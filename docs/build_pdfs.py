"""Compila los dos documentos LaTeX canónicos de Arii.

El flujo editorial oficial también puede realizarse en Overleaf cargando el
repositorio y compilando ``main.tex`` o ``scientific_documentation.tex``.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
OUTPUT = DOCS / "pdf"
VERSION = "1.1.0"
DOCUMENTS = {
    "main.tex": f"Arii-manual-de-usuario-versión{VERSION}",
    "scientific_documentation.tex": f"Arii-documentacion-cientifica-versión{VERSION}",
}


def find_compiler() -> tuple[str, int]:
    """Devuelve el ejecutable LaTeX y la cantidad de ejecuciones necesarias."""
    latexmk = shutil.which("latexmk")
    if latexmk:
        return latexmk, 1
    pdflatex = shutil.which("pdflatex")
    if pdflatex:
        return pdflatex, 2
    raise SystemExit(
        "No se encontró latexmk ni pdflatex. Abra el repositorio en Overleaf "
        "y compile docs/main.tex y docs/scientific_documentation.tex."
    )


def build(source_name: str, job_name: str, executable: str, runs: int) -> Path:
    """Compila una fuente y mueve el PDF terminado a ``docs/pdf``."""
    OUTPUT.mkdir(parents=True, exist_ok=True)
    if Path(executable).stem.lower() == "latexmk":
        command = [
            executable,
            "-pdf",
            "-interaction=nonstopmode",
            "-halt-on-error",
            f"-jobname={job_name}",
            source_name,
        ]
    else:
        command = [
            executable,
            "-interaction=nonstopmode",
            "-halt-on-error",
            f"-jobname={job_name}",
            source_name,
        ]
    for _ in range(runs):
        subprocess.run(command, cwd=DOCS, check=True)
    generated = DOCS / f"{job_name}.pdf"
    target = OUTPUT / generated.name
    generated.replace(target)
    return target


if __name__ == "__main__":
    engine, passes = find_compiler()
    for source, job in DOCUMENTS.items():
        print(build(source, job, engine, passes))
