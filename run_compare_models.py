#!/usr/bin/env python3
"""Compares specific, pinned Dorado model versions (not speed aliases) for
one basecalling test, against a single Dorado executable -- e.g. is
dna_r10.4.1_e8.2_400bps_hac@v5.0.0 meaningfully different from
...@v6.0.0? Model names come from
https://software-docs.nanoporetech.com/dorado/latest/models/list/ (or
`<dorado> download --list`) and must be given in full -- this script never
resolves a speed alias for you.

One invocation = one test + one speed (the test picks it) + 2 or more pinned
model versions of that same analyte/speed, all basecalled against the same
POD5 input with the same Dorado executable. A failing model is recorded and
skipped, same as run_tests.py -- it never aborts the comparison.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dorado_tester import aggregate, dorado_commands, runner, version
from dorado_tester.log import setup_logging

# analyte, library, speed -- model-name validation, --kit-name, and the
# output layout all key off these, so every allowed --test is spelled out
# explicitly rather than parsed back out of the string.
TEST_SPECS: dict[str, tuple[str, str, str]] = {
    "dna_singleplex_simplex_hac": ("DNA", "singleplex", "hac"),
    "dna_singleplex_simplex_sup": ("DNA", "singleplex", "sup"),
    "dna_multiplex_simplex_hac": ("DNA", "multiplex", "hac"),
    "dna_multiplex_simplex_sup": ("DNA", "multiplex", "sup"),
    "rna_singleplex_simplex_hac": ("RNA", "singleplex", "hac"),
    "rna_singleplex_simplex_sup": ("RNA", "singleplex", "sup"),
    "rna_multiplex_simplex_hac": ("RNA", "multiplex", "hac"),
    "rna_multiplex_simplex_sup": ("RNA", "multiplex", "sup"),
}

# --test already implies the analyte, so --kit_name doesn't need a static
# default the way --dna_kit/--rna_kit do in run_tests.py -- fall back to
# whichever of these matches, only when --test is a multiplex test.
DEFAULT_KIT_NAMES = {"DNA": "SQK-NBD114-24", "RNA": "SQK-DRB004-24"}


def _split_list(value: str | None) -> list[str]:
    if not value:
        return []
    return [v.strip() for v in value.split(",") if v.strip()]


def _version_tag(model: str) -> str:
    """'dna_r10.4.1_e8.2_400bps_hac@v6.0.0' -> 'v6.0.0'."""
    return model.rsplit("@", 1)[-1]


def _validate_models(models: list[str], analyte: str, speed: str) -> None:
    """Only checks the model name *looks* like it matches --test's analyte
    and speed (e.g. starts with 'dna'/'rna', contains '_hac@'/'_sup@'). It
    does not check the model actually exists -- if it doesn't, dorado itself
    will error out when asked to download/load it, same as any other case."""
    analyte_prefix = analyte.lower()
    speed_marker = f"_{speed}@"
    bad = [
        m for m in models
        if not m.lower().startswith(analyte_prefix) or speed_marker not in m
    ]
    if bad:
        raise SystemExit(
            f"--models entries must be full {analyte} {speed} model names "
            f"(expected to start with '{analyte_prefix}' and contain '{speed_marker}'), "
            f"got: {bad}"
        )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare specific pinned Dorado model versions for one basecalling "
                    "test, against a single Dorado executable.",
    )
    parser.add_argument("--path_to_dorado", required=True, type=Path)
    parser.add_argument(
        "--test", default="dna_singleplex_simplex_hac", choices=sorted(TEST_SPECS),
        help="Which test to run. Default: dna_singleplex_simplex_hac.",
    )
    parser.add_argument(
        "--models", required=True,
        help="Comma-separated, full versioned model names to compare (2 or more), e.g. "
             "'dna_r10.4.1_e8.2_400bps_hac@v5.0.0,dna_r10.4.1_e8.2_400bps_hac@v6.0.0'. "
             "See https://software-docs.nanoporetech.com/dorado/latest/models/list/ "
             "or `<dorado> download --list`.",
    )
    parser.add_argument(
        "--mods", default=None,
        help="Comma-separated mod codes appended to every model being compared, e.g. "
             "'5mCG_5hmCG,6mA'. Applied identically to all --models. Optional.",
    )
    parser.add_argument(
        "--path_to_pod5", type=Path, required=True,
        help="Directory containing multiplex/ and singleplex/ (same layout as run_tests.py). "
             "Whichever --test needs is validated; there's no separate --path_to_dna_pod5 / "
             "--path_to_rna_pod5 since --test already implies the analyte.",
    )
    parser.add_argument(
        "--kit_name", default=None,
        help="Barcode kit name, only used if --test is a multiplex test (adds --kit-name "
             "to the basecall). Defaults to SQK-NBD114-24 for DNA / SQK-DRB004-24 for RNA "
             "tests if omitted.",
    )
    parser.add_argument("--output_dir", type=Path, default=Path("results_compare"))
    parser.add_argument("--device", default="auto")
    parser.add_argument("--models_directory", type=Path, default=None)
    parser.add_argument(
        "--strict", action="store_true",
        help="Exit non-zero if any model failed.",
    )
    args = parser.parse_args(argv)

    if not args.path_to_dorado.is_file():
        raise SystemExit(f"--path_to_dorado does not exist: {args.path_to_dorado}")

    args.models = _split_list(args.models)
    if len(args.models) < 2:
        raise SystemExit(f"--models needs at least 2 pinned model names to compare, got {len(args.models)}")

    args.mods = _split_list(args.mods)

    analyte, library, speed = TEST_SPECS[args.test]
    _validate_models(args.models, analyte, speed)

    version_tags = [_version_tag(m) for m in args.models]
    if len(set(version_tags)) != len(version_tags):
        raise SystemExit(f"--models has duplicate version tags, can't tell them apart: {version_tags}")

    if not args.path_to_pod5.is_dir():
        raise SystemExit(f"--path_to_pod5 does not exist or is not a directory: {args.path_to_pod5}")
    lib_dir = args.path_to_pod5 / library
    if not lib_dir.is_dir():
        raise SystemExit(
            f"--path_to_pod5 is missing the '{library}/' subdirectory required by --test {args.test}: {lib_dir}"
        )

    return args


def main(argv: list[str] | None = None) -> int:
    logger = setup_logging()
    args = parse_args(argv)
    dorado_path = str(args.path_to_dorado)
    analyte, library, speed = TEST_SPECS[args.test]

    lib_dir = args.path_to_pod5 / library

    dorado_version = version.get_dorado_version(dorado_path)
    logger.info("Dorado version: %s", dorado_version.raw)

    models_directory = args.models_directory
    if models_directory:
        models_directory.mkdir(parents=True, exist_ok=True)

    version_tags = [_version_tag(m) for m in args.models]
    version_label = "-".join(version_tags)
    logger.info(
        "Comparing %d model(s) for %s: %s",
        len(args.models), args.test,
        ", ".join(f"{m} ({t})" for m, t in zip(args.models, version_tags)),
    )
    if args.mods:
        logger.info("Mods applied to every model: %s", ", ".join(args.mods))

    base_dir = args.output_dir / args.test
    output_root = runner.resolve_output_root(base_dir, version_label)
    output_root.mkdir(parents=True, exist_ok=True)
    if output_root.name != version_label:
        logger.info(
            "%s already exists; writing this run to %s instead",
            base_dir / version_label, output_root.name,
        )

    kit_name = None
    if library == "multiplex":
        kit_name = args.kit_name or DEFAULT_KIT_NAMES[analyte]

    cases = []
    for model, tag in zip(args.models, version_tags):
        model_arg = dorado_commands.build_model_with_mods(model, args.mods)
        case_out = output_root / tag
        cases.append(runner.TestCase(
            analyte=analyte, library=library, test_name=tag,
            output_dir=case_out,
            command_builders=[runner.basecaller_builder(
                dorado_path, model_arg, lib_dir, case_out,
                kit_name=kit_name,
                models_directory=models_directory, device=args.device,
            )],
            model=model, mods=list(args.mods),
        ))

    results = runner.run_all(cases, output_root)

    n_success = sum(1 for r in results if r.status == "success")
    n_failed = len(results) - n_success
    if n_failed:
        logger.warning("Completed: %d succeeded, %d failed.", n_success, n_failed)
    else:
        logger.info("Completed: %d succeeded, %d failed.", n_success, n_failed)

    manifest_path = output_root / "manifest.json"
    runner.write_manifest(results, dorado_version, dorado_path, manifest_path)
    logger.info("Manifest written to %s", manifest_path)

    try:
        stats_csv_path = aggregate.aggregate_version(output_root)
        logger.info("Stats written to %s", stats_csv_path)
    except Exception as exc:
        logger.error("Stats aggregation failed (test results above are unaffected): %s", exc)

    if args.strict and n_failed > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
