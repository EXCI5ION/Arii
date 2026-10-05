from __future__ import annotations

import argparse
import json
import sys

from arii.domain import AnalysisSpec
from arii.pca_runner import run_pca
from arii.r_bridge import r_health
from arii.omics_matrix import inspect_omics_matrix


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="arii")
    commands = parser.add_subparsers(dest="command", required=True)

    inspect_cmd = commands.add_parser("inspect", help="Inspecciona una matriz ómica")
    inspect_cmd.add_argument("path")
    inspect_cmd.add_argument("--delimiter", default=None)

    spec_cmd = commands.add_parser("new-spec", help="Genera una especificación inicial")
    spec_cmd.add_argument("path")

    commands.add_parser("r-health", help="Comprueba R y los motores científicos")
    pca_cmd = commands.add_parser("pca", help="Ejecuta un PCA local con mixOmics")
    pca_cmd.add_argument("path")
    pca_cmd.add_argument("--output", required=True)
    pca_cmd.add_argument("--ncomp", type=int, default=5)
    pca_cmd.add_argument("--validate", action="store_true")
    pca_cmd.add_argument("--repeats", type=int, default=20)
    pca_cmd.add_argument("--train-fraction", type=float, default=0.8)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "inspect":
            output = inspect_omics_matrix(args.path, args.delimiter).to_dict()
        elif args.command == "new-spec":
            output = AnalysisSpec.for_spectral_csv(args.path).to_dict()
        elif args.command == "pca":
            result = run_pca(
                args.path,
                args.output,
                n_components=args.ncomp,
                validation_enabled=args.validate,
                validation_repeats=args.repeats,
                train_fraction=args.train_fraction,
            )
            output = {
                "result_path": args.output,
                "engine": result["engine"],
                "dimensions": result["dimensions"],
                "explained_variance": result["explained_variance"],
                "cumulative_variance": result["cumulative_variance"],
            }
        else:
            output = r_health()
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
