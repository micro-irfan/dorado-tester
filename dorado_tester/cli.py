from __future__ import annotations

import argparse
from pathlib import Path

from .log import get_logger

REQUIRED_SUBDIRS = ("multiplex", "singleplex")
IGNORABLE_VARIANTS = {"hac", "sup"}
logger = get_logger()


def _split_comma_list(values: list[str] | None) -> list[str]:
    if not values:
        return []
    return [name.strip() for token in values for name in token.split(",") if name.strip()]


def _parse_mod_groups(values: list[str] | None) -> list[list[str]]:
    """'m6A,pseU;m6A;pseU' -> [['m6A','pseU'], ['m6A'], ['pseU']]: each
    ';'-separated group is tested as its own parallel case, combining
    whichever mods are ','-joined within that group."""
    if not values:
        return []
    groups: list[list[str]] = []
    for token in values:
        for group in token.split(";"):
            mods = [m.strip() for m in group.split(",") if m.strip()]
            if mods:
                groups.append(mods)
    return groups


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the Dorado version-comparison test matrix.",
    )
    parser.add_argument("--path_to_dorado", required=True, type=Path)
    parser.add_argument("--path_to_dna_pod5", type=Path, default=None)
    parser.add_argument("--path_to_rna_pod5", type=Path, default=None)
    parser.add_argument("--dna_kit", default="SQK-NBD114-24")
    parser.add_argument("--rna_kit", default="SQK-DRB004-24")
    parser.add_argument("--output_dir", type=Path, default=Path("results"))
    parser.add_argument("--device", default="auto")
    parser.add_argument("--models_directory", type=Path, default=None)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero if any test case failed.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="If results/<version>/ already exists, delete and replace it instead of "
             "writing to a fresh results/<version>_1/, _2/, ... Off by default so one "
             "run's manifest.json/logs can never overwrite another's.",
    )
    parser.add_argument(
        "--ignore",
        nargs="+",
        default=None,
        metavar="VARIANT",
        help="Skip these basecalling model variant(s): 'hac' and/or 'sup' "
             "(space- and/or comma-separated, e.g. '--ignore sup,hac'). Ignoring "
             "both runs the 'fast' variant everywhere instead.",
    )
    parser.add_argument(
        "--only",
        nargs="+",
        default=None,
        metavar="TEST_NAME",
        help="Only run these test case(s) by name (see --list_tests for available names). "
             "Accepts space- and/or comma-separated names, e.g. "
             "'--only a,b c' or '--only a b c'. The rest of the matrix is skipped, but "
             "logs, manifest.json, and the stats CSV are still written as usual.",
    )
    parser.add_argument(
        "--add_tests",
        nargs="+",
        default=None,
        metavar="TEST_NAME",
        help="Also run these test case(s) by name, on top of the default run, even if they're "
             "normally excluded from it (e.g. dna_singleplex_no_trim, "
             "dna_multiplex_barcode_kit_mods_hac). Accepts space- and/or comma-separated names, "
             "same as --only. Ignored if --only is given.",
    )
    parser.add_argument(
        "--rna_mod",
        nargs="+",
        default=None,
        metavar="MODS",
        help="Override the RNA mods used for *_mods_hac/*_mods_sup, testing multiple "
             "combinations as separate parallel cases: ';'-separated groups, each a "
             "comma-separated set of mods to combine in that case, e.g. "
             "'--rna_mod m6A,pseU;m6A;pseU' runs three cases (m6A+pseU combined, m6A "
             "alone, pseU alone) instead of the one config/mods.yaml-derived case.",
    )
    parser.add_argument(
        "--dna_mod",
        nargs="+",
        default=None,
        metavar="MODS",
        help="Same as --rna_mod, but for the DNA *_mods_hac/*_mods_sup cases, e.g. "
             "'--dna_mod 4mC_5mC,6mA;5mC_5hmC,6mA' runs both as separate parallel cases "
             "alongside the config/mods.yaml default (5mCG_5hmCG+6mA). 4mC_5mC, 5mC_5hmC, "
             "and 5mCG_5hmCG all act on the same canonical base (C), so combine at most "
             "one of them per group with a non-C mod like 6mA -- Dorado rejects two "
             "same-base mods in one model complex.",
    )
    parser.add_argument(
        "--list_tests",
        action="store_true",
        help="Print the test_name of every case the current arguments would run, then exit "
             "without running anything.",
    )
    parser.add_argument(
        "--poly_a",
        action="store_true",
        help="Add --estimate-poly-a to every basecall in the matrix (DNA and RNA both -- "
             "poly(A) tail estimation isn't RNA-only, it also works on cDNA). Replaces the "
             "old dedicated rna_<library>_poly_a case: instead of one extra RNA-only case, "
             "every case's stats gain the polya_* columns (see README.md). No effect on "
             "which test cases run, only on the command each one uses.",
    )
    parser.add_argument(
        "--dry_run",
        action="store_true",
        help="Build the test matrix and render every case's dorado command(s) without "
             "launching dorado. Still writes manifest.json (status 'dry_run', "
             "wall_time_sec null) and per-case logs under logs/ containing the rendered "
             "command(s), plus the usual stats CSV (all-NaN rows, since nothing basecalled). "
             "A demux command that depends on a prior basecall step's actual output can't be "
             "fully resolved without that step having run; it's logged with a placeholder "
             "for the unresolved part instead of being skipped.",
    )
    args = parser.parse_args(argv)

    args.only = _split_comma_list(args.only)
    args.add_tests = _split_comma_list(args.add_tests)
    args.rna_mod = _parse_mod_groups(args.rna_mod)
    args.dna_mod = _parse_mod_groups(args.dna_mod)

    args.ignore = _split_comma_list(args.ignore)
    invalid = sorted(set(args.ignore) - IGNORABLE_VARIANTS)
    if invalid:
        raise SystemExit(
            f"--ignore only accepts {sorted(IGNORABLE_VARIANTS)}, got: {invalid}"
        )

    validate_args(args)
    return args


def _detect_available_libraries(path: Path, label: str) -> set[str]:
    """A missing multiplex/ or singleplex/ subdir just skips that library's
    cases (warned). Only warn loudly (both missing) instead of failing,
    since the run may still be useful with a single library present."""
    present = {d for d in REQUIRED_SUBDIRS if (path / d).is_dir()}
    missing = set(REQUIRED_SUBDIRS) - present
    if missing and present:
        logger.warning(
            "%s is missing %s under %s; skipping those test cases.",
            label, sorted(missing), path,
        )
    elif not present:
        logger.warning(
            "%s has neither 'multiplex/' nor 'singleplex/' under %s; "
            "no test cases will run for this input.",
            label, path,
        )
    return present


def validate_args(args: argparse.Namespace) -> None:
    if not args.path_to_dorado.is_file():
        raise SystemExit(f"--path_to_dorado does not exist: {args.path_to_dorado}")

    if args.path_to_dna_pod5 is None and args.path_to_rna_pod5 is None:
        raise SystemExit(
            "Expected at least one of --path_to_dna_pod5 or --path_to_rna_pod5 to be provided."
        )

    args.dna_libraries = set()
    if args.path_to_dna_pod5 is not None:
        if not args.path_to_dna_pod5.is_dir():
            raise SystemExit(
                f"--path_to_dna_pod5 does not exist or is not a directory: {args.path_to_dna_pod5}"
            )
        args.dna_libraries = _detect_available_libraries(args.path_to_dna_pod5, "--path_to_dna_pod5")

    args.rna_libraries = set()
    if args.path_to_rna_pod5 is not None:
        if not args.path_to_rna_pod5.is_dir():
            raise SystemExit(
                f"--path_to_rna_pod5 does not exist or is not a directory: {args.path_to_rna_pod5}"
            )
        args.rna_libraries = _detect_available_libraries(args.path_to_rna_pod5, "--path_to_rna_pod5")
