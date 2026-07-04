#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

from dorado_tester import aggregate, cli, runner, version
from dorado_tester.log import setup_logging

MODS_CONFIG_PATH = Path(__file__).resolve().parent / "config" / "mods.yaml"


def resolve_output_root(output_dir: Path, version_safe: str) -> Path:
    """Never reuses an existing results/<version>/ -- always picks a fresh
    <version>_1, <version>_2, ... instead, so one run's output can't get
    mixed into another's manifest.json/logs."""
    candidate = output_dir / version_safe
    if not candidate.exists():
        return candidate
    i = 1
    while (output_dir / f"{version_safe}_{i}").exists():
        i += 1
    return output_dir / f"{version_safe}_{i}"


def main(argv: list[str] | None = None) -> int:
    logger = setup_logging()
    args = cli.parse_args(argv)
    dorado_path = str(args.path_to_dorado)

    dorado_version = version.get_dorado_version(dorado_path)
    logger.info("Dorado version: %s", dorado_version.raw)

    output_root = resolve_output_root(args.output_dir, dorado_version.safe)
    output_root.mkdir(parents=True, exist_ok=True)
    if output_root.name != dorado_version.safe:
        logger.info(
            "results/%s already exists; writing this run to %s instead",
            dorado_version.safe, output_root.name,
        )

    models_directory = args.models_directory
    if models_directory:
        models_directory.mkdir(parents=True, exist_ok=True)

    mods_config = runner.load_mods_config(MODS_CONFIG_PATH)
    available_mods_output = runner.get_available_mods_output(dorado_path, models_directory)

    dna_mods = runner.resolve_compatible_mods(
        mods_config.get("dna", {}).get("compatible_mods", []), available_mods_output
    )
    rna_mods = runner.resolve_compatible_mods(
        mods_config.get("rna", {}).get("compatible_mods", []), available_mods_output
    )

    rna_mod_extra_groups = []
    for group in args.rna_mod:
        resolved = runner.resolve_compatible_mods(group, available_mods_output)
        if not resolved:
            logger.warning(
                "--rna_mod group %s has no mods supported by this Dorado version; skipping.",
                group,
            )
            continue
        rna_mod_extra_groups.append(resolved)

    cases = runner.build_test_matrix(
        dorado_path=dorado_path,
        dna_pod5_dir=args.path_to_dna_pod5,
        rna_pod5_dir=args.path_to_rna_pod5,
        dna_kit=args.dna_kit,
        rna_kit=args.rna_kit,
        output_root=output_root,
        models_directory=models_directory,
        device=args.device,
        dna_mods=dna_mods,
        rna_mods=rna_mods,
        dna_libraries=args.dna_libraries,
        rna_libraries=args.rna_libraries,
        ignore=set(args.ignore),
        rna_mod_extra_groups=rna_mod_extra_groups,
    )

    if args.list_tests:
        for case in cases:
            print(case.test_name)
        return 0

    if args.only:
        if args.add_tests:
            logger.warning(
                "--only and --add_tests both given; ignoring --add_tests since --only "
                "already selects the exact cases to run: %s",
                sorted(args.add_tests),
            )
        requested = set(args.only)
        available = {c.test_name for c in cases}
        unknown = sorted(requested - available)
        if unknown:
            logger.warning("Unknown --only test name(s), skipping: %s", unknown)
        cases = [c for c in cases if c.test_name in requested]
        if not cases:
            logger.warning("No matching test cases to run.")
    else:
        available = {c.test_name for c in cases}
        add_tests = set(args.add_tests)
        unknown_add = sorted(add_tests - available)
        if unknown_add:
            logger.warning("Unknown --add_tests test name(s), ignoring: %s", unknown_add)

        dynamic_excluded = {c.test_name for c in cases if c.default_excluded}
        to_exclude = (runner.DEFAULT_EXCLUDED_TESTS | dynamic_excluded) - add_tests
        excluded = [c for c in cases if c.test_name in to_exclude]
        if excluded:
            logger.info(
                "Excluding from default run (use --only or --add_tests to run explicitly): %s",
                sorted(c.test_name for c in excluded),
            )
        cases = [c for c in cases if c.test_name not in to_exclude]

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
        summary_path = aggregate.build_summary_all_versions(args.output_dir)
        logger.info("Cross-version summary written to %s", summary_path)
    except Exception as exc:
        logger.error("Stats aggregation failed (test results above are unaffected): %s", exc)

    if args.strict and n_failed > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
