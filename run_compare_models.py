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
import re
import sys
from pathlib import Path

from dorado_tester import aggregate, runner, version
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


# Best-effort mod-code -> canonical-base guesses, used only to catch an
# *obvious* same-base conflict (e.g. 5mC_5hmC + 5mCG_5hmCG, both C) before
# wasting a run on it. Not exhaustive, and can't catch everything Dorado
# itself would reject -- e.g. the mod-model "architecture type" conflict
# noted in CLAUDE.md (m6A vs pseU) isn't a same-base conflict at all and
# has no way to be detected without asking Dorado.
_MOD_BASE_RE = re.compile(r"m\d*([acgtu])")


def _canonical_base(mod_code: str) -> str | None:
    key = mod_code.lower()
    if key.startswith("pseu"):
        return "U"
    if key.startswith("inosine"):
        return "A"
    if key.startswith("2ome") and len(key) > 4:
        return key[4].upper()
    match = _MOD_BASE_RE.search(key)
    return match.group(1).upper() if match else None


def _check_mod_conflicts(mods: list[str]) -> None:
    seen: dict[str, str] = {}
    for mod in mods:
        base = _canonical_base(mod)
        if base is None:
            continue
        if base in seen and seen[base] != mod:
            raise SystemExit(
                f"--mods {mods} has a canonical-base conflict: '{seen[base]}' and '{mod}' "
                f"both look like they act on {base} -- Dorado can't combine two mods on "
                f"the same base (see CLAUDE.md). This check is best-effort (unrecognized "
                f"codes aren't checked), so a combination that passes here can still be "
                f"rejected by Dorado for other reasons, e.g. mismatched mod-model "
                f"architecture types."
            )
        seen[base] = mod


def _version_sort_key(v: str) -> tuple[int, ...]:
    return tuple(int(p) for p in v.lstrip("vV").split("."))


def _resolve_mod_models(base_model: str, mod_codes: list[str], catalog_text: str) -> list[str] | None:
    """Finds the highest-numbered '<base_model>_<mod_code>@v<N...>' entry in
    `dorado download --list` output for each mod code. Returns None if any
    code has no match at all for this exact base model -- the caller decides
    what to do (skip this model, same as any other per-case failure)."""
    resolved = []
    for code in mod_codes:
        pattern = re.compile(re.escape(f"{base_model}_{code}@") + r"(v[\d.]+)")
        versions = pattern.findall(catalog_text)
        if not versions:
            return None
        best = max(versions, key=_version_sort_key)
        resolved.append(f"{base_model}_{code}@{best}")
    return resolved


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
        help="Comma-separated mod codes applied to every model being compared, e.g. "
             "'5mCG_5hmCG,6mA'. Each is resolved to the highest available fully-qualified "
             "mod model name for that exact pinned base model (via `dorado download "
             "--list`) and passed through --modified-bases-models -- a bare code appended "
             "to a pinned model@version, unlike a floating hac/sup alias, doesn't resolve "
             "on its own. A model missing a requested mod is skipped, same as any other "
             "per-case failure. Optional.",
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
    parser.add_argument(
        "--poly_a", action="store_true",
        help="Add --estimate-poly-a to the basecall (poly(A) tail length written to the "
             "pt:i: BAM tag). Works for DNA tests too, not just RNA -- poly(A) tail "
             "estimation isn't RNA-only, it also works on cDNA.",
    )
    parser.add_argument("--output_dir", type=Path, default=Path("results_compare"))
    parser.add_argument("--device", default="auto")
    parser.add_argument("--models_directory", type=Path, default=None)
    parser.add_argument(
        "--strict", action="store_true",
        help="Exit non-zero if any model failed.",
    )
    parser.add_argument(
        "--dry_run", action="store_true",
        help="Render every model's dorado command(s) without launching dorado. Still writes "
             "manifest.json (status 'dry_run', wall_time_sec null) and per-case logs under "
             "logs/ containing the rendered command(s), plus the usual stats CSV (all-NaN "
             "rows, since nothing basecalled).",
    )
    args = parser.parse_args(argv)

    if not args.path_to_dorado.is_file():
        raise SystemExit(f"--path_to_dorado does not exist: {args.path_to_dorado}")

    args.models = _split_list(args.models)
    if len(args.models) < 2:
        raise SystemExit(f"--models needs at least 2 pinned model names to compare, got {len(args.models)}")

    args.mods = _split_list(args.mods)
    _check_mod_conflicts(args.mods)

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
    catalog_text = None
    if args.mods:
        logger.info("Mods applied to every model (if available): %s", ", ".join(args.mods))
        catalog_text = runner.get_available_mods_output(dorado_path, models_directory) or ""

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

    estimate_poly_a = args.poly_a

    cases = []
    for model, tag in zip(args.models, version_tags):
        modified_bases_models = None
        if args.mods:
            resolved_mods = _resolve_mod_models(model, args.mods, catalog_text)
            if resolved_mods is None:
                logger.warning(
                    "%s: no compatible mod model found for one or more of %s for this "
                    "exact pinned model in `dorado download --list`; skipping.",
                    tag, args.mods,
                )
                continue
            modified_bases_models = ",".join(resolved_mods)
            logger.info("%s: resolved --mods to %s", tag, modified_bases_models)

        case_out = output_root / tag
        cases.append(runner.TestCase(
            analyte=analyte, library=library, test_name=tag,
            output_dir=case_out,
            command_builders=[runner.basecaller_builder(
                dorado_path, model, lib_dir, case_out,
                kit_name=kit_name, estimate_poly_a=estimate_poly_a,
                models_directory=models_directory, device=args.device,
                modified_bases_models=modified_bases_models,
            )],
            model=model, mods=list(args.mods),
            estimate_poly_a=estimate_poly_a,
        ))

    results = runner.run_all(cases, output_root, dry_run=args.dry_run)

    n_success = sum(1 for r in results if r.status == "success")
    n_dry_run = sum(1 for r in results if r.status == "dry_run")
    n_failed = len(results) - n_success - n_dry_run
    if args.dry_run:
        logger.info("Dry run complete: %d case(s) rendered, not executed.", n_dry_run)
    elif n_failed:
        logger.warning("Completed: %d succeeded, %d failed.", n_success, n_failed)
    else:
        logger.info("Completed: %d succeeded, %d failed.", n_success, n_failed)

    manifest_path = output_root / "manifest.json"
    runner.write_manifest(results, dorado_version, dorado_path, manifest_path, dry_run=args.dry_run)
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
