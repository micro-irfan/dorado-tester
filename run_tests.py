#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

from dorado_tester import aggregate, cli, runner, version

MODS_CONFIG_PATH = Path(__file__).resolve().parent / "config" / "mods.yaml"


def main(argv: list[str] | None = None) -> int:
    args = cli.parse_args(argv)
    dorado_path = str(args.path_to_dorado)

    dorado_version = version.get_dorado_version(dorado_path)
    print(f"Dorado version: {dorado_version.raw}")

    output_root = args.output_dir / dorado_version.safe
    output_root.mkdir(parents=True, exist_ok=True)

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

    if args.test_fast and args.ignore_sup:
        print("--test_fast overrides --ignore_sup; running the fast model variant only.")

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
        ignore_sup=args.ignore_sup,
        test_fast=args.test_fast,
    )

    print(f"Running {len(cases)} test cases...")
    results = runner.run_all(cases, output_root)

    n_success = sum(1 for r in results if r.status == "success")
    n_failed = len(results) - n_success
    print(f"Completed: {n_success} succeeded, {n_failed} failed.")

    manifest_path = output_root / "manifest.json"
    runner.write_manifest(results, dorado_version, dorado_path, manifest_path)
    print(f"Manifest written to {manifest_path}")

    try:
        stats_csv_path = aggregate.aggregate_version(output_root)
        print(f"Stats written to {stats_csv_path}")
        summary_path = aggregate.build_summary_all_versions(args.output_dir)
        print(f"Cross-version summary written to {summary_path}")
    except Exception as exc:
        print(f"Stats aggregation failed (test results above are unaffected): {exc}")

    if args.strict and n_failed > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
