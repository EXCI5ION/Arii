from __future__ import annotations

from dataclasses import dataclass
import ctypes
import os
import shutil
import subprocess


@dataclass(frozen=True)
class SystemResources:
    logical_cpus: int
    total_memory_mb: int | None
    available_memory_mb: int | None
    gpu_names: tuple[str, ...]


def _windows_memory() -> tuple[int | None, int | None]:
    class MemoryStatus(ctypes.Structure):
        _fields_ = [
            ("length", ctypes.c_ulong), ("memory_load", ctypes.c_ulong),
            ("total_physical", ctypes.c_ulonglong),
            ("available_physical", ctypes.c_ulonglong),
            ("total_page_file", ctypes.c_ulonglong),
            ("available_page_file", ctypes.c_ulonglong),
            ("total_virtual", ctypes.c_ulonglong),
            ("available_virtual", ctypes.c_ulonglong),
            ("available_extended_virtual", ctypes.c_ulonglong),
        ]
    status = MemoryStatus()
    status.length = ctypes.sizeof(status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None, None
    divisor = 1024 * 1024
    return status.total_physical // divisor, status.available_physical // divisor


def _posix_memory() -> tuple[int | None, int | None]:
    try:
        page_size = os.sysconf("SC_PAGE_SIZE")
        total = page_size * os.sysconf("SC_PHYS_PAGES") // (1024 * 1024)
        available = page_size * os.sysconf("SC_AVPHYS_PAGES") // (1024 * 1024)
        return int(total), int(available)
    except (AttributeError, OSError, ValueError):
        return None, None


def _nvidia_gpus() -> tuple[str, ...]:
    executable = shutil.which("nvidia-smi")
    if not executable:
        return ()
    completed = subprocess.run(
        [executable, "--query-gpu=name", "--format=csv,noheader"],
        capture_output=True, text=True, timeout=5, check=False,
    )
    if completed.returncode:
        return ()
    return tuple(line.strip() for line in completed.stdout.splitlines() if line.strip())


def detect_system_resources() -> SystemResources:
    total, available = _windows_memory() if os.name == "nt" else _posix_memory()
    return SystemResources(
        logical_cpus=max(1, os.cpu_count() or 1),
        total_memory_mb=total,
        available_memory_mb=available,
        gpu_names=_nvidia_gpus(),
    )


def recommended_workers(
    resources: SystemResources, *, reserved_cpus: int = 3,
    samples: int = 0, variables: int = 0,
) -> int:
    cpu_limit = max(1, resources.logical_cpus - max(2, reserved_cpus))
    if resources.available_memory_mb is None:
        return cpu_limit
    # Each independent R process loads the engine and creates several matrices.
    matrix_mb = samples * variables * 8 / (1024 * 1024)
    estimated_worker_mb = max(384.0, 384.0 + matrix_mb * 12.0)
    usable_mb = max(0.0, resources.available_memory_mb * 0.70 - 1024.0)
    memory_limit = max(1, int(usable_mb // estimated_worker_mb))
    return max(1, min(cpu_limit, memory_limit))
