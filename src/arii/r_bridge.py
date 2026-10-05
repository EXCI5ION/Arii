from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from arii.resources import configured_rscript_candidates, installation_root, worker_path


WINDOWS_POSIX_LOCALE_VARIABLES = (
    "LC_ALL", "LC_COLLATE", "LC_CTYPE", "LC_MONETARY",
    "LC_NUMERIC", "LC_TIME", "LANG",
)


def find_rscript() -> Path:
    for candidate in configured_rscript_candidates():
        if candidate.is_file():
            return candidate

    in_path = shutil.which("Rscript")
    if in_path:
        return Path(in_path)

    r_root = Path("C:/Program Files/R")
    candidates = sorted(r_root.glob("R-*/bin/Rscript.exe"), reverse=True)
    if candidates:
        return candidates[0]
    configured = os.environ.get("ARII_RSCRIPT")
    detail = f" La ruta configurada no existe: {configured}." if configured else ""
    raise FileNotFoundError(
        "No se encontró Rscript. Instale el runtime de Arii o configure "
        f"ARII_RSCRIPT.{detail}"
    )


def r_subprocess_environment(
    rscript: str | Path | None = None,
    *,
    platform_name: str | None = None,
) -> dict[str, str]:
    """Build a deterministic environment for local R, including portable R."""

    environment = os.environ.copy()
    effective_platform = os.name if platform_name is None else platform_name
    if effective_platform == "nt":
        for name in WINDOWS_POSIX_LOCALE_VARIABLES:
            environment.pop(name, None)

    executable = Path(rscript) if rscript is not None else find_rscript()
    runtime_root = installation_root() / "runtime"
    try:
        executable.resolve().relative_to(runtime_root.resolve())
    except ValueError:
        return environment

    executable_directory = executable.resolve().parent
    if (
        executable_directory.name.lower() in {"x64", "i386"}
        and executable_directory.parent.name.lower() == "bin"
    ):
        r_home = executable_directory.parent.parent
    else:
        r_home = executable_directory.parent
    library = r_home / "library"
    environment.update({
        "R_HOME": str(r_home),
        "R_LIBS_SITE": str(library),
        "R_LIBS_USER": str(library),
    })
    return environment


def r_health(script: str | Path | None = None) -> dict:
    rscript = find_rscript()
    worker = Path(script) if script else worker_path("health.R")
    completed = subprocess.run(
        [str(rscript), str(worker)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=r_subprocess_environment(rscript),
    )
    return json.loads(completed.stdout)
