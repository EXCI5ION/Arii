from __future__ import annotations

"""Small, non-interactive OpenSSH/PuTTY Slurm transport used by Arii."""

import json
import math
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile
import time

import numpy as np

from arii.execution import ClusterProfile, SlurmBackend, SlurmResources
from arii.residual_tests import build_residual_tests
from arii.ssh_access import connect_managed


SAFE_JOB_ID = re.compile(r"^[A-Za-z0-9_.-]+$")
KNOWN_WORKERS = {
    "pca_worker.R", "plsda_worker.R", "permutation_worker.R", "health.R",
}


def launcher_command(
    request_path: Path, *, executable: str | None = None,
    frozen: bool | None = None,
) -> tuple[str, list[str]]:
    """Return the remote-runner command for source and frozen applications.

    In a PyInstaller build ``sys.executable`` is Arii.exe rather than Python.
    Passing ``-m arii.remote_runner`` to it would therefore start a second GUI.
    The frozen executable uses an internal dispatch flag handled by gui.main.
    """
    program = executable or sys.executable
    is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    arguments = (
        ["--arii-remote-runner", str(request_path)]
        if is_frozen else
        ["-m", "arii.remote_runner", str(request_path)]
    )
    return program, arguments


def _status(message: str) -> None:
    print(f"ARII_STATUS:{message}", flush=True)


def _putty_program(name: str) -> str:
    discovered = shutil.which(name)
    if discovered:
        return discovered
    candidate = Path("C:/Program Files/PuTTY") / f"{name}.exe"
    if candidate.is_file():
        return str(candidate)
    raise RuntimeError(f"No se encontró {name}. Instale PuTTY o agréguelo al PATH.")


def _openssh_program(name: str) -> str:
    discovered = shutil.which(name)
    if discovered:
        return discovered
    candidate = Path("C:/Windows/System32/OpenSSH") / f"{name}.exe"
    if candidate.is_file():
        return str(candidate)
    raise RuntimeError(
        f"No se encontró OpenSSH ({name}). Active 'Cliente OpenSSH' en Windows."
    )


def _run(arguments: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        arguments, text=True, encoding="utf-8", errors="replace",
        capture_output=True, check=False,
    )
    if check and completed.returncode:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(detail or f"El comando terminó con código {completed.returncode}")
    return completed


class PuttySlurmRunner:
    def __init__(self, request: dict) -> None:
        self.profile = ClusterProfile.from_dict(request["profile"])
        self.resources = SlurmResources(**request["resources"])
        self.worker = Path(request["worker_path"]).resolve()
        self.job = Path(request["job_path"]).resolve()
        self.dataset = Path(request["dataset_path"]).resolve()
        self.result = Path(request["result_path"]).resolve()
        self.job_id = str(request["remote_job_id"])
        if not SAFE_JOB_ID.fullmatch(self.job_id):
            raise ValueError("Identificador remoto no válido")
        if self.worker.name not in KNOWN_WORKERS:
            raise ValueError("Worker R remoto no admitido")
        for path, label in (
            (self.worker, "worker"), (self.job, "especificación"),
            (self.dataset, "dataset"),
        ):
            if not path.is_file():
                raise FileNotFoundError(f"No se encontró el {label}: {path}")
        self.use_managed_ssh = self.profile.authentication == "arii_managed_key"
        self.use_putty = self.profile.authentication == "pageant"
        self.paramiko_client = None
        if self.use_managed_ssh:
            self.paramiko_client = connect_managed(self.profile)
            self.target = self.profile.host
        elif self.use_putty:
            self.ssh_program = _putty_program("plink")
            self.scp_program = _putty_program("pscp")
            self.target = self.profile.host
        else:
            self.ssh_program = _openssh_program("ssh")
            self.scp_program = _openssh_program("scp")
            self.target = (
                self.profile.ssh_config_host
                if self.profile.authentication == "openssh_config"
                and self.profile.ssh_config_host
                else f"{self.profile.username}@{self.profile.host}"
            )

    @property
    def remote_directory(self) -> str:
        return str(PurePosixPath(
            self.profile.remote_workspace, "jobs", self.job_id
        ))

    def _plink(self, command: str, *, check: bool = True) -> subprocess.CompletedProcess[str]:
        if self.use_managed_ssh:
            assert self.paramiko_client is not None
            _, stdout, stderr = self.paramiko_client.exec_command(command)
            exit_code = stdout.channel.recv_exit_status()
            completed = subprocess.CompletedProcess(
                args=["paramiko", command],
                returncode=exit_code,
                stdout=stdout.read().decode("utf-8", errors="replace"),
                stderr=stderr.read().decode("utf-8", errors="replace"),
            )
            if check and exit_code:
                detail = completed.stderr.strip() or completed.stdout.strip()
                raise RuntimeError(detail or f"El comando terminó con código {exit_code}")
            return completed
        if self.use_putty:
            arguments = [
                self.ssh_program, "-batch", "-ssh", "-P", str(self.profile.port),
                "-l", self.profile.username, self.profile.host, command,
            ]
        else:
            arguments = [self.ssh_program, "-o", "BatchMode=yes"]
            if self.profile.authentication != "openssh_config":
                arguments.extend(["-p", str(self.profile.port)])
            arguments.extend([self.target, command])
        return _run(arguments, check=check)

    def _upload(self, source: Path, remote_name: str) -> None:
        if self.use_managed_ssh:
            assert self.paramiko_client is not None
            with self.paramiko_client.open_sftp() as sftp:
                sftp.put(
                    str(source), f"{self.remote_directory}/{remote_name}", confirm=True
                )
            return
        if self.use_putty:
            arguments = [
                self.scp_program, "-batch", "-P", str(self.profile.port), "-l",
                self.profile.username, str(source),
                f"{self.target}:{self.remote_directory}/{remote_name}",
            ]
        else:
            arguments = [self.scp_program, "-o", "BatchMode=yes"]
            if self.profile.authentication != "openssh_config":
                arguments.extend(["-P", str(self.profile.port)])
            arguments.extend([
                str(source), f"{self.target}:{self.remote_directory}/{remote_name}"
            ])
        _run(arguments)

    def _download(self, remote_name: str, destination: Path, *, check: bool = True) -> bool:
        if self.use_managed_ssh:
            assert self.paramiko_client is not None
            try:
                with self.paramiko_client.open_sftp() as sftp:
                    sftp.get(
                        f"{self.remote_directory}/{remote_name}", str(destination)
                    )
                return True
            except OSError as exc:
                if check:
                    raise RuntimeError(f"No se pudo descargar {remote_name}: {exc}") from exc
                return False
        if self.use_putty:
            arguments = [
                self.scp_program, "-batch", "-P", str(self.profile.port), "-l",
                self.profile.username,
                f"{self.target}:{self.remote_directory}/{remote_name}",
                str(destination),
            ]
        else:
            arguments = [self.scp_program, "-o", "BatchMode=yes"]
            if self.profile.authentication != "openssh_config":
                arguments.extend(["-P", str(self.profile.port)])
            arguments.extend([
                f"{self.target}:{self.remote_directory}/{remote_name}", str(destination)
            ])
        completed = _run(arguments, check=False)
        if completed.returncode and check:
            detail = completed.stderr.strip() or completed.stdout.strip()
            raise RuntimeError(detail or f"No se pudo descargar {remote_name}")
        return completed.returncode == 0

    def run(self) -> None:
        import shlex

        distributed = self.worker.name == "permutation_worker.R" and self.resources.nodes > 1
        backend = SlurmBackend(self.profile)
        submissions = (
            [backend.build_permutation_chunk_submission(
                self.job_id, self.resources, index, self.resources.nodes
            ) for index in range(self.resources.nodes)]
            if distributed else
            [backend.build_submission(self.job_id, self.worker.name, self.resources)]
        )
        remote_q = shlex.quote(self.remote_directory)
        _status("Comprobando la conexión y preparando la carpeta remota…")
        self._plink(f"install -d -m 700 -- {remote_q}")
        with tempfile.TemporaryDirectory(prefix="arii-remote-") as directory:
            staging = Path(directory)
            job_payload = json.loads(self.job.read_text(encoding="utf-8"))
            job_payload.setdefault("dataset", {})["path"] = "dataset.csv"
            staged_job = staging / "job.json"
            staged_job.write_text(
                json.dumps(job_payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            _status("Enviando dataset y especificación al clúster…")
            self._upload(self.dataset, "dataset.csv")
            self._upload(staged_job, "job.json")
            self._upload(self.worker, self.worker.name)
            for submission in submissions:
                script_name = PurePosixPath(submission.script_path).name
                staged_script = staging / script_name
                staged_script.write_text(
                    submission.script, encoding="utf-8", newline="\n"
                )
                self._upload(staged_script, script_name)

        _status("Enviando el trabajo a Slurm…")
        slurm_ids: list[str] = []
        try:
            for submission in submissions:
                script_name = PurePosixPath(submission.script_path).name
                submitted = self._plink(
                    f"cd -- {remote_q} && sbatch --parsable {script_name}"
                )
                match = re.search(
                    r"(?m)^(\d+)(?:;[^\s]+)?$", submitted.stdout.strip()
                )
                if not match:
                    raise RuntimeError(
                        f"Slurm no devolvió un JOBID válido: {submitted.stdout.strip()}"
                    )
                slurm_ids.append(match.group(1))
        except Exception:
            if slurm_ids:
                self._plink("scancel " + " ".join(slurm_ids), check=False)
            raise
        slurm_id = slurm_ids[0]
        effective_nodes = self.resources.nodes if distributed else 1
        _status(
            f"Trabajo(s) Slurm {', '.join(slurm_ids)} enviado(s) con "
            f"hasta {effective_nodes} nodo(s) × {self.resources.cpus} CPU; "
            "esperando recursos…"
        )
        last_state = ""
        while True:
            polled = self._plink(
                f"squeue -h -j {','.join(slurm_ids)} -o '%i|%T|%M|%R'", check=False
            )
            lines = polled.stdout.strip()
            if not lines:
                break
            if lines != last_state:
                compact = "; ".join(lines.splitlines())
                _status(f"Slurm: {compact}")
                last_state = lines
            time.sleep(2)

        _status("El cálculo terminó; recuperando el resultado…")
        self.result.parent.mkdir(parents=True, exist_ok=True)
        if distributed:
            partial_paths: list[Path] = []
            try:
                for index in range(self.resources.nodes):
                    partial = self.result.with_name(
                        f"{self.result.stem}.partial-{index}.json"
                    )
                    self._download(f"partial-result-{index}.json", partial)
                    partial_paths.append(partial)
                merged = merge_permutation_results([
                    json.loads(path.read_text(encoding="utf-8"))
                    for path in partial_paths
                ])
                self.result.write_text(
                    json.dumps(merged, ensure_ascii=False, separators=(",", ":")),
                    encoding="utf-8",
                )
                _status(
                    f"Resultado distribuido de {', '.join(slurm_ids)} reunido "
                    f"desde {self.resources.nodes} nodos"
                )
                return
            finally:
                for partial in partial_paths:
                    partial.unlink(missing_ok=True)
        for attempt in range(3):
            if self._download("result.json", self.result, check=False):
                _status(f"Resultado del trabajo {slurm_id} descargado")
                return
            time.sleep(1 + attempt)
        log_path = self.result.with_suffix(".slurm.log")
        self._download(f"slurm-{slurm_id}.log", log_path, check=False)
        if log_path.is_file():
            tail = log_path.read_text(encoding="utf-8", errors="replace")[-6000:]
            raise RuntimeError(f"El trabajo Slurm {slurm_id} no produjo result.json.\n{tail}")
        raise RuntimeError(f"El trabajo Slurm {slurm_id} no produjo result.json ni un log recuperable")


def _as_list(value) -> list:
    return value if isinstance(value, list) else [value]


def _observed_results_close(left: dict, right: dict) -> bool:
    if set(left) != set(right):
        return False
    for name in left:
        left_value, right_value = left[name], right[name]
        if left_value is None or right_value is None:
            if left_value is not right_value:
                return False
        elif not math.isclose(
            float(left_value), float(right_value), rel_tol=1e-12, abs_tol=1e-12
        ):
            return False
    return True


def merge_permutation_results(partials: list[dict]) -> dict:
    if not partials:
        raise ValueError("No hay resultados parciales para reunir")
    total = int(partials[0]["permutations"])
    observed = partials[0]["observed"]
    records: list[tuple[int, dict, float, float, float, dict]] = []
    metric_names = ("r2y", "q2y", "ber", "auc_macro")
    residual_template = partials[0].get("residual_comparison")
    residual_modes = ("calibration", "cross_validated")
    residual_scopes = (
        ["global", *residual_template["class_levels"]]
        if residual_template else []
    )
    for partial in partials:
        contract_fields = (
            "method", "seed", "selection_policy", "exchangeability_unit",
            "validation", "requested_analysis_mode",
        )
        same_contract = all(
            partial.get(field) == partials[0].get(field) for field in contract_fields
        )
        if int(partial["permutations"]) != total or not same_contract:
            raise ValueError("Los resultados parciales no pertenecen al mismo test")
        if not _observed_results_close(partial["observed"], observed):
            raise ValueError(
                "Los resultados observados de los nodos difieren más que la "
                "tolerancia numérica permitida"
            )
        indices = [int(value) for value in _as_list(partial["permutation_indices"])]
        correlations = [float(value) for value in _as_list(partial["correlation_to_original"])]
        rejected = [float(value) for value in _as_list(partial["null_rejected_fraction"])]
        seconds = [float(value) for value in _as_list(partial["timing"]["permutation_seconds"])]
        metrics = {
            name: [float(value) for value in _as_list(partial["null"][name])]
            for name in metric_names
        }
        residual = partial.get("residual_comparison")
        if (residual is None) != (residual_template is None):
            raise ValueError("Los resultados parciales no contienen el mismo diagnóstico residual")
        if residual:
            for mode in residual_modes:
                if not np.allclose(
                    np.asarray(residual["observed_error_by_sample"][mode], dtype=float),
                    np.asarray(
                        residual_template["observed_error_by_sample"][mode], dtype=float
                    ),
                    rtol=1e-12, atol=1e-12, equal_nan=True,
                ):
                    raise ValueError(
                        "Los residuos observados de los nodos difieren más que la "
                        "tolerancia numérica permitida"
                    )
        residual_null = {
            mode: {
                scope: [float(value) for value in _as_list(
                    residual["null_standardized_ssq"][mode][scope]
                )]
                for scope in residual_scopes
            }
            for mode in residual_modes
        } if residual else {}
        lengths = {len(indices), len(correlations), len(rejected), len(seconds)}
        lengths.update(len(values) for values in metrics.values())
        for mode in residual_null.values():
            lengths.update(len(values) for values in mode.values())
        if lengths != {len(indices)}:
            raise ValueError("Un resultado parcial tiene longitudes incompatibles")
        for offset, permutation_index in enumerate(indices):
            records.append((
                permutation_index,
                {name: metrics[name][offset] for name in metric_names},
                correlations[offset], rejected[offset], seconds[offset],
                {
                    mode: {
                        scope: residual_null[mode][scope][offset]
                        for scope in residual_scopes
                    }
                    for mode in residual_modes
                },
            ))
    records.sort(key=lambda value: value[0])
    if [record[0] for record in records] != list(range(1, total + 1)):
        raise ValueError("Faltan permutaciones o hay índices duplicados")
    null = {
        name: [record[1][name] for record in records] for name in metric_names
    }
    empirical = {
        "r2y": (1 + sum(value >= float(observed["r2y"]) for value in null["r2y"])) / (total + 1),
        "q2y": (1 + sum(value >= float(observed["q2y"]) for value in null["q2y"])) / (total + 1),
        "ber": (1 + sum(value <= float(observed["ber"]) for value in null["ber"])) / (total + 1),
        "auc_macro": (
            1 + sum(value >= float(observed["auc_macro"]) for value in null["auc_macro"])
        ) / (total + 1),
    }
    merged = dict(partials[0])
    merged["permutation_indices"] = list(range(1, total + 1))
    merged["null"] = null
    merged["correlation_to_original"] = [record[2] for record in records]
    merged["null_rejected_fraction"] = [record[3] for record in records]
    merged["empirical_p"] = empirical
    if residual_template:
        residual_merged = dict(residual_template)
        residual_merged["null_standardized_ssq"] = {
            mode: {
                scope: [record[5][mode][scope] for record in records]
                for scope in residual_scopes
            }
            for mode in residual_modes
        }
        observed_errors = residual_template["observed_error_by_sample"]
        null_error_sum = {
            mode: np.sum(
                [
                    np.asarray(partial["residual_comparison"]["null_error_sum_by_sample"][mode], dtype=float)
                    for partial in partials
                ],
                axis=0,
            ).tolist()
            for mode in residual_modes
        }
        residual_merged["null_error_sum_by_sample"] = null_error_sum
        residual_merged["evaluated_permutations"] = total
        residual_merged["tests"] = build_residual_tests(
            observed_errors,
            null_error_sum,
            total,
            list(residual_template["class_levels"]),
            seed=int(merged.get("seed", 4321)) + 700001,
        )
        merged["residual_comparison"] = residual_merged
    all_seconds = [record[4] for record in records]
    merged["timing"] = {
        "total_seconds": max(float(partial["timing"]["total_seconds"]) for partial in partials),
        "observed_seconds": max(float(partial["timing"]["observed_seconds"]) for partial in partials),
        "permutation_seconds": all_seconds,
        "mean_permutation_seconds": sum(all_seconds) / len(all_seconds),
        "parallel_workers": sum(int(partial["timing"]["parallel_workers"]) for partial in partials),
        "distributed_tasks": len(partials),
    }
    return merged


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    arguments = sys.argv[1:] if argv is None else argv
    if len(arguments) != 1:
        print("Uso: python -m arii.remote_runner <request.json>", file=sys.stderr)
        return 2
    try:
        request = json.loads(Path(arguments[0]).read_text(encoding="utf-8"))
        PuttySlurmRunner(request).run()
        return 0
    except Exception as exc:
        print(str(exc), file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
