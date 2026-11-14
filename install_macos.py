#!/usr/bin/env python3
"""System-wide installer and updater for Arii on macOS.

The installer supports native Apple Silicon (arm64) and Intel (x86_64) Macs.
It installs Arii, Python 3.12 and the R scientific runtime in an isolated
directory, creates /Applications/Arii.app and provides compact update commands.

Typical use from a clone of the Arii repository:

    python3 install_macos.py

The script uses only the Python standard library before provisioning its own
runtime. It intentionally refuses to install from a process translated by
Rosetta so Python, Qt and R cannot be mixed across architectures.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import plistlib
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path


APP_NAME = "Arii"
REPOSITORY_URL = "https://github.com/EXCI5ION/Arii.git"

SUPPORT_DIR = Path("/Library/Application Support/Arii")
SOURCE_DIR = SUPPORT_DIR / "source"
RUNTIMES_DIR = SUPPORT_DIR / "runtimes"
RUNTIME_DIR = SUPPORT_DIR / "runtime"
RUNTIME_PYTHON = RUNTIME_DIR / "bin/python"
RUNTIME_PIP = RUNTIME_DIR / "bin/pip"
RUNTIME_RSCRIPT = RUNTIME_DIR / "bin/Rscript"
RUNTIME_CLI = RUNTIME_DIR / "bin/arii"
RUNTIME_GUI = RUNTIME_DIR / "bin/arii-gui"

MAMBA_ROOT = SUPPORT_DIR / "mamba"
MICROMAMBA = SUPPORT_DIR / "tools/micromamba"
MICROMAMBA_PLATFORM_FILE = SUPPORT_DIR / "tools/platform"

APP_BUNDLE = Path("/Applications/Arii.app")
APP_CONTENTS = APP_BUNDLE / "Contents"
APP_EXECUTABLE = APP_CONTENTS / "MacOS/Arii"
APP_RESOURCES = APP_CONTENTS / "Resources"
APP_ICON = APP_RESOURCES / "Arii.icns"
INFO_PLIST = APP_CONTENTS / "Info.plist"

GLOBAL_CLI = Path("/usr/local/bin/arii")
GLOBAL_GUI = Path("/usr/local/bin/arii-gui")
UPDATER_COMMAND = Path("/usr/local/bin/arii-update")
INSTALLED_INSTALLER = SUPPORT_DIR / "install_macos.py"
PERSISTENT_CUSTOM_ICON = SUPPORT_DIR / "custom-icon.png"

STABLE_TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
MINIMUM_FREE_BYTES = 8 * 1024**3
MINIMUM_MACOS = (13, 0)
MINIMUM_BOOTSTRAP_PYTHON = (3, 9)
MICROMAMBA_VERSION = "2.9.0-0"
MICROMAMBA_DOWNLOADS = {
    "osx-arm64": (
        "https://github.com/mamba-org/micromamba-releases/releases/download/"
        "2.9.0-0/micromamba-osx-arm64.tar.bz2",
        "ec2a072f028e1a7cf20f3e2e74d5a8127cf5a5f27636375b5359811565f4e5be",
    ),
    "osx-64": (
        "https://github.com/mamba-org/micromamba-releases/releases/download/"
        "2.9.0-0/micromamba-osx-64.tar.bz2",
        "1e71054bb3ac9a076e21f7ec48acfef536f9b3f1408f371a942784bf5ef83d8a",
    ),
}

RUNTIME_PACKAGES = (
    "python=3.12",
    "pip",
    "r-base=4.5.3",
    "bioconductor-mixomics=6.34.0",
    "r-jsonlite=2.0.0",
)


class InstallerError(RuntimeError):
    """Expected installation error with a user-facing message."""


def print_step(message: str) -> None:
    print(f"\n==> {message}", flush=True)


def command_text(command: list[str]) -> str:
    return " ".join(subprocess.list2cmdline([item]) for item in command)


def run(
    command: list[str],
    *,
    capture: bool = False,
    env: dict[str, str] | None = None,
    show: bool = True,
) -> subprocess.CompletedProcess[str]:
    if show:
        print(f"    $ {command_text(command)}", flush=True)
    return subprocess.run(
        command,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        env=env,
    )


def output(
    command: list[str],
    *,
    env: dict[str, str] | None = None,
    show: bool = True,
) -> str:
    return run(command, capture=True, env=env, show=show).stdout.strip()


def running_under_rosetta() -> bool:
    result = subprocess.run(
        ["/usr/sbin/sysctl", "-in", "sysctl.proc_translated"],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    return result.stdout.strip() == "1"


def require_bootstrap_python() -> None:
    if sys.version_info[:2] < MINIMUM_BOOTSTRAP_PYTHON:
        required = ".".join(map(str, MINIMUM_BOOTSTRAP_PYTHON))
        detected = f"{sys.version_info.major}.{sys.version_info.minor}"
        raise InstallerError(
            f"El instalador necesita Python {required} o posterior para iniciar; "
            f"se detectó Python {detected}."
        )


def macos_version() -> tuple[int, int]:
    text = platform.mac_ver()[0]
    try:
        major, minor, *_rest = (int(part) for part in text.split("."))
    except (TypeError, ValueError):
        raise InstallerError("No se pudo determinar la versión de macOS.")
    return major, minor


def detect_macos_platform() -> tuple[str, str]:
    if sys.platform != "darwin":
        raise InstallerError("Este instalador solamente puede ejecutarse en macOS.")
    if running_under_rosetta():
        raise InstallerError(
            "Terminal o Python está ejecutándose mediante Rosetta. Abra una "
            "Terminal nativa y vuelva a ejecutar el instalador para evitar "
            "mezclar componentes Intel y Apple Silicon."
        )

    detected_macos = macos_version()
    if detected_macos < MINIMUM_MACOS:
        detected = ".".join(map(str, detected_macos))
        required = ".".join(map(str, MINIMUM_MACOS))
        raise InstallerError(
            f"Arii requiere macOS {required} o posterior; se detectó {detected}."
        )

    machine = platform.machine().lower()
    if machine == "arm64":
        return machine, "osx-arm64"
    if machine in {"x86_64", "amd64"}:
        return "x86_64", "osx-64"
    raise InstallerError(f"Arquitectura de Mac no compatible: {machine}")


def require_system_tools() -> None:
    missing = [name for name in ("git", "sips", "iconutil") if not shutil.which(name)]
    if missing:
        names = ", ".join(missing)
        raise InstallerError(
            f"Faltan herramientas de macOS: {names}. Ejecute "
            "'xcode-select --install', complete la instalación y vuelva a intentarlo."
        )


def reexec_with_sudo() -> None:
    if os.geteuid() == 0:
        return
    sudo = shutil.which("sudo")
    if sudo is None:
        raise InstallerError("Se necesitan privilegios administrativos y no se encontró sudo.")
    script = str(Path(__file__).resolve())
    print("Se solicitará la contraseña de la cuenta administradora de la Mac.")
    os.execv(sudo, [sudo, sys.executable, script, *sys.argv[1:]])


def verify_free_space() -> None:
    available = shutil.disk_usage("/Library").free
    if available < MINIMUM_FREE_BYTES:
        gib = available / 1024**3
        raise InstallerError(
            "Arii necesita al menos 8 GiB libres durante la instalación; "
            f"hay {gib:.1f} GiB disponibles."
        )


def repository_is_dirty(*, quiet: bool = False) -> bool:
    status = output(
        [
            "git",
            "-C",
            str(SOURCE_DIR),
            "status",
            "--porcelain",
            "--untracked-files=no",
        ],
        show=not quiet,
    )
    return bool(status)


def prepare_repository(*, quiet: bool = False) -> str | None:
    if not quiet:
        print_step("Preparando el repositorio de Arii")
    previous_commit: str | None = None
    if SOURCE_DIR.exists():
        if not (SOURCE_DIR / ".git").is_dir():
            raise InstallerError(
                f"{SOURCE_DIR} ya existe pero no es un repositorio Git de Arii."
            )
        if repository_is_dirty(quiet=quiet):
            raise InstallerError(
                f"Hay modificaciones locales en {SOURCE_DIR}. La instalación se "
                "detuvo para no sobrescribirlas."
            )
        previous_commit = output(
            ["git", "-C", str(SOURCE_DIR), "rev-parse", "HEAD"],
            show=not quiet,
        )
    else:
        SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
        run(["git", "clone", REPOSITORY_URL, str(SOURCE_DIR)], show=not quiet)
    run(
        ["git", "-C", str(SOURCE_DIR), "fetch", "--tags", "--prune", "origin"],
        capture=quiet,
        show=not quiet,
    )
    return previous_commit


def stable_tags(*, quiet: bool = False) -> list[tuple[tuple[int, int, int], str]]:
    tags = output(
        ["git", "-C", str(SOURCE_DIR), "tag", "--list"],
        show=not quiet,
    ).splitlines()
    parsed: list[tuple[tuple[int, int, int], str]] = []
    for tag in tags:
        match = STABLE_TAG.fullmatch(tag.strip())
        if match:
            parsed.append((tuple(map(int, match.groups())), tag.strip()))
    return sorted(parsed, reverse=True)


def resolve_target_tag(
    requested_version: str | None,
    repair: bool,
    *,
    quiet: bool = False,
) -> str:
    if requested_version:
        tag = f"v{requested_version.removeprefix('v')}"
        if not STABLE_TAG.fullmatch(tag):
            raise InstallerError(
                f"Versión no válida: {requested_version}. Use un formato como 1.0.1."
            )
        if tag not in {item[1] for item in stable_tags(quiet=quiet)}:
            raise InstallerError(f"La versión {tag} no existe en el repositorio.")
        return tag

    if repair and (SOURCE_DIR / ".git").is_dir():
        pointed = output(
            ["git", "-C", str(SOURCE_DIR), "tag", "--points-at", "HEAD"],
            show=not quiet,
        ).splitlines()
        current = [tag for tag in pointed if STABLE_TAG.fullmatch(tag)]
        if current:
            return max(
                current,
                key=lambda tag: tuple(
                    map(int, STABLE_TAG.fullmatch(tag).groups())  # type: ignore[union-attr]
                ),
            )

    tags = stable_tags(quiet=quiet)
    if not tags:
        raise InstallerError("No se encontró ninguna versión estable de Arii.")
    return tags[0][1]


def checkout_release(tag: str) -> None:
    print_step(f"Seleccionando Arii {tag.removeprefix('v')}")
    run(["git", "-C", str(SOURCE_DIR), "switch", "--detach", tag])


def download_micromamba(conda_platform: str) -> None:
    installed_platform = ""
    if MICROMAMBA_PLATFORM_FILE.is_file():
        installed_platform = MICROMAMBA_PLATFORM_FILE.read_text(
            encoding="utf-8"
        ).strip()
    marker = f"{MICROMAMBA_VERSION}:{conda_platform}"
    if MICROMAMBA.is_file() and installed_platform == marker:
        return

    print_step(f"Descargando micromamba para {conda_platform}")
    MICROMAMBA.parent.mkdir(parents=True, exist_ok=True)
    try:
        download_url, expected_sha256 = MICROMAMBA_DOWNLOADS[conda_platform]
    except KeyError as exc:
        raise InstallerError(
            f"No hay una descarga fijada de micromamba para {conda_platform}."
        ) from exc
    request = urllib.request.Request(
        download_url,
        headers={"User-Agent": "Arii-macOS-Installer/1"},
    )
    with tempfile.TemporaryDirectory(prefix="arii-micromamba-") as temporary:
        archive = Path(temporary) / "micromamba.tar.bz2"
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                with archive.open("wb") as destination:
                    shutil.copyfileobj(response, destination)
        except OSError as exc:
            raise InstallerError("No se pudo descargar micromamba.") from exc
        actual_sha256 = hashlib.sha256(archive.read_bytes()).hexdigest()
        if actual_sha256 != expected_sha256:
            raise InstallerError(
                "La descarga de micromamba no coincide con su SHA-256 publicado."
            )
        try:
            with tarfile.open(archive, mode="r:bz2") as package:
                member = package.getmember("bin/micromamba")
                source = package.extractfile(member)
                if source is None:
                    raise InstallerError("El paquete de micromamba está incompleto.")
                temporary_binary = MICROMAMBA.with_suffix(".new")
                with temporary_binary.open("wb") as destination:
                    shutil.copyfileobj(source, destination)
                temporary_binary.chmod(0o755)
                temporary_binary.replace(MICROMAMBA)
        except (tarfile.TarError, KeyError) as exc:
            raise InstallerError("No se pudo extraer micromamba.") from exc

    MICROMAMBA_PLATFORM_FILE.write_text(f"{marker}\n", encoding="utf-8")
    MICROMAMBA_PLATFORM_FILE.chmod(0o644)


def mamba_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment["MAMBA_ROOT_PREFIX"] = str(MAMBA_ROOT)
    environment["MAMBA_NO_BANNER"] = "1"
    return environment


def install_runtime(conda_platform: str, target_tag: str) -> Path:
    download_micromamba(conda_platform)
    print_step("Instalando Python, R y el motor científico privado")
    RUNTIMES_DIR.mkdir(parents=True, exist_ok=True)
    prefix = f"{target_tag.removeprefix('v')}-{conda_platform}-"
    candidate = Path(tempfile.mkdtemp(prefix=prefix, dir=RUNTIMES_DIR))
    candidate.rmdir()
    try:
        run(
            [
                str(MICROMAMBA),
                "create",
                "--yes",
                "--channel-priority",
                "strict",
                "--channel",
                "conda-forge",
                "--channel",
                "bioconda",
                "--platform",
                conda_platform,
                "--prefix",
                str(candidate),
                *RUNTIME_PACKAGES,
            ],
            env=mamba_environment(),
        )
    except (InstallerError, OSError, subprocess.CalledProcessError):
        if candidate.exists():
            shutil.rmtree(candidate)
        raise
    for path in (
        candidate / "bin/python",
        candidate / "bin/pip",
        candidate / "bin/Rscript",
    ):
        if not path.is_file():
            shutil.rmtree(candidate)
            raise InstallerError(f"El runtime no creó el ejecutable esperado: {path}")
    return candidate


def install_python_application(
    runtime_dir: Path, *, force_reinstall: bool
) -> None:
    print_step("Instalando Arii y sus dependencias Python")
    python = runtime_dir / "bin/python"
    run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--no-cache-dir",
            "--upgrade",
            "pip",
            "setuptools",
            "wheel",
        ]
    )
    command = [
        str(python),
        "-m",
        "pip",
        "install",
        "--no-cache-dir",
        "--upgrade",
    ]
    if force_reinstall:
        command.append("--force-reinstall")
    command.extend(["--editable", str(SOURCE_DIR)])
    run(command)
    if not (runtime_dir / "bin/arii").is_file() or not (
        runtime_dir / "bin/arii-gui"
    ).is_file():
        raise InstallerError("La instalación Python no creó los ejecutables de Arii.")


def validate_health_report(report: object) -> None:
    if not isinstance(report, dict):
        raise InstallerError("El motor científico de R no devolvió un informe válido.")
    packages = report.get("packages")
    if report.get("status") != "ok" or not isinstance(packages, list):
        raise InstallerError("El motor científico de R no informó un estado correcto.")
    if not all(
        isinstance(package, dict) and package.get("installed") is True
        for package in packages
    ):
        raise InstallerError("Faltan paquetes científicos en el runtime privado de R.")


def verify_candidate_runtime(runtime_dir: Path) -> None:
    print_step("Validando el runtime candidato")
    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = "offscreen"
    run(
        [
            str(runtime_dir / "bin/python"),
            "-c",
            (
                "import arii, numpy, pyqtgraph, PySide6; "
                "from PySide6.QtWidgets import QApplication; "
                "app = QApplication([]); print(PySide6.__version__)"
            ),
        ],
        env=environment,
    )
    cocoa_plugins = list(
        runtime_dir.glob(
            "lib/python*/site-packages/PySide6/Qt/plugins/platforms/"
            "libqcocoa.dylib"
        )
    )
    if not cocoa_plugins:
        raise InstallerError("El runtime candidato no contiene el plugin Cocoa.")
    health_text = output(
        [str(runtime_dir / "bin/Rscript"), str(SOURCE_DIR / "r/health.R")]
    )
    try:
        validate_health_report(json.loads(health_text))
    except json.JSONDecodeError as exc:
        raise InstallerError("El motor R devolvió una respuesta no válida.") from exc


def activate_runtime(candidate: Path) -> Path | None:
    """Atomically point the stable runtime path at a validated candidate."""

    previous: Path | None = None
    if RUNTIME_DIR.is_symlink():
        previous = RUNTIME_DIR.resolve(strict=False)
    elif RUNTIME_DIR.exists():
        RUNTIMES_DIR.mkdir(parents=True, exist_ok=True)
        previous = RUNTIMES_DIR / f"legacy-{os.getpid()}"
        if previous.exists():
            raise InstallerError(f"Ya existe el runtime de migración: {previous}")
        RUNTIME_DIR.replace(previous)
    temporary_link = SUPPORT_DIR / ".runtime-link.new"
    try:
        temporary_link.unlink(missing_ok=True)
        temporary_link.symlink_to(candidate, target_is_directory=True)
        os.replace(temporary_link, RUNTIME_DIR)
    except OSError:
        temporary_link.unlink(missing_ok=True)
        if previous is not None and not RUNTIME_DIR.exists():
            previous.replace(RUNTIME_DIR)
        raise
    return previous


def restore_runtime(previous: Path | None) -> None:
    if previous is None:
        RUNTIME_DIR.unlink(missing_ok=True)
        return
    temporary_link = SUPPORT_DIR / ".runtime-link.rollback"
    temporary_link.unlink(missing_ok=True)
    temporary_link.symlink_to(previous, target_is_directory=True)
    os.replace(temporary_link, RUNTIME_DIR)


def remove_managed_runtime(runtime_dir: Path | None) -> None:
    if runtime_dir is None or not runtime_dir.exists():
        return
    if runtime_dir.parent != RUNTIMES_DIR:
        raise InstallerError(f"Ruta de runtime inesperada: {runtime_dir}")
    shutil.rmtree(runtime_dir)


def write_executable(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.new")
    temporary.write_text(content, encoding="utf-8")
    temporary.chmod(0o755)
    temporary.replace(path)


def runtime_launcher(entrypoint: Path) -> str:
    return (
        "#!/bin/sh\n"
        f"export ARII_RSCRIPT='{RUNTIME_RSCRIPT}'\n"
        f"export PATH='{RUNTIME_DIR / 'bin'}:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin\n"
        f"exec '{entrypoint}' \"$@\"\n"
    )


def select_icon(custom_icon: Path | None) -> Path:
    if custom_icon is not None:
        PERSISTENT_CUSTOM_ICON.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(custom_icon, PERSISTENT_CUSTOM_ICON)
        PERSISTENT_CUSTOM_ICON.chmod(0o644)
    if PERSISTENT_CUSTOM_ICON.is_file():
        return PERSISTENT_CUSTOM_ICON
    source = SOURCE_DIR / "assets/icons/arii-1024.png"
    if not source.is_file():
        raise InstallerError(f"No se encontró el icono de Arii: {source}")
    return source


def create_icns(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="arii-icon-") as temporary:
        iconset = Path(temporary) / "Arii.iconset"
        iconset.mkdir()
        variants = {
            "icon_16x16.png": 16,
            "icon_16x16@2x.png": 32,
            "icon_32x32.png": 32,
            "icon_32x32@2x.png": 64,
            "icon_128x128.png": 128,
            "icon_128x128@2x.png": 256,
            "icon_256x256.png": 256,
            "icon_256x256@2x.png": 512,
            "icon_512x512.png": 512,
            "icon_512x512@2x.png": 1024,
        }
        for name, size in variants.items():
            run(
                [
                    "sips",
                    "-s",
                    "format",
                    "png",
                    "-z",
                    str(size),
                    str(size),
                    str(source),
                    "--out",
                    str(iconset / name),
                ],
                capture=True,
            )
        temporary_icns = Path(temporary) / "Arii.icns"
        run(
            ["iconutil", "-c", "icns", str(iconset), "-o", str(temporary_icns)]
        )
        shutil.copy2(temporary_icns, destination)
        destination.chmod(0o644)


def write_info_plist(version: str) -> None:
    data = {
        "CFBundleDevelopmentRegion": "es",
        "CFBundleDisplayName": "Arii",
        "CFBundleExecutable": "Arii",
        "CFBundleIconFile": "Arii.icns",
        "CFBundleIdentifier": "org.excision.arii",
        "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundleName": "Arii",
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": version,
        "CFBundleVersion": version,
        "NSHighResolutionCapable": True,
        "NSPrincipalClass": "NSApplication",
        "LSMinimumSystemVersion": "13.0",
    }
    INFO_PLIST.parent.mkdir(parents=True, exist_ok=True)
    with INFO_PLIST.open("wb") as stream:
        plistlib.dump(data, stream, fmt=plistlib.FMT_XML, sort_keys=True)
    INFO_PLIST.chmod(0o644)


def install_integration(custom_icon: Path | None, version: str) -> None:
    print_step("Creando Arii.app y los comandos globales")
    APP_EXECUTABLE.parent.mkdir(parents=True, exist_ok=True)
    APP_RESOURCES.mkdir(parents=True, exist_ok=True)
    write_executable(APP_EXECUTABLE, runtime_launcher(RUNTIME_GUI))
    create_icns(select_icon(custom_icon), APP_ICON)
    write_info_plist(version)

    write_executable(GLOBAL_CLI, runtime_launcher(RUNTIME_CLI))
    write_executable(GLOBAL_GUI, runtime_launcher(APP_EXECUTABLE))

    codesign = shutil.which("codesign")
    if codesign:
        run(
            [codesign, "--force", "--sign", "-", str(APP_BUNDLE)],
            capture=True,
        )


def install_updater() -> None:
    print_step("Instalando el actualizador")
    source_installer = SOURCE_DIR / "install_macos.py"
    source = source_installer if source_installer.is_file() else Path(__file__).resolve()
    if source.resolve() != INSTALLED_INSTALLER.resolve():
        shutil.copy2(source, INSTALLED_INSTALLER)
    INSTALLED_INSTALLER.chmod(0o755)
    write_executable(
        UPDATER_COMMAND,
        "#!/bin/sh\n"
        "if [ \"$#\" -eq 0 ]; then\n"
        "    set -- --update\n"
        "fi\n"
        f"exec '{RUNTIME_PYTHON}' '{INSTALLED_INSTALLER}' \"$@\"\n",
    )


def installed_version(*, quiet: bool = False) -> str:
    return output(
        [
            str(RUNTIME_PYTHON),
            "-c",
            "from importlib.metadata import version; print(version('arii'))",
        ],
        show=not quiet,
    )


def installation_matches_release(expected_tag: str) -> bool:
    required = (
        SOURCE_DIR / ".git",
        RUNTIME_PYTHON,
        RUNTIME_RSCRIPT,
        RUNTIME_CLI,
        RUNTIME_GUI,
        APP_EXECUTABLE,
        INFO_PLIST,
        GLOBAL_CLI,
        GLOBAL_GUI,
        UPDATER_COMMAND,
    )
    if not all(path.exists() for path in required):
        return False
    try:
        installed = installed_version(quiet=True)
        head = output(
            ["git", "-C", str(SOURCE_DIR), "rev-parse", "HEAD"], show=False
        )
        release_commit = output(
            ["git", "-C", str(SOURCE_DIR), "rev-list", "-n", "1", expected_tag],
            show=False,
        )
    except subprocess.CalledProcessError:
        return False
    return installed == expected_tag.removeprefix("v") and head == release_commit


def report_already_current(target_tag: str) -> None:
    print(f"Arii ya está en la última versión estable: {target_tag}")


def verify_cocoa_plugin() -> None:
    plugins = list(
        RUNTIME_DIR.glob(
            "lib/python*/site-packages/PySide6/Qt/plugins/platforms/libqcocoa.dylib"
        )
    )
    if not plugins:
        raise InstallerError("No se encontró el plugin gráfico Cocoa de PySide6.")


def verify_installation(expected_tag: str, expected_platform: str) -> None:
    print_step("Verificando la instalación")
    version = installed_version()
    expected = expected_tag.removeprefix("v")
    if version != expected:
        raise InstallerError(f"Se esperaba Arii {expected}, pero se instaló {version}.")
    verify_cocoa_plugin()

    health = output([str(GLOBAL_CLI), "r-health"])
    try:
        report = json.loads(health)
    except json.JSONDecodeError as exc:
        raise InstallerError("El motor R devolvió una respuesta no válida.") from exc
    validate_health_report(report)

    print(f"\nArii {version} se instaló correctamente para {expected_platform}.")
    print("Puede abrirlo desde Aplicaciones → Arii o ejecutar: arii-gui")
    print("Para actualizarlo: sudo arii-update")


def restore_previous_release(previous_commit: str | None) -> None:
    if previous_commit is None:
        return
    print("\nLa instalación falló. Restaurando la revisión anterior...", file=sys.stderr)
    try:
        run(["git", "-C", str(SOURCE_DIR), "switch", "--detach", previous_commit])
        if RUNTIME_PYTHON.is_file():
            run(
                [
                    str(RUNTIME_PYTHON),
                    "-m",
                    "pip",
                    "install",
                    "--no-cache-dir",
                    "--force-reinstall",
                    "--editable",
                    str(SOURCE_DIR),
                ]
            )
    except (InstallerError, subprocess.CalledProcessError) as exc:
        print(f"No se pudo completar la restauración: {exc}", file=sys.stderr)


def confirm_uninstall(assume_yes: bool) -> None:
    if assume_yes:
        return
    if not sys.stdin.isatty():
        raise InstallerError("Use --yes para desinstalar sin confirmación interactiva.")
    answer = input(
        "Esto eliminará Arii, Arii.app y su runtime privado. "
        "Escriba DESINSTALAR para continuar: "
    )
    if answer != "DESINSTALAR":
        raise InstallerError("Desinstalación cancelada.")


def uninstall(assume_yes: bool) -> None:
    confirm_uninstall(assume_yes)
    print_step("Desinstalando Arii")
    for path in (GLOBAL_CLI, GLOBAL_GUI, UPDATER_COMMAND):
        path.unlink(missing_ok=True)
    if APP_BUNDLE.exists():
        shutil.rmtree(APP_BUNDLE)
    if SUPPORT_DIR.exists():
        shutil.rmtree(SUPPORT_DIR)
    print("Arii fue desinstalado. Los proyectos y datos personales no se modificaron.")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Instala, actualiza, repara o desinstala Arii en macOS."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--update", action="store_true", help="actualiza a la versión estable más reciente"
    )
    mode.add_argument(
        "--repair", action="store_true", help="reinstala y verifica todos los componentes"
    )
    mode.add_argument("--uninstall", action="store_true", help="desinstala Arii")
    parser.add_argument(
        "--version",
        dest="release_version",
        metavar="X.Y.Z",
        help="instala una versión estable concreta",
    )
    parser.add_argument(
        "requested_version",
        nargs="?",
        metavar="X.Y.Z",
        help="versión concreta; forma abreviada utilizada por arii-update",
    )
    parser.add_argument(
        "--icon",
        type=Path,
        help="utiliza un PNG alternativo como icono de Arii.app",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="confirma operaciones no interactivas, como la desinstalación",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_arguments()
    try:
        require_bootstrap_python()
        architecture, conda_platform = detect_macos_platform()
        require_system_tools()
        reexec_with_sudo()

        if args.uninstall:
            uninstall(args.yes)
            return 0

        custom_icon = args.icon.expanduser().resolve() if args.icon else None
        if custom_icon is not None and not custom_icon.is_file():
            raise InstallerError(f"No se encontró el icono solicitado: {custom_icon}")
        if args.release_version and args.requested_version:
            raise InstallerError("Indique la versión una sola vez.")
        requested = args.release_version or args.requested_version

        existing_update = args.update and (SOURCE_DIR / ".git").is_dir()
        if existing_update:
            try:
                current_version = installed_version(quiet=True)
            except subprocess.CalledProcessError:
                current_version = "desconocida"
            print(f"Versión instalada: {current_version}")
            print("Buscando versiones disponibles...")
            previous_commit = prepare_repository(quiet=True)
        else:
            verify_free_space()
            previous_commit = prepare_repository()

        target_tag = resolve_target_tag(
            requested,
            args.repair,
            quiet=existing_update,
        )

        if args.update and installation_matches_release(target_tag):
            if custom_icon is not None:
                install_integration(custom_icon, target_tag.removeprefix("v"))
            report_already_current(target_tag)
            return 0

        if existing_update:
            print(f"Nueva versión estable disponible: {target_tag}")
            verify_free_space()

        candidate_runtime: Path | None = None
        previous_runtime: Path | None = None
        runtime_activated = False
        try:
            checkout_release(target_tag)
            candidate_runtime = install_runtime(conda_platform, target_tag)
            install_python_application(
                candidate_runtime, force_reinstall=args.repair
            )
            verify_candidate_runtime(candidate_runtime)
            previous_runtime = activate_runtime(candidate_runtime)
            runtime_activated = True
            version = target_tag.removeprefix("v")
            install_integration(custom_icon, version)
            install_updater()
            verify_installation(target_tag, conda_platform)
        except (InstallerError, OSError, subprocess.CalledProcessError):
            if runtime_activated:
                try:
                    restore_runtime(previous_runtime)
                except OSError as rollback_error:
                    print(
                        "No se pudo restaurar el enlace al runtime anterior: "
                        f"{rollback_error}",
                        file=sys.stderr,
                    )
            try:
                remove_managed_runtime(candidate_runtime)
            finally:
                restore_previous_release(previous_commit)
            raise
        remove_managed_runtime(previous_runtime)

        print(f"Arquitectura detectada: {architecture}")
        return 0
    except InstallerError as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        failed = (
            [str(item) for item in exc.cmd]
            if isinstance(exc.cmd, (list, tuple))
            else [str(exc.cmd)]
        )
        print(
            f"\nError: el comando terminó con código {exc.returncode}: "
            f"{command_text(failed)}",
            file=sys.stderr,
        )
        if exc.stderr:
            print(exc.stderr.strip(), file=sys.stderr)
        return exc.returncode or 1
    except OSError as exc:
        print(f"\nError del sistema durante la instalación: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())


