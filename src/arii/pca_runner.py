from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from arii.r_bridge import find_rscript, r_subprocess_environment
from arii.resources import worker_path
from arii.omics_matrix import inspect_omics_matrix


def run_pca(
    dataset_path: str | Path,
    output_path: str | Path,
    n_components: int = 5,
    scaling: str = "pareto",
    validation_enabled: bool = False,
    validation_repeats: int = 20,
    train_fraction: float = 0.8,
    seed: int = 1234,
) -> dict:
    """Run a local mixOmics PCA using the same job contract as the GUI."""
    summary = inspect_omics_matrix(dataset_path)
    output = Path(output_path).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    exchange = Path(tempfile.mkdtemp(prefix="arii-pca-"))
    job_path = exchange / "job.json"
    exchange_result = exchange / "result.json"
    job = {
        "schema_version": "1.0",
        "dataset": {
            "path": summary.path, "delimiter": summary.delimiter,
            "orientation": summary.orientation,
            "representation": summary.representation,
            "modality": summary.modality, "axis_label": summary.axis_label,
        },
        "preprocessing": {"mean_center": True, "scaling": scaling},
        "selected_sample_indices": list(range(summary.samples)),
        "classes": ["Sin asignar"] * summary.samples,
        "n_components": n_components,
        "validation": {
            "enabled": validation_enabled,
            "repeats": validation_repeats,
            "train_fraction": train_fraction,
            "seed": seed,
        },
        "created_at_unix_ns": time.time_ns(),
    }
    job_path.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
    worker = worker_path("pca_worker.R")
    rscript = find_rscript()
    completed = subprocess.run(
        [str(rscript), str(worker), str(job_path), str(exchange_result)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=r_subprocess_environment(rscript),
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "El trabajador PCA falló")
    shutil.copyfile(exchange_result, output)
    return json.loads(exchange_result.read_text(encoding="utf-8"))
