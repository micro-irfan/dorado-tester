"""Combines a version's manifest.json + Dorado outputs into
stats_<version>.csv, plus a per-barcode breakdown (for every multiplex case,
DNA and RNA both, which all classify by barcode one way or another) and a
summary_all_versions.csv across every version run under the results root."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from . import dorado_commands, stats
from .log import get_logger, setup_logging

# error_message and commands_executed are deliberately not stats CSV columns:
# both are already recorded per-case in manifest.json.
STATS_COLUMNS = [
    "dorado_version", "analyte", "library", "test_name", "model", "resolved_models", "mods",
    "status", "wall_time_sec",
    "num_reads", "num_reads_passed", "num_bases", "num_bases_passed",
    "n50", "read_len_mean", "read_len_median", "read_len_mode",
    "read_len_min", "read_len_max",
    "mean_qscore", "median_qscore", "qscore_min", "qscore_max",
    "polya_median", "polya_mean",
]

logger = get_logger()


def load_manifest(manifest_path: Path) -> dict:
    with open(manifest_path, encoding="utf-8") as fh:
        return json.load(fh)


def _empty_case_stats() -> dict:
    return {
        "num_reads": float("nan"),
        "num_reads_passed": float("nan"),
        "num_bases": float("nan"),
        "num_bases_passed": float("nan"),
        "n50": float("nan"),
        "read_len_mean": float("nan"),
        "read_len_median": float("nan"),
        "read_len_mode": float("nan"),
        "read_len_min": float("nan"),
        "read_len_max": float("nan"),
        "mean_qscore": float("nan"),
        "median_qscore": float("nan"),
        "qscore_min": float("nan"),
        "qscore_max": float("nan"),
        "polya_median": float("nan"),
        "polya_mean": float("nan"),
    }


def _is_barcode_classified_case(case: dict) -> bool:
    """Every multiplex case (DNA and RNA both) classifies by barcode one way
    or another: the general cases via inline --kit-name during basecalling
    (verified v2.0.1: this alone splits output into per-barcode
    bam_pass/<barcode>/ files, no demux step involved), and DNA's dedicated
    barcode-kit case via a separate demux step. Singleplex doesn't."""
    return case["library"] == "multiplex"


def _barcode_scan_dir(case: dict) -> Path:
    output_dir = Path(case["output_dir"])
    demux_dir = output_dir / "demux"
    return demux_dir if demux_dir.is_dir() else output_dir


def _case_bam_paths(case: dict) -> list[Path]:
    """The dedicated barcode-kit case has a demux/ subfolder with the
    (final, already-split) per-barcode output alongside the pre-demux bam(s)
    -- stats must come only from demux/, not a recursive scan of the whole
    output_dir, or every read gets double-counted. Cases without a demux/
    subfolder (including the other, inline-classified multiplex cases) have
    no such duplication, so a plain recursive scan is already correct."""
    output_dir = Path(case["output_dir"])
    demux_dir = output_dir / "demux"
    if demux_dir.is_dir():
        groups = stats.discover_barcode_bams(demux_dir)
        return [bam for bams in groups.values() for bam in bams]
    return dorado_commands.find_output_bams(output_dir)


def build_case_row(dorado_path: str, dorado_version: str, case: dict) -> dict:
    row = {
        "dorado_version": dorado_version,
        "analyte": case["analyte"],
        "library": case["library"],
        "test_name": case["test_name"],
        "model": case["model"],
        "resolved_models": ";".join(stats.extract_resolved_models(Path(case["log_path"]))),
        "mods": ";".join(case.get("mods") or []),
        "status": case["status"],
        "wall_time_sec": case["wall_time_sec"],
    }
    row.update(_empty_case_stats())

    if case["status"] != "success":
        return row

    bam_paths = _case_bam_paths(case)
    if not bam_paths:
        row["status"] = "failed"
        logger.warning("%s: no output BAM files found for stats", case["test_name"])
        return row

    try:
        row.update(stats.compute_bam_stats(
            dorado_path, bam_paths, case["model"],
            estimate_poly_a=case["test_name"].endswith("_poly_a"),
        ))
    except Exception as exc:
        row["status"] = "failed"
        logger.warning("%s: stats computation failed: %s", case["test_name"], exc)
    return row


def build_per_barcode_rows(dorado_path: str, dorado_version: str, case: dict) -> list[dict]:
    groups = stats.discover_barcode_bams(_barcode_scan_dir(case))
    rows = []
    for barcode, bam_paths in sorted(groups.items()):
        row = {
            "dorado_version": dorado_version,
            "analyte": case["analyte"],
            "library": case["library"],
            "test_name": case["test_name"],
            "barcode": barcode,
            "model": case["model"],
            "resolved_models": ";".join(stats.extract_resolved_models(Path(case["log_path"]))),
        }
        row.update(_empty_case_stats())
        try:
            row.update(stats.compute_bam_stats(dorado_path, bam_paths, case["model"]))
        except Exception as exc:
            logger.warning("%s [%s]: stats computation failed: %s", case["test_name"], barcode, exc)
        rows.append(row)
    return rows


def aggregate_version(version_dir: Path) -> Path:
    manifest = load_manifest(version_dir / "manifest.json")
    dorado_path = manifest["dorado_path"]
    dorado_version = manifest["dorado_version"]

    rows = [build_case_row(dorado_path, dorado_version, case) for case in manifest["cases"]]
    stats_df = pd.DataFrame(rows, columns=STATS_COLUMNS)
    stats_csv_path = version_dir / f"stats_{manifest['dorado_version_safe']}.csv"
    stats_df.to_csv(stats_csv_path, index=False)

    per_barcode_rows = []
    for case in manifest["cases"]:
        if case["status"] != "success":
            continue
        if not _is_barcode_classified_case(case):
            continue
        per_barcode_rows.extend(build_per_barcode_rows(dorado_path, dorado_version, case))

    if per_barcode_rows:
        per_barcode_csv_path = version_dir / f"stats_{manifest['dorado_version_safe']}_per_barcode.csv"
        pd.DataFrame(per_barcode_rows).to_csv(per_barcode_csv_path, index=False)

    return stats_csv_path


def build_summary_all_versions(results_root: Path) -> Path:
    frames = [
        pd.read_csv(stats_csv)
        for stats_csv in sorted(results_root.glob("*/stats_*.csv"))
        if not stats_csv.name.endswith("_per_barcode.csv")
    ]
    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=STATS_COLUMNS)
    summary_path = results_root / "summary_all_versions.csv"
    combined.to_csv(summary_path, index=False)
    return summary_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Aggregate per-case Dorado test results into comparison spreadsheets.",
    )
    parser.add_argument(
        "--output_dir", type=Path, default=Path("results"),
        help="Root results directory containing one subdirectory per Dorado version.",
    )
    parser.add_argument(
        "--version", default=None,
        help="Only aggregate this version's results/<version> subdirectory. Default: all versions found.",
    )
    args = parser.parse_args(argv)
    setup_logging()

    if args.version:
        version_dirs = [args.output_dir / args.version]
    else:
        version_dirs = sorted(
            d for d in args.output_dir.iterdir() if d.is_dir() and (d / "manifest.json").is_file()
        )

    for version_dir in version_dirs:
        if not (version_dir / "manifest.json").is_file():
            logger.warning("Skipping %s: no manifest.json found", version_dir)
            continue
        stats_csv_path = aggregate_version(version_dir)
        logger.info("Wrote %s", stats_csv_path)

    summary_path = build_summary_all_versions(args.output_dir)
    logger.info("Wrote %s", summary_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
