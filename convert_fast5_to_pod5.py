#!/usr/bin/env python3
"""Converts FAST5 files to POD5 -- the format run_tests.py/
run_compare_models.py/download_pod5.py all expect -- via the `pod5` CLI
(https://pod5-file-format.readthedocs.io/), installed with `pip install
pod5` (or `pod5[fast5]` if this platform's pod5 build doesn't already
bundle FAST5 read support).

Unlike dorado_commands.py's invocations, the exact `pod5 convert fast5`
flags below are taken from the pod5 project's published docs, not verified
against a real install in this repo -- if something doesn't match, check
`pod5 convert fast5 --help` for your installed version.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from dorado_tester.log import setup_logging


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert a directory of FAST5 files to POD5, via the `pod5` CLI.",
    )
    parser.add_argument(
        "--input_dir", required=True, type=Path,
        help="Directory of .fast5 files (searched recursively).",
    )
    parser.add_argument(
        "--output_dir", required=True, type=Path,
        help="Where to write .pod5 output.",
    )
    parser.add_argument(
        "--merge", action="store_true",
        help="Merge every input .fast5 into a single <output_dir>/converted.pod5. "
             "Default is one .pod5 per .fast5, mirroring --input_dir's structure "
             "under --output_dir (via `pod5`'s --output-one-to-one) -- safer for a "
             "large FAST5 set than one big merged file.",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Overwrite existing output .pod5 file(s) (passes --force-overwrite to `pod5`).",
    )
    args = parser.parse_args(argv)

    if not args.input_dir.is_dir():
        raise SystemExit(f"--input_dir does not exist or is not a directory: {args.input_dir}")

    return args


def check_pod5_installed() -> None:
    if shutil.which("pod5") is None:
        raise SystemExit(
            "`pod5` CLI not found on PATH. Install it (`pip install pod5`, or "
            "`pip install pod5[fast5]` if this build needs FAST5 read support) and retry."
        )


def build_convert_command(
    input_dir: Path, output_dir: Path, *, merge: bool, force: bool
) -> list[str]:
    output_target = output_dir / "converted.pod5" if merge else output_dir
    cmd = ["pod5", "convert", "fast5", str(input_dir), "--recursive", "--output", str(output_target)]
    if not merge:
        cmd += ["--output-one-to-one", str(input_dir)]
    if force:
        cmd.append("--force-overwrite")
    return cmd


def main(argv: list[str] | None = None) -> int:
    logger = setup_logging()
    args = parse_args(argv)

    check_pod5_installed()

    fast5_files = sorted(args.input_dir.rglob("*.fast5"))
    if not fast5_files:
        raise SystemExit(f"No .fast5 files found under {args.input_dir}")
    logger.info("Found %d .fast5 file(s) under %s", len(fast5_files), args.input_dir)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    cmd = build_convert_command(args.input_dir, args.output_dir, merge=args.merge, force=args.force)
    logger.info("Running: %s", " ".join(cmd))

    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.stdout:
        logger.info("%s", result.stdout.strip())
    if result.returncode != 0:
        logger.error(
            "pod5 convert failed (exit %d): %s",
            result.returncode, (result.stderr or "").strip()[-2000:],
        )
        return 1

    logger.info("Done. POD5 output written to %s", args.output_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
