#!/usr/bin/env python3
"""Extracts a set of reads (by read ID) out of one or more POD5 files and
merges them into a single new POD5 file -- e.g. to build a small repro/test
POD5 from a handful of interesting read ids found during basecalling.

Uses the `pod5` Python package's Reader/Writer API (documented at
https://pod5-file-format.readthedocs.io/, "Sub-setting Reads"). Like
convert_fast5_to_pod5.py's use of the `pod5` CLI, this isn't verified
against a real install in this repo -- check the pod5 package's docs for
your installed version if something doesn't match.
"""

from __future__ import annotations

import argparse
import uuid
from pathlib import Path

try:
    import pod5
except ImportError as exc:
    raise SystemExit("`pod5` package not installed. Install it (`pip install pod5`) and retry.") from exc

from dorado_tester.log import get_logger, setup_logging


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract reads by read ID from POD5 file(s) into a single merged POD5 file.",
    )
    parser.add_argument(
        "--pod5", required=True, type=Path,
        help="A single .pod5 file, or a directory of .pod5 files (searched recursively).",
    )
    parser.add_argument(
        "--read_ids", required=True,
        help="A single read ID, or a path to a text file listing read IDs (one per line).",
    )
    parser.add_argument(
        "--output", required=True, type=Path,
        help="Path to write the merged output .pod5 file.",
    )
    args = parser.parse_args(argv)

    if not args.pod5.exists():
        raise SystemExit(f"--pod5 does not exist: {args.pod5}")

    if args.output.exists():
        raise SystemExit(
            f"--output already exists: {args.output} (choose a different path or remove it first)"
        )

    return args


def load_requested_read_ids(read_ids_arg: str) -> list[str]:
    candidate = Path(read_ids_arg)
    if candidate.is_file():
        lines = [line.strip() for line in candidate.read_text().splitlines()]
        ids = [line for line in lines if line]
    else:
        ids = [read_ids_arg.strip()]

    if not ids:
        raise SystemExit(f"No read IDs found in --read_ids: {read_ids_arg}")

    # De-duplicate (case-insensitively, since POD5 read ids are lowercase
    # UUIDs but user-supplied lists may not be) while preserving order.
    seen: set[str] = set()
    deduped = []
    for read_id in ids:
        normalised = read_id.lower()
        if normalised not in seen:
            seen.add(normalised)
            deduped.append(normalised)
    return deduped


def split_valid_read_ids(read_ids: list[str]) -> tuple[list[str], list[str]]:
    valid, malformed = [], []
    for read_id in read_ids:
        try:
            uuid.UUID(read_id)
            valid.append(read_id)
        except ValueError:
            malformed.append(read_id)
    return valid, malformed


def discover_pod5_files(pod5_path: Path) -> list[Path]:
    if pod5_path.is_file():
        return [pod5_path]
    files = sorted(pod5_path.rglob("*.pod5"))
    if not files:
        raise SystemExit(f"No .pod5 files found under {pod5_path}")
    return files


def extract_reads(pod5_files: list[Path], requested_ids: list[str], output_path: Path) -> set[str]:
    logger = get_logger()
    remaining = set(requested_ids)
    found: set[str] = set()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with pod5.Writer(str(output_path)) as writer:
        for pod5_file in pod5_files:
            if not remaining:
                break
            logger.info("Scanning %s (%d read ID(s) still outstanding)", pod5_file, len(remaining))
            with pod5.Reader(str(pod5_file)) as reader:
                for read_record in reader.reads(selection=remaining, missing_ok=True):
                    read_id = str(read_record.read_id).lower()
                    writer.add_read(read_record)
                    found.add(read_id)
                    remaining.discard(read_id)

    return found


def main(argv: list[str] | None = None) -> int:
    logger = setup_logging()
    args = parse_args(argv)

    requested_ids = load_requested_read_ids(args.read_ids)
    valid_ids, malformed_ids = split_valid_read_ids(requested_ids)
    for read_id in malformed_ids:
        logger.warning("Skipping malformed read ID (not a valid UUID): %s", read_id)

    pod5_files = discover_pod5_files(args.pod5)
    logger.info(
        "Found %d .pod5 file(s) to search for %d requested read ID(s)",
        len(pod5_files), len(requested_ids),
    )

    found = extract_reads(pod5_files, valid_ids, args.output) if valid_ids else set()

    missing = [rid for rid in requested_ids if rid not in found]
    if missing:
        logger.warning("%d read ID(s) not found:", len(missing))
        for read_id in missing:
            logger.warning("  %s", read_id)

    if not found:
        args.output.unlink(missing_ok=True)
        logger.error("0/%d read IDs found. No output written.", len(requested_ids))
        return 1

    logger.info("%d/%d read IDs found. Output written to %s", len(found), len(requested_ids), args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
