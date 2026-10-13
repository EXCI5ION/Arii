from __future__ import annotations

import argparse
import re
import sys
import tomllib
from pathlib import Path


def declared_versions(project_root: Path) -> dict[str, str]:
    pyproject = tomllib.loads((project_root / "pyproject.toml").read_text("utf-8"))
    versions = {"pyproject.toml": pyproject["project"]["version"]}

    init_text = (project_root / "src" / "arii" / "__init__.py").read_text("utf-8")
    versions["src/arii/__init__.py"] = re.search(
        r'^__version__\s*=\s*"([^"]+)"', init_text, re.MULTILINE
    ).group(1)

    iss_text = (project_root / "packaging" / "windows" / "arii.iss").read_text(
        "utf-8"
    )
    versions["packaging/windows/arii.iss"] = re.search(
        r'^#define MyAppVersion\s+"([^"]+)"', iss_text, re.MULTILINE
    ).group(1)

    info_text = (
        project_root / "packaging" / "windows" / "version_info.txt"
    ).read_text("utf-8")
    versions["packaging/windows/version_info.txt"] = re.search(
        r"StringStruct\('ProductVersion', '([^']+)'\)", info_text
    ).group(1)

    cluster_text = (project_root / "scripts" / "stage_cluster_release.ps1").read_text(
        "utf-8"
    )
    versions["scripts/stage_cluster_release.ps1"] = re.search(
        r'\[string\]\$Version\s*=\s*"([^"]+)"', cluster_text
    ).group(1)
    for relative in (
        "cluster/install-server.sh",
        "cluster/runtime/build-runtime.sbatch",
        "cluster/runtime/validate-runtime.sbatch",
        "cluster/runtime/smoke-runtime.sbatch",
        "cluster/runtime/audit-runtime.sbatch",
    ):
        text = (project_root / relative).read_text("utf-8")
        versions[relative] = re.search(
            r'VERSION="\$\{ARII_VERSION:-([^}]+)\}"', text
        ).group(1)
    installer_test = (project_root / "tests" / "test_install_server.sh").read_text(
        "utf-8"
    )
    versions["tests/test_install_server.sh"] = re.search(
        r'^VERSION="([^"]+)"', installer_test, re.MULTILINE
    ).group(1)
    return versions


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected")
    args = parser.parse_args()
    project_root = Path(__file__).resolve().parents[1]
    versions = declared_versions(project_root)
    unique = set(versions.values())
    if len(unique) != 1:
        for source, version in versions.items():
            print(f"{source}: {version}", file=sys.stderr)
        print("ERROR: las versiones declaradas no coinciden", file=sys.stderr)
        return 1
    version = unique.pop()
    if args.expected is not None and version != args.expected:
        print(
            f"ERROR: se solicitó {args.expected}, pero el código declara {version}",
            file=sys.stderr,
        )
        return 1
    print(f"Versión coherente: {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
