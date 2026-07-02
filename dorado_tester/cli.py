from __future__ import annotations

import argparse
import sys
from pathlib import Path

REQUIRED_SUBDIRS = ("multiplex", "singleplex")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the Dorado version-comparison test matrix.",
    )
    parser.add_argument("--path_to_dorado", required=True, type=Path)
    parser.add_argument("--path_to_dna_pod5", required=True, type=Path)
    parser.add_argument("--path_to_rna_pod5", type=Path, default=None)
    parser.add_argument("--dna_kit", default="SQK-NBD114-24")
    parser.add_argument("--rna_kit", default="SQK-DRB004.24")
    parser.add_argument("--output_dir", type=Path, default=Path("results"))
    parser.add_argument("--device", default="auto")
    parser.add_argument("--models_directory", type=Path, default=None)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero if any test case failed.",
    )
    parser.add_argument(
        "--ignore_sup",
        action="store_true",
        help="Only run hac-variant test cases (skips sup) to save time.",
    )
    parser.add_argument(
        "--test_fast",
        action="store_true",
        help="Run the fast model variant instead of hac/sup. Overrides --ignore_sup.",
    )
    args = parser.parse_args(argv)
    validate_args(args)
    return args


def _detect_available_libraries(path: Path, label: str) -> set[str]:
    """A missing multiplex/ or singleplex/ subdir just skips that library's
    cases (warned). Only warn loudly (both missing) instead of failing,
    since the run may still be useful with a single library present."""
    present = {d for d in REQUIRED_SUBDIRS if (path / d).is_dir()}
    missing = set(REQUIRED_SUBDIRS) - present
    if missing and present:
        print(
            f"WARNING: {label} is missing {sorted(missing)} under {path}; "
            "skipping those test cases.",
            file=sys.stderr,
        )
    elif not present:
        print(
            f"WARNING: {label} has neither 'multiplex/' nor 'singleplex/' under {path}; "
            "no test cases will run for this input.",
            file=sys.stderr,
        )
    return present


def validate_args(args: argparse.Namespace) -> None:
    if not args.path_to_dorado.is_file():
        raise SystemExit(f"--path_to_dorado does not exist: {args.path_to_dorado}")

    if not args.path_to_dna_pod5.is_dir():
        raise SystemExit(
            f"--path_to_dna_pod5 does not exist or is not a directory: {args.path_to_dna_pod5}"
        )
    args.dna_libraries = _detect_available_libraries(args.path_to_dna_pod5, "--path_to_dna_pod5")

    args.rna_libraries: set[str] = set()
    if args.path_to_rna_pod5 is not None:
        if not args.path_to_rna_pod5.is_dir():
            raise SystemExit(
                f"--path_to_rna_pod5 does not exist or is not a directory: {args.path_to_rna_pod5}"
            )
        args.rna_libraries = _detect_available_libraries(args.path_to_rna_pod5, "--path_to_rna_pod5")
