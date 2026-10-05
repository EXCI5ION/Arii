from __future__ import annotations

import os
import sys
from pathlib import Path


KNOWN_WORKERS = {
    "health.R",
    "pca_worker.R",
    "plsda_worker.R",
    "permutation_worker.R",
}


def bundle_root() -> Path:
    """Root containing PyInstaller data or the source checkout."""

    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        return Path(frozen_root)
    return Path(__file__).resolve().parents[2]


def installation_root() -> Path:
    """Persistent directory beside the executable in a frozen installation."""

    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return bundle_root()


def worker_path(name: str) -> Path:
    if name not in KNOWN_WORKERS:
        raise ValueError(f"worker R desconocido: {name}")
    path = bundle_root() / "r" / name
    if not path.is_file():
        raise FileNotFoundError(f"No se encontró el worker R: {path}")
    return path


def asset_path(name: str) -> Path:
    path = bundle_root() / "assets" / name
    if not path.is_file():
        raise FileNotFoundError(f"No se encontró el recurso de Arii: {path}")
    return path


def configured_rscript_candidates() -> tuple[Path, ...]:
    """Candidate Rscript paths ordered from explicit/bundled to system-wide."""

    candidates: list[Path] = []
    configured = os.environ.get("ARII_RSCRIPT", "").strip()
    if configured:
        candidates.append(Path(configured).expanduser())

    for root in (installation_root(), bundle_root()):
        candidates.extend((
            root / "runtime" / "R" / "bin" / "x64" / "Rscript.exe",
            root / "runtime" / "r" / "bin" / "x64" / "Rscript.exe",
            root / "runtime" / "R" / "bin" / "Rscript.exe",
            root / "runtime" / "r" / "bin" / "Rscript.exe",
            root / "runtime" / "R" / "bin" / "Rscript",
            root / "runtime" / "r" / "bin" / "Rscript",
        ))

    unique: list[Path] = []
    for candidate in candidates:
        if candidate not in unique:
            unique.append(candidate)
    return tuple(unique)
