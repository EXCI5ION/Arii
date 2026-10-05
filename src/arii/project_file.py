from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path


PROJECT_MEMBER = "project.json"
RESULT_MEMBER = "results/model.json"
LEGACY_PCA_RESULT_MEMBER = "results/pca.json"


def fingerprint_file(path: str | Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def save_project(path: str | Path, payload: dict, model_result: dict | None = None) -> Path:
    destination = Path(path)
    if destination.suffix.lower() != ".arii":
        destination = destination.with_suffix(".arii")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".arii.tmp")
    manifest = dict(payload)
    manifest["result_members"] = [RESULT_MEMBER] if model_result is not None else []
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            PROJECT_MEMBER,
            json.dumps(manifest, ensure_ascii=False, indent=2),
        )
        if model_result is not None:
            archive.writestr(
                RESULT_MEMBER,
                json.dumps(model_result, ensure_ascii=False, separators=(",", ":")),
            )
    temporary.replace(destination)
    return destination


def load_project(path: str | Path) -> tuple[dict, dict | None]:
    source = Path(path)
    with zipfile.ZipFile(source, "r") as archive:
        if PROJECT_MEMBER not in archive.namelist():
            raise ValueError("El archivo no contiene project.json")
        manifest = json.loads(archive.read(PROJECT_MEMBER).decode("utf-8"))
        if manifest.get("schema_version") != "1.0":
            raise ValueError(f"Versión de proyecto no compatible: {manifest.get('schema_version')}")
        result = None
        result_member = next(
            (name for name in (RESULT_MEMBER, LEGACY_PCA_RESULT_MEMBER) if name in archive.namelist()),
            None,
        )
        if result_member:
            result = json.loads(archive.read(result_member).decode("utf-8"))
    return manifest, result
