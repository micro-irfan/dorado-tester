#!/usr/bin/env python3
"""Counts the number of reads in POD5 file(s) -- a single .pod5 file, or a
directory of them (searched recursively) -- logging a per-file count and a
final summed total.

Uses the `pod5` Python package's Reader API (see
https://pod5-file-format.readthedocs.io/). Like extract_reads.py, exact
attribute names haven't all been verified against a real install in this
repo (a prior script's assumption about Writer.add_read() turned out wrong
in practice) -- count_reads() falls back to iterating reader.reads() if
Reader has no usable read-count shortcut.
"""

from __future__ import annotations

import argparse
from pathlib import Path

try:
    import pod5
except ImportError as exc:
    raise SystemExit("`pod5` package not installed. Install it (`pip install pod5`) and retry.") from exc

from dorado_tester.log import get_logger, setup_logging


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Count the number of reads in POD5 file(s), per-file and total.",
    )
    parser.add_argument(
        "--pod5", required=True, type=Path,
        help="A single .pod5 file, or a directory of .pod5 files (searched recursively).",
    )
    args = parser.parse_args(argv)

    if not args.pod5.exists():
        raise SystemExit(f"--pod5 does not exist: {args.pod5}")

    return args


def discover_pod5_files(pod5_path: Path) -> list[Path]:
    if pod5_path.is_file():
        return [pod5_path]
    files = sorted(pod5_path.rglob("*.pod5"))
    if not files:
        raise SystemExit(f"No .pod5 files found under {pod5_path}")
    return files


def count_reads(pod5_file: Path) -> int:
    with pod5.Reader(str(pod5_file)) as reader:
        num_reads = getattr(reader, "num_reads", None)
        if callable(num_reads):
            num_reads = num_reads()
        if isinstance(num_reads, int):
            return num_reads
        return sum(1 for _ in reader.reads())


def main(argv: list[str] | None = None) -> int:
    logger = setup_logging()
    args = parse_args(argv)

    pod5_files = discover_pod5_files(args.pod5)
    logger.info("Found %d .pod5 file(s) under %s", len(pod5_files), args.pod5)

    total = 0
    for pod5_file in pod5_files:
        count = count_reads(pod5_file)
        total += count
        logger.info("%s: %d read(s)", pod5_file, count)

    logger.info("Total: %d read(s) across %d file(s)", total, len(pod5_files))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
