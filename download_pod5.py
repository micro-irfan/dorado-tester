#!/usr/bin/env python3
"""Downloads a handful of real POD5 files from ont-open-data (public, no
AWS credentials needed) and lays them out exactly as run_tests.py expects:

    <output_dir>/dna/multiplex/
    <output_dir>/dna/singleplex/
    <output_dir>/rna/multiplex/
    <output_dir>/rna/singleplex/

So the result can be passed straight through as
--path_to_dna_pod5 <output_dir>/dna and/or --path_to_rna_pod5 <output_dir>/rna.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

from dorado_tester.log import get_logger, setup_logging

MIN_FREE_BYTES = 10 * 1024**3  # 10GB
MAX_FILES = 10

# Each dataset's files are named ..._1<digit>.pod5 (single digit, 0-9), so a
# request for N files becomes a "[0-N-1]" character class here -- which is
# also why N is capped at 10 (one digit).
CATEGORIES: dict[tuple[str, str], dict[str, str]] = {
    ("dna", "multiplex"): {
        "s3_uri": "s3://ont-open-data/pgx_as_2025.07/flowcells/cohort_1/pod5/",
        "filename_template": "PBC88003_08351ad4_aada6c04_1{range}.pod5",
    },
    ("dna", "singleplex"): {
        "s3_uri": "s3://ont-open-data/giab_2025.01/flowcells/HG002/PAW70337/pod5/",
        "filename_template": "PAW70337_66b2eea5_de8117b1_1{range}.pod5",
    },
    ("rna", "multiplex"): {
        "s3_uri": "s3://ont-open-data/UHRR_HG002_2026.06/raw/dRNA/HG002/DRB004_24/HG002_DRB004_24_PolyA_1/",
        "filename_template": "PBM60192_598e5b4d_0120de47_1{range}.pod5",
    },
    ("rna", "singleplex"): {
        "s3_uri": "s3://ont-open-data/UHRR_HG002_2026.06/raw/dRNA/HG002/RNA004/HG002_RNA004_PolyA_1/",
        "filename_template": "PBE81341_30374973_a683f47a_1{range}.pod5",
    },
}

VALID_TYPE_TOKENS = {"dna", "rna", "multiplex", "singleplex"}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download a small set of real POD5 files from ont-open-data "
                    "for exercising run_tests.py against a new Dorado version.",
    )
    parser.add_argument("--output_dir", type=Path, default=Path("./pod5_data"))
    parser.add_argument(
        "--num_files", "-n", type=int, default=1,
        help=f"Pod5 files to fetch per category (1-{MAX_FILES}, default 1).",
    )
    parser.add_argument(
        "--type",
        default=None,
        metavar="TOKEN[,TOKEN...]",
        help="Restrict which categories to download, comma-separated tokens from "
             "{dna, rna, multiplex, singleplex}. A category is downloaded if all "
             "given tokens apply to it, e.g. '--type dna' downloads both DNA "
             "multiplex and DNA singleplex; '--type dna,multiplex' downloads only "
             "DNA multiplex. Default: all four categories.",
    )
    args = parser.parse_args(argv)

    if not 1 <= args.num_files <= MAX_FILES:
        raise SystemExit(f"--num_files must be between 1 and {MAX_FILES}, got {args.num_files}")

    if args.type:
        tokens = {t.strip().lower() for t in args.type.split(",") if t.strip()}
        invalid = sorted(tokens - VALID_TYPE_TOKENS)
        if invalid:
            raise SystemExit(f"--type only accepts {sorted(VALID_TYPE_TOKENS)}, got: {invalid}")
        args.type_tokens = tokens
    else:
        args.type_tokens = set()

    return args


def select_categories(type_tokens: set[str]) -> list[tuple[str, str]]:
    selected = [
        category for category in CATEGORIES
        if not type_tokens or type_tokens <= set(category)
    ]
    if not selected:
        raise SystemExit(f"--type {sorted(type_tokens)} matches no category; nothing to download.")
    return selected


def check_aws_installed() -> None:
    if shutil.which("aws") is None:
        raise SystemExit(
            "aws CLI not found on PATH. Install it (https://docs.aws.amazon.com/cli/) and retry."
        )


def _nearest_existing_dir(path: Path) -> Path:
    path = path.resolve()
    while not path.exists():
        path = path.parent
    return path


def check_free_space(output_dir: Path, min_bytes: int = MIN_FREE_BYTES) -> None:
    free = shutil.disk_usage(_nearest_existing_dir(output_dir)).free
    if free < min_bytes:
        raise SystemExit(
            f"Only {free / 1024**3:.1f}GB free at {output_dir} "
            f"(need at least {min_bytes / 1024**3:.0f}GB)."
        )


def build_include_pattern(filename_template: str, num_files: int) -> str:
    digit_range = "0" if num_files == 1 else f"[0-{num_files - 1}]"
    return filename_template.format(range=digit_range)


def sync_category(analyte: str, library: str, output_dir: Path, num_files: int) -> bool:
    logger = get_logger()
    spec = CATEGORIES[(analyte, library)]
    dest_dir = output_dir / analyte / library
    dest_dir.mkdir(parents=True, exist_ok=True)
    include_pattern = build_include_pattern(spec["filename_template"], num_files)

    cmd = [
        "aws", "s3", "sync", "--no-sign-request",
        spec["s3_uri"], str(dest_dir),
        "--exclude", "*",
        "--include", include_pattern,
    ]
    logger.info("Downloading %s %s (%d file(s)): %s", analyte, library, num_files, " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.stdout:
        logger.info("%s", result.stdout.strip())
    if result.returncode != 0:
        logger.error(
            "%s %s download failed (exit %d): %s",
            analyte, library, result.returncode, (result.stderr or "").strip()[-2000:],
        )
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    logger = setup_logging()
    args = parse_args(argv)

    check_aws_installed()
    check_free_space(args.output_dir)

    categories = select_categories(args.type_tokens)
    logger.info(
        "Fetching %d file(s) each for: %s",
        args.num_files, ", ".join(f"{a}/{l}" for a, l in categories),
    )

    failures = []
    for analyte, library in categories:
        if not sync_category(analyte, library, args.output_dir, args.num_files):
            failures.append(f"{analyte}/{library}")

    if failures:
        logger.error("Failed categories: %s", ", ".join(failures))

    dna_requested = any(a == "dna" for a, _ in categories)
    rna_requested = any(a == "rna" for a, _ in categories)
    logger.info("Done. Pass to run_tests.py as:")
    if dna_requested:
        logger.info("  --path_to_dna_pod5 %s", args.output_dir / "dna")
    if rna_requested:
        logger.info("  --path_to_rna_pod5 %s", args.output_dir / "rna")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
