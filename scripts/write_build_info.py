from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from check_release_version import declared_versions


def _git(project_root: Path, *arguments: str, required: bool = True) -> str | None:
    completed = subprocess.run(
        [
            "git", "-c", f"safe.directory={project_root}", "-C", str(project_root),
            *arguments,
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if completed.returncode == 0:
        return completed.stdout.strip()
    if required:
        raise RuntimeError(completed.stderr.strip() or "Git no devolvió información")
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--release", action="store_true")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    versions = declared_versions(project_root)
    unique_versions = set(versions.values())
    if len(unique_versions) != 1:
        raise RuntimeError("Las versiones declaradas de Arii no coinciden")
    version = unique_versions.pop()
    commit = _git(project_root, "rev-parse", "HEAD")
    status = _git(project_root, "status", "--porcelain") or ""
    dirty = bool(status)
    tag = _git(project_root, "describe", "--tags", "--exact-match", required=False)
    expected_tag = f"v{version}"

    if args.release and dirty:
        raise RuntimeError("Un release no puede construirse con cambios sin confirmar")
    if args.release and tag != expected_tag:
        raise RuntimeError(
            f"HEAD debe corresponder exactamente al tag {expected_tag}; detectado: "
            f"{tag or 'ninguno'}"
        )

    payload = {
        "schema_version": "1.0",
        "application": "Arii",
        "version": version,
        "git_commit": commit,
        "git_tag": tag,
        "source_tree_clean": not dirty,
        "release_build": bool(args.release),
        "built_at_utc": datetime.now(timezone.utc).isoformat(),
        "python_version": sys.version.split()[0],
    }
    output = args.output
    if not output.is_absolute():
        output = project_root / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Información de construcción: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
