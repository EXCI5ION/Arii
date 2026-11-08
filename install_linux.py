#!/usr/bin/env python3
"""System-wide installer and updater for Arii on Debian-based Linux.

Run from a clone of the Arii repository:

    python3 install_linux.py

The installer relaunches itself with sudo, installs the latest stable Arii
release under /opt, creates an isolated Python environment and provisions a
private R runtime with the exact scientific packages required by Arii.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
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
APP_DIR = Path("/opt/arii")
VENV_DIR = APP_DIR / ".venv"
VENV_PYTHON = VENV_DIR / "bin" / "python"
VENV_CLI = VENV_DIR / "bin" / "arii"
VENV_GUI = VENV_DIR / "bin" / "arii-gui"

RUNTIME_DIR = Path("/opt/arii-runtime")
RSCRIPT = RUNTIME_DIR / "bin" / "Rscript"
MAMBA_ROOT = Path("/opt/arii-mamba")
MICROMAMBA = Path("/usr/local/lib/arii/micromamba")
MICROMAMBA_URL = "https://micro.mamba.pm/api/micromamba/linux-64/latest"

GLOBAL_CLI = Path("/usr/local/bin/arii")
GLOBAL_GUI = Path("/usr/local/bin/arii-gui")
UPDATER_COMMAND = Path("/usr/local/sbin/arii-update")
INSTALLED_INSTALLER = Path("/usr/local/lib/arii/install_linux.py")
DESKTOP_FILE = Path("/usr/share/applications/arii.desktop")
ICON_ROOT = Path("/usr/share/icons/hicolor")
PERSISTENT_CUSTOM_ICON = Path("/usr/local/share/arii/custom-icon.png")
QT_STYLE_CONFIG = Path("/usr/local/share/arii/qt-style")

STABLE_TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
PYTHON_COMMAND = Path("/usr/bin/python3")
PYTHON_SUPPORTED = {(3, 12), (3, 13)}
MINIMUM_FREE_BYTES = 6 * 1024**3

DEBIAN_PACKAGES = (
    "git",
    "python3",
    "python3-venv",
    "desktop-file-utils",
    "hicolor-icon-theme",
    "ca-certificates",
    "curl",
    "bzip2",
    "gnome-keyring",
    "libsecret-1-0",
    "libdbus-1-3",
    "libegl1",
    "libgl1",
    "libxcb-cursor0",
    "libxcb-icccm4",
    "libxcb-image0",
    "libxcb-keysyms1",
    "libxcb-render-util0",
    "libxcb-xinerama0",
    "libxkbcommon-x11-0",
)


class InstallerError(RuntimeError):
    """Expected installation error with a concise user-facing message."""


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


def parse_os_release(path: Path = Path("/etc/os-release")) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise InstallerError("No se pudo leer /etc/os-release.") from exc
    for line in lines:
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value.strip().strip('"').strip("'")
    return values


def require_supported_system() -> None:
    info = parse_os_release()
    identifiers = {info.get("ID", "").lower()}
    identifiers.update(info.get("ID_LIKE", "").lower().split())
    if not identifiers.intersection({"debian", "ubuntu"}):
        name = info.get("PRETTY_NAME", info.get("ID", "desconocido"))
        raise InstallerError(
            "Este instalador admite Debian, Ubuntu y sus derivados. "
            f"Sistema detectado: {name}."
        )
    if platform.machine().lower() not in {"x86_64", "amd64"}:
        raise InstallerError(
            "El runtime científico automático de Arii está disponible por ahora "
            "solamente para Linux x86-64."
        )
    if shutil.which("apt-get") is None:
        raise InstallerError("No se encontró apt-get.")


def reexec_with_sudo() -> None:
    if os.geteuid() == 0:
        return
    sudo = shutil.which("sudo")
    if sudo is None:
        raise InstallerError(
            "Se necesitan privilegios administrativos y no se encontró sudo."
        )
    script = str(Path(__file__).resolve())
    print("Se solicitarán permisos administrativos para instalar Arii.")
    os.execv(sudo, [sudo, sys.executable, script, *sys.argv[1:]])


def install_system_dependencies(*, skip_apt_update: bool) -> None:
    print_step("Instalando dependencias del sistema")
    environment = os.environ.copy()
    environment["DEBIAN_FRONTEND"] = "noninteractive"
    if not skip_apt_update:
        run(["apt-get", "update"], env=environment)
    run(["apt-get", "install", "-y", *DEBIAN_PACKAGES], env=environment)


def verify_python() -> None:
    if not PYTHON_COMMAND.is_file():
        raise InstallerError(f"No se encontró {PYTHON_COMMAND}.")
    version_text = output(
        [
            str(PYTHON_COMMAND),
            "-c",
            "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')",
        ]
    )
    major, minor = map(int, version_text.split(".", 1))
    if (major, minor) not in PYTHON_SUPPORTED:
        raise InstallerError(
            "Arii admite Python 3.12 o 3.13; "
            f"el intérprete predeterminado es Python {version_text}."
        )


def verify_free_space() -> None:
    available = shutil.disk_usage("/opt").free
    if available < MINIMUM_FREE_BYTES:
        available_gib = available / 1024**3
        raise InstallerError(
            "Arii necesita al menos 6 GiB libres durante la instalación; "
            f"hay {available_gib:.1f} GiB disponibles en /opt."
        )


def repository_is_dirty() -> bool:
    status = output(
        [
            "git",
            "-C",
            str(APP_DIR),
            "status",
            "--porcelain",
            "--untracked-files=no",
        ]
    )
    return bool(status)


def prepare_repository(*, quiet: bool = False) -> str | None:
    if not quiet:
        print_step("Preparando el repositorio de Arii")
    previous_commit: str | None = None
    if APP_DIR.exists():
        if not (APP_DIR / ".git").is_dir():
            raise InstallerError(
                f"{APP_DIR} ya existe pero no es un repositorio Git de Arii."
            )
        if repository_is_dirty():
            raise InstallerError(
                f"Hay modificaciones locales en {APP_DIR}. La instalación se "
                "detuvo para no sobrescribirlas."
            )
        previous_commit = output(
            ["git", "-C", str(APP_DIR), "rev-parse", "HEAD"],
            show=not quiet,
        )
    else:
        APP_DIR.parent.mkdir(parents=True, exist_ok=True)
        run(["git", "clone", REPOSITORY_URL, str(APP_DIR)])
    run(
        ["git", "-C", str(APP_DIR), "fetch", "--tags", "--prune", "origin"],
        capture=quiet,
        show=not quiet,
    )
    return previous_commit


def stable_tags(*, quiet: bool = False) -> list[tuple[tuple[int, int, int], str]]:
    tags = output(
        ["git", "-C", str(APP_DIR), "tag", "--list"],
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
                f"Versión no válida: {requested_version}. Usa un formato como 1.0.1."
            )
        if tag not in {item[1] for item in stable_tags(quiet=quiet)}:
            raise InstallerError(f"La versión {tag} no existe en el repositorio.")
        return tag
    if repair and (APP_DIR / ".git").is_dir():
        pointed = output(
            ["git", "-C", str(APP_DIR), "tag", "--points-at", "HEAD"],
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
    run(["git", "-C", str(APP_DIR), "switch", "--detach", tag])


def create_or_update_python_environment(*, force_reinstall: bool) -> None:
    print_step("Creando el entorno Python de Arii")
    if not VENV_PYTHON.is_file():
        run([str(PYTHON_COMMAND), "-m", "venv", str(VENV_DIR)])
    run(
        [
            str(VENV_PYTHON),
            "-m",
            "pip",
            "install",
            "--upgrade",
            "pip",
            "setuptools",
            "wheel",
        ]
    )
    command = [
        str(VENV_PYTHON),
        "-m",
        "pip",
        "install",
        "--no-cache-dir",
        "--upgrade",
    ]
    if force_reinstall:
        command.append("--force-reinstall")
    # Editable mode is intentional: Arii's R workers and image assets live at
    # the repository root and resources.py resolves them relative to src/arii.
    command.extend(["--editable", str(APP_DIR), "secretstorage>=3.3"])
    run(command)


def download_micromamba() -> None:
    if MICROMAMBA.is_file():
        return
    print_step("Descargando el gestor del runtime científico")
    MICROMAMBA.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(
        MICROMAMBA_URL,
        headers={"User-Agent": "Arii-Linux-Installer/1"},
    )
    with tempfile.TemporaryDirectory(prefix="arii-micromamba-") as temporary:
        archive = Path(temporary) / "micromamba.tar.bz2"
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                with archive.open("wb") as destination:
                    shutil.copyfileobj(response, destination)
        except OSError as exc:
            raise InstallerError("No se pudo descargar micromamba.") from exc
        try:
            with tarfile.open(archive, mode="r:bz2") as package:
                member = package.getmember("bin/micromamba")
                source = package.extractfile(member)
                if source is None:
                    raise InstallerError("El paquete de micromamba está incompleto.")
                with MICROMAMBA.open("wb") as destination:
                    shutil.copyfileobj(source, destination)
        except (tarfile.TarError, KeyError) as exc:
            MICROMAMBA.unlink(missing_ok=True)
            raise InstallerError("No se pudo extraer micromamba.") from exc
    MICROMAMBA.chmod(0o755)


def mamba_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment["MAMBA_ROOT_PREFIX"] = str(MAMBA_ROOT)
    environment["MAMBA_NO_BANNER"] = "1"
    return environment


def install_scientific_runtime(*, force_reinstall: bool) -> None:
    specification = APP_DIR / "cluster" / "environment-linux-64.yml"
    if not specification.is_file():
        raise InstallerError(f"No se encontró la especificación de R: {specification}")
    download_micromamba()
    print_step("Instalando el runtime privado de R y mixOmics")
    if force_reinstall and RUNTIME_DIR.exists():
        shutil.rmtree(RUNTIME_DIR)
    operation = "install" if RSCRIPT.is_file() else "create"
    run(
        [
            str(MICROMAMBA),
            operation,
            "--yes",
            "--prefix",
            str(RUNTIME_DIR),
            "--file",
            str(specification),
        ],
        env=mamba_environment(),
    )
    if not RSCRIPT.is_file():
        raise InstallerError("El runtime no creó el ejecutable Rscript.")


def write_executable(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.new")
    temporary.write_text(content, encoding="utf-8")
    temporary.chmod(0o755)
    temporary.replace(path)


def launcher(entrypoint: Path, *, qt_style: str | None = None) -> str:
    lines = [
        "#!/bin/sh",
        f"export ARII_RSCRIPT='{RSCRIPT}'",
    ]
    if qt_style:
        lines.append(f"export QT_STYLE_OVERRIDE='{qt_style}'")
    lines.append(f"exec '{entrypoint}' \"$@\"")
    return "\n".join(lines) + "\n"


def configure_qt_style(*, classic: bool, system: bool) -> str | None:
    """Persist and return the Qt widget style selected for the GUI."""

    if system:
        QT_STYLE_CONFIG.unlink(missing_ok=True)
        return None
    if classic:
        QT_STYLE_CONFIG.parent.mkdir(parents=True, exist_ok=True)
        QT_STYLE_CONFIG.write_text("Windows\n", encoding="utf-8")
        QT_STYLE_CONFIG.chmod(0o644)
        return "Windows"
    if QT_STYLE_CONFIG.is_file():
        configured = QT_STYLE_CONFIG.read_text(encoding="utf-8").strip()
        if configured in {"Windows", "Fusion"}:
            return configured
    return None


def desktop_entry() -> str:
    return """[Desktop Entry]
Type=Application
Version=1.0
Name=Arii
GenericName=Análisis quimiométrico
Comment=Análisis quimiométrico de datos ómicos
Exec=/usr/local/bin/arii-gui
Icon=arii
Terminal=false
Categories=Science;Education;
Keywords=Arii;quimiometría;ómicos;PCA;PLS-DA;OPLS-DA;mixOmics;
StartupNotify=true
"""


def install_icons(custom_icon: Path | None) -> None:
    if custom_icon is not None:
        PERSISTENT_CUSTOM_ICON.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(custom_icon, PERSISTENT_CUSTOM_ICON)
        PERSISTENT_CUSTOM_ICON.chmod(0o644)

    sizes = (16, 32, 48, 64, 128, 256, 512, 1024)
    for size in sizes:
        source = (
            PERSISTENT_CUSTOM_ICON
            if PERSISTENT_CUSTOM_ICON.is_file()
            else APP_DIR / "assets" / "icons" / f"arii-{size}.png"
        )
        if not source.is_file():
            if custom_icon is not None:
                continue
            raise InstallerError(f"No se encontró el icono de Arii: {source}")
        destination = ICON_ROOT / f"{size}x{size}" / "apps" / "arii.png"
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        destination.chmod(0o644)


def install_desktop_integration(
    custom_icon: Path | None,
    *,
    qt_style: str | None,
) -> None:
    print_step("Instalando comandos, iconos y lanzador")
    if not VENV_CLI.is_file() or not VENV_GUI.is_file():
        raise InstallerError("La instalación Python no creó los ejecutables de Arii.")
    write_executable(GLOBAL_CLI, launcher(VENV_CLI))
    write_executable(GLOBAL_GUI, launcher(VENV_GUI, qt_style=qt_style))
    install_icons(custom_icon)
    DESKTOP_FILE.parent.mkdir(parents=True, exist_ok=True)
    DESKTOP_FILE.write_text(desktop_entry(), encoding="utf-8")
    DESKTOP_FILE.chmod(0o644)


def install_updater() -> None:
    print_step("Instalando el actualizador")
    INSTALLED_INSTALLER.parent.mkdir(parents=True, exist_ok=True)
    repository_installer = APP_DIR / "install_linux.py"
    source = (
        repository_installer
        if repository_installer.is_file()
        else Path(__file__).resolve()
    )
    if source.resolve() != INSTALLED_INSTALLER.resolve():
        shutil.copy2(source, INSTALLED_INSTALLER)
    INSTALLED_INSTALLER.chmod(0o755)
    write_executable(
        UPDATER_COMMAND,
        "#!/bin/sh\n"
        "if [ \"$#\" -eq 0 ]; then\n"
        "    set -- --update\n"
        "fi\n"
        f"exec /usr/bin/python3 '{INSTALLED_INSTALLER}' \"$@\"\n",
    )


def refresh_desktop_caches() -> None:
    desktop_database = shutil.which("update-desktop-database")
    if desktop_database:
        run([desktop_database, str(DESKTOP_FILE.parent)])
    icon_cache = shutil.which("gtk-update-icon-cache")
    if icon_cache:
        run([icon_cache, "--force", str(ICON_ROOT)])


def installed_version(*, quiet: bool = False) -> str:
    return output(
        [
            str(VENV_PYTHON),
            "-c",
            "from importlib.metadata import version; print(version('arii'))",
        ],
        show=not quiet,
    )


def installation_matches_release(expected_tag: str) -> bool:
    """Return True only when the complete installed app matches the tag."""

    required_paths = (
        APP_DIR / ".git",
        VENV_PYTHON,
        VENV_CLI,
        VENV_GUI,
        RSCRIPT,
        GLOBAL_CLI,
        GLOBAL_GUI,
        DESKTOP_FILE,
    )
    if not all(path.exists() for path in required_paths):
        return False

    try:
        installed = installed_version(quiet=True)
        head = output(
            ["git", "-C", str(APP_DIR), "rev-parse", "HEAD"], show=False
        )
        release_commit = output(
            ["git", "-C", str(APP_DIR), "rev-list", "-n", "1", expected_tag],
            show=False,
        )
    except subprocess.CalledProcessError:
        return False

    return installed == expected_tag.removeprefix("v") and head == release_commit


def report_already_current(target_tag: str) -> None:
    print(f"Arii ya está en la última versión estable: {target_tag}")


def verify_xcb_dependencies() -> None:
    plugins = list(
        VENV_DIR.glob(
            "lib/python*/site-packages/PySide6/Qt/plugins/platforms/libqxcb.so"
        )
    )
    if not plugins:
        raise InstallerError("No se encontró el plugin gráfico libqxcb.so de PySide6.")
    result = run(["ldd", str(plugins[0])], capture=True)
    missing = [line.strip() for line in result.stdout.splitlines() if "not found" in line]
    if missing:
        details = "\n".join(f"  {line}" for line in missing)
        raise InstallerError(f"Faltan bibliotecas para Qt/XCB:\n{details}")


def verify_installation(expected_tag: str) -> None:
    print_step("Verificando la instalación")
    version = installed_version()
    expected = expected_tag.removeprefix("v")
    if version != expected:
        raise InstallerError(
            f"Se esperaba Arii {expected}, pero se instaló {version}."
        )
    if not GLOBAL_CLI.is_file() or not GLOBAL_GUI.is_file():
        raise InstallerError("Los comandos globales de Arii no funcionan.")
    if not DESKTOP_FILE.is_file():
        raise InstallerError("No se creó el lanzador de Arii.")
    verify_xcb_dependencies()
    health = output([str(GLOBAL_CLI), "r-health"])
    try:
        report = json.loads(health)
    except json.JSONDecodeError as exc:
        raise InstallerError("El motor R devolvió una respuesta no válida.") from exc
    if not isinstance(report, dict):
        raise InstallerError("La comprobación del motor R no devolvió un informe.")
    if report.get("status") != "ok":
        raise InstallerError("El motor R no informó un estado correcto.")
    packages = report.get("packages")
    if not isinstance(packages, list) or not all(
        isinstance(package, dict) and package.get("installed") is True
        for package in packages
    ):
        raise InstallerError("Faltan paquetes científicos en el runtime privado de R.")
    print(f"\n{APP_NAME} {version} se instaló correctamente.")
    print("Puedes iniciarlo desde el menú de aplicaciones o con: arii-gui")
    print("Para actualizarlo más adelante: sudo arii-update")


def restore_previous_release(previous_commit: str | None) -> None:
    if previous_commit is None:
        return
    print("\nLa instalación falló. Restaurando la revisión anterior...", file=sys.stderr)
    try:
        run(["git", "-C", str(APP_DIR), "switch", "--detach", previous_commit])
        if VENV_PYTHON.is_file():
            run(
                [
                    str(VENV_PYTHON),
                    "-m",
                    "pip",
                    "install",
                    "--force-reinstall",
                    "--editable",
                    str(APP_DIR),
                    "secretstorage>=3.3",
                ]
            )
    except (InstallerError, subprocess.CalledProcessError) as exc:
        print(f"No se pudo completar la restauración: {exc}", file=sys.stderr)


def confirm_uninstall(assume_yes: bool) -> None:
    if assume_yes:
        return
    if not sys.stdin.isatty():
        raise InstallerError("Usa --yes para desinstalar sin confirmación interactiva.")
    answer = input(
        "Esto eliminará Arii y su runtime privado de /opt. "
        "Escribe DESINSTALAR para continuar: "
    )
    if answer != "DESINSTALAR":
        raise InstallerError("Desinstalación cancelada.")


def uninstall(assume_yes: bool) -> None:
    confirm_uninstall(assume_yes)
    print_step("Desinstalando Arii")
    for path in (GLOBAL_CLI, GLOBAL_GUI, UPDATER_COMMAND, DESKTOP_FILE):
        path.unlink(missing_ok=True)
    for size in (16, 32, 48, 64, 128, 256, 512, 1024):
        (ICON_ROOT / f"{size}x{size}" / "apps" / "arii.png").unlink(
            missing_ok=True
        )
    PERSISTENT_CUSTOM_ICON.unlink(missing_ok=True)
    QT_STYLE_CONFIG.unlink(missing_ok=True)
    for directory in (APP_DIR, RUNTIME_DIR, MAMBA_ROOT):
        if directory.exists():
            shutil.rmtree(directory)
    MICROMAMBA.unlink(missing_ok=True)
    INSTALLED_INSTALLER.unlink(missing_ok=True)
    refresh_desktop_caches()
    print("Arii fue desinstalado. Los proyectos y datos de los usuarios no se modificaron.")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Instala, actualiza, repara o desinstala Arii en Debian/Ubuntu x86-64."
        )
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
        "--icon", type=Path, help="utiliza un PNG alternativo como icono global"
    )
    style = parser.add_mutually_exclusive_group()
    style.add_argument(
        "--classic-style",
        action="store_true",
        help="usa controles clásicos de Qt, apropiados para Chicago95",
    )
    style.add_argument(
        "--system-style",
        action="store_true",
        help="elimina la personalización y vuelve al estilo Qt del sistema",
    )
    parser.add_argument(
        "--skip-apt-update",
        action="store_true",
        help="no ejecuta apt-get update (útil al construir una imagen ISO)",
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
        require_supported_system()
        reexec_with_sudo()
        if args.uninstall:
            uninstall(args.yes)
            return 0

        custom_icon = args.icon.expanduser().resolve() if args.icon else None
        if custom_icon is not None and not custom_icon.is_file():
            raise InstallerError(f"No se encontró el icono solicitado: {custom_icon}")
        qt_style = configure_qt_style(
            classic=args.classic_style,
            system=args.system_style,
        )

        if args.release_version and args.requested_version:
            raise InstallerError("Indica la versión una sola vez.")
        requested = args.release_version or args.requested_version

        # A normal update of an existing installation only needs Git in order
        # to discover the latest tag.  Delay apt, pip and micromamba until a
        # different release is actually found.
        existing_update = args.update and (APP_DIR / ".git").is_dir()
        if existing_update:
            try:
                current_version = installed_version(quiet=True)
            except subprocess.CalledProcessError:
                current_version = "desconocida"
            print(f"Versión instalada: {current_version}")
            print("Buscando versiones disponibles...")
            previous_commit = prepare_repository(quiet=True)
        else:
            install_system_dependencies(skip_apt_update=args.skip_apt_update)
            verify_python()
            verify_free_space()
            previous_commit = prepare_repository()

        target_tag = resolve_target_tag(
            requested,
            args.repair,
            quiet=existing_update,
        )

        if args.update and installation_matches_release(target_tag):
            if args.classic_style or args.system_style or custom_icon is not None:
                install_desktop_integration(custom_icon, qt_style=qt_style)
                refresh_desktop_caches()
            report_already_current(target_tag)
            return 0

        if existing_update:
            print(f"Nueva versión estable disponible: {target_tag}")
            install_system_dependencies(skip_apt_update=args.skip_apt_update)
            verify_python()
            verify_free_space()

        try:
            checkout_release(target_tag)
            create_or_update_python_environment(force_reinstall=args.repair)
            install_scientific_runtime(force_reinstall=args.repair)
            install_desktop_integration(custom_icon, qt_style=qt_style)
            install_updater()
            refresh_desktop_caches()
            verify_installation(target_tag)
        except (InstallerError, subprocess.CalledProcessError):
            restore_previous_release(previous_commit)
            raise
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


if __name__ == "__main__":
    raise SystemExit(main())


