from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
import re
import shlex
from typing import Literal, Protocol

from arii.r_bridge import find_rscript


@dataclass(frozen=True)
class RJob:
    """Portable description of one Arii R worker invocation."""

    worker: Path
    specification: Path
    result: Path


@dataclass(frozen=True)
class ProcessCommand:
    program: str
    arguments: tuple[str, ...]


class ExecutionBackend(Protocol):
    """Boundary shared by the local implementation and future schedulers."""

    def command_for(self, job: RJob) -> ProcessCommand: ...


class LocalRBackend:
    name = "local"

    def command_for(self, job: RJob) -> ProcessCommand:
        return ProcessCommand(
            program=str(find_rscript()),
            arguments=(str(job.worker), str(job.specification), str(job.result)),
        )


Scheduler = Literal["slurm", "pbs", "sge"]
Authentication = Literal[
    "arii_managed_key", "ssh_agent", "openssh_config", "pageant"
]


@dataclass(frozen=True)
class ClusterProfile:
    """Non-secret connection and scheduler metadata.

    Passwords, private keys and bearer tokens deliberately have no field here.
    Authentication is delegated to OpenSSH/ssh-agent and, later, the OS keychain.
    """

    profile_id: str
    display_name: str
    host: str
    username: str
    scheduler: Scheduler
    remote_workspace: str
    port: int = 22
    authentication: Authentication = "ssh_agent"
    ssh_config_host: str | None = None
    account: str | None = None
    partition: str | None = None
    qos: str | None = None
    rscript_path: str | None = None

    def __post_init__(self) -> None:
        textual_fields = (
            self.profile_id, self.display_name, self.host, self.username,
            self.remote_workspace, self.ssh_config_host, self.account,
            self.partition, self.qos,
            self.rscript_path,
        )
        if any(
            value is not None and any(ord(character) < 32 for character in value)
            for value in textual_fields
        ):
            raise ValueError("Los campos del perfil no admiten caracteres de control")
        if not self.profile_id.strip() or not self.display_name.strip():
            raise ValueError("El perfil necesita identificador y nombre")
        if not self.host.strip() or not self.username.strip():
            raise ValueError("El perfil necesita host y usuario")
        if not 1 <= self.port <= 65535:
            raise ValueError("El puerto SSH debe estar entre 1 y 65535")
        workspace = PurePosixPath(self.remote_workspace)
        if not workspace.is_absolute() or len(workspace.parts) == 1:
            raise ValueError("El directorio remoto debe ser absoluto y no puede ser la raíz")
        if self.scheduler not in ("slurm", "pbs", "sge"):
            raise ValueError("Planificador no admitido")
        if self.authentication not in (
            "arii_managed_key", "ssh_agent", "openssh_config", "pageant"
        ):
            raise ValueError("Método de autenticación no admitido")
        if self.authentication == "openssh_config" and not self.ssh_config_host:
            raise ValueError("La autenticación por configuración OpenSSH requiere un alias")
        if self.rscript_path:
            rscript = PurePosixPath(self.rscript_path)
            if not rscript.is_absolute():
                raise ValueError("La ruta remota de Rscript debe ser absoluta")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict) -> "ClusterProfile":
        forbidden = {
            "password", "passphrase", "private_key", "private_key_path",
            "token", "secret", "jwt",
        }
        present = forbidden.intersection(payload)
        if present:
            names = ", ".join(sorted(present))
            raise ValueError(f"Un perfil Arii no puede contener secretos: {names}")
        return cls(**payload)


@dataclass(frozen=True)
class SlurmResources:
    cpus: int = 1
    memory_mb: int = 4096
    walltime_minutes: int = 60
    nodes: int = 1

    def __post_init__(self) -> None:
        if not 1 <= self.cpus <= 256:
            raise ValueError("Los CPU solicitados deben estar entre 1 y 256")
        if not 256 <= self.memory_mb <= 1_048_576:
            raise ValueError("La memoria debe estar entre 256 MB y 1 TB")
        if not 1 <= self.walltime_minutes <= 10_080:
            raise ValueError("El tiempo debe estar entre 1 minuto y 7 días")
        if not 1 <= self.nodes <= 64:
            raise ValueError("Los nodos solicitados deben estar entre 1 y 64")


@dataclass(frozen=True)
class SlurmSubmission:
    remote_directory: str
    script_path: str
    result_path: str
    log_path: str
    script: str


class SlurmBackend:
    """Build a closed, auditable sbatch script without executing SSH."""

    name = "slurm"
    _safe_token = re.compile(r"^[A-Za-z0-9_.-]+$")
    _known_workers = {
        "pca_worker.R", "plsda_worker.R",
        "permutation_worker.R", "health.R",
    }

    def __init__(self, profile: ClusterProfile) -> None:
        if profile.scheduler != "slurm":
            raise ValueError("SlurmBackend requiere un perfil Slurm")
        for label, value in (
            ("account", profile.account), ("partition", profile.partition),
            ("qos", profile.qos),
        ):
            if value is not None and not self._safe_token.fullmatch(value):
                raise ValueError(f"El campo Slurm {label} contiene caracteres no permitidos")
        self.profile = profile

    def build_submission(
        self, job_id: str, worker_name: str, resources: SlurmResources
    ) -> SlurmSubmission:
        if not self._safe_token.fullmatch(job_id):
            raise ValueError("Identificador de trabajo no válido")
        if worker_name not in self._known_workers:
            raise ValueError("Worker R no reconocido")
        remote_directory = PurePosixPath(
            self.profile.remote_workspace, "jobs", job_id
        )
        script_path = remote_directory / "submit.sbatch"
        result_path = remote_directory / "result.json"
        log_path = remote_directory / "slurm-%j.log"
        hours, minutes = divmod(resources.walltime_minutes, 60)
        directives = [
            f"#SBATCH --job-name=arii-{job_id[:64]}",
            f"#SBATCH --cpus-per-task={resources.cpus}",
            f"#SBATCH --mem={resources.memory_mb}M",
            f"#SBATCH --time={hours:02d}:{minutes:02d}:00",
            f"#SBATCH --output={log_path}",
        ]
        for option, value in (
            ("account", self.profile.account),
            ("partition", self.profile.partition),
            ("qos", self.profile.qos),
        ):
            if value:
                directives.append(f"#SBATCH --{option}={value}")
        script_lines = [
            "#!/bin/bash",
            *directives,
            "set -eu",
            'cd -- "$SLURM_SUBMIT_DIR"',
        ]
        if worker_name in {"permutation_worker.R", "plsda_worker.R"}:
            script_lines.extend([
                'export ARII_PARALLEL_WORKERS="${SLURM_CPUS_PER_TASK:-1}"',
                "export OMP_NUM_THREADS=1",
                "export OPENBLAS_NUM_THREADS=1",
                "export MKL_NUM_THREADS=1",
            ])
        script_lines.extend([
            shlex.quote(
                self.profile.rscript_path
                or str(
                    PurePosixPath(
                        self.profile.remote_workspace,
                        "runtime", "envs", "arii-r-2026.08", "bin", "Rscript",
                    )
                )
            )
            + " "
            + " ".join(
                shlex.quote(value)
                for value in (worker_name, "job.json", "result.json")
            ),
            "test -s result.json",
            "chmod 600 result.json",
            "",
        ])
        return SlurmSubmission(
            remote_directory=str(remote_directory),
            script_path=str(script_path), result_path=str(result_path),
            log_path=str(log_path), script="\n".join(script_lines),
        )

    def build_permutation_chunk_submission(
        self, job_id: str, resources: SlurmResources,
        task_index: int, task_count: int,
    ) -> SlurmSubmission:
        if not 0 <= task_index < task_count <= 64:
            raise ValueError("Índices de distribución Slurm no válidos")
        if not self._safe_token.fullmatch(job_id):
            raise ValueError("Identificador de trabajo no válido")
        remote_directory = PurePosixPath(
            self.profile.remote_workspace, "jobs", job_id
        )
        log_path = remote_directory / "slurm-%j.log"
        hours, minutes = divmod(resources.walltime_minutes, 60)
        directives = [
            f"#SBATCH --job-name=arii-{job_id[:52]}-{task_index}",
            f"#SBATCH --cpus-per-task={resources.cpus}",
            f"#SBATCH --mem={resources.memory_mb}M",
            f"#SBATCH --time={hours:02d}:{minutes:02d}:00",
            f"#SBATCH --output={log_path}",
        ]
        for option, value in (
            ("account", self.profile.account),
            ("partition", self.profile.partition), ("qos", self.profile.qos),
        ):
            if value:
                directives.append(f"#SBATCH --{option}={value}")
        result_name = f"partial-result-{task_index}.json"
        rscript = shlex.quote(
            self.profile.rscript_path
            or str(PurePosixPath(
                self.profile.remote_workspace, "runtime", "envs",
                "arii-r-2026.08", "bin", "Rscript",
            ))
        )
        script_lines = [
            "#!/bin/bash", *directives, "set -eu", 'cd -- "$SLURM_SUBMIT_DIR"',
            'export ARII_PARALLEL_WORKERS="${SLURM_CPUS_PER_TASK:-1}"',
            f"export ARII_DISTRIBUTED_TASKS={task_count}",
            f"export ARII_DISTRIBUTED_INDEX={task_index}",
            "export OMP_NUM_THREADS=1", "export OPENBLAS_NUM_THREADS=1",
            "export MKL_NUM_THREADS=1",
            f"{rscript} permutation_worker.R job.json {result_name}",
            f"test -s {result_name}", f"chmod 600 {result_name}", "",
        ]
        return SlurmSubmission(
            remote_directory=str(remote_directory),
            script_path=str(remote_directory / f"submit-{task_index}.sbatch"),
            result_path=str(remote_directory / result_name),
            log_path=str(log_path), script="\n".join(script_lines),
        )
