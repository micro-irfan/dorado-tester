#!/usr/bin/env python3
"""Runs an arbitrary, one-off `dorado` command line (or a short pipeline of
them) -- for exercising a subcommand or flag combination that isn't (yet)
part of run_tests.py's or run_compare_models.py's fixed test matrices,
without having to wire it into either. Dorado's CLI surface changes across
versions faster than any fixed matrix can track every combination.

--command accepts either a literal command string (the previous behavior)
or a path to a text file listing one or more commands -- see examples/ for
sample pipelines and the file-format rules (blank/backslash handling,
multi-command files).

Same conventions as the other scripts: full stdout/stderr captured to a log
file under `logs/`, and a manifest.json recording the exact command(s) and
outcome. If the *last* command in the pipeline is a `basecaller` or
`aligner` call and the whole pipeline completes successfully, a
best-effort stats.csv is also computed from whatever *.bam it produced (see
stats.compute_bam_stats). Any other subcommand (demux, duplex, download,
summary, trim, correct, smallvar, ...) just gets the log + manifest -- no
stats file, since this repo hasn't verified their output shape.
"""

from __future__ import annotations

import argparse
import shlex
import sys
from pathlib import Path

import pandas as pd

from dorado_tester import dorado_commands, runner, stats, version
from dorado_tester.log import setup_logging

# Subcommands whose output is a bam we know how to find and summarize.
# Anything else (demux, duplex, download, summary, ...) just gets the log +
# manifest -- deliberately not guessed at beyond what was asked for.
STATS_CAPABLE_SUBCOMMANDS = {"basecaller", "aligner"}

# Both spellings dorado uses for "where did the output go" across
# subcommands (basecaller/aligner use -o, demux uses --output-dir).
_OUTPUT_FLAGS = {"-o", "--output-dir"}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run an arbitrary dorado command (or short pipeline of them), "
                    "capturing a log and manifest.json like run_tests.py/"
                    "run_compare_models.py, plus a best-effort stats.csv if the last "
                    "command is a basecaller/aligner call.",
    )
    parser.add_argument("--path_to_dorado", required=True, type=Path)
    parser.add_argument(
        "--command", required=True,
        help="Either a single command string, e.g. 'basecaller hac /data/pod5 -o "
             "/tmp/out', or a path to a text file listing one or more commands (see "
             "examples/) -- whichever --command resolves to an existing file is read "
             "as a file, otherwise it's treated as a literal command string. Each "
             "command is run directly (not through a shell) -- no pipes/redirects. "
             "In a command string, omit the leading 'dorado' (only the subcommand and "
             "its arguments); in a file, 'dorado' as the first word of a command is "
             "replaced with --path_to_dorado, but may also be omitted.",
    )
    parser.add_argument(
        "--output_dir", required=True, type=Path,
        help="Where this wrapper writes its own log/manifest.json/stats.csv. Separate "
             "from wherever the (last) command's own -o/--output-dir points, if it has "
             "one -- that's dorado's actual output location, and is what gets scanned "
             "for *.bam when computing stats. Never reused -- an existing directory "
             "gets a fresh _1, _2, ... suffix, same as the other scripts.",
    )
    parser.add_argument(
        "--strict", action="store_true",
        help="Exit non-zero if the command (or, for a pipeline, any step of it) failed.",
    )
    args = parser.parse_args(argv)

    if not args.path_to_dorado.is_file():
        raise SystemExit(f"--path_to_dorado does not exist: {args.path_to_dorado}")

    command_path = Path(args.command)
    if command_path.is_file():
        args.commands = _read_command_file(command_path)
        if not args.commands:
            raise SystemExit(f"--command file has no commands in it: {command_path}")
    else:
        tokens = shlex.split(args.command)
        if not tokens:
            raise SystemExit("--command is empty")
        args.commands = [tokens]

    return args


def _read_command_file(path: Path) -> list[list[str]]:
    """One or more commands, one per (possibly multi-line) block:
    - A '\\'-terminated line continues onto the next (joined with a space);
      a command ends at the first line that doesn't end in '\\'.
    - Blank lines and '#' comment lines are ignored -- useful for visually
      separating commands and annotating a file, but not required; two
      commands on consecutive, non-continued lines are already separate.
    See examples/ for sample pipeline files."""
    commands: list[list[str]] = []
    current: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.endswith("\\"):
            current.append(line[:-1].strip())
            continue
        current.append(line)
        tokens = shlex.split(" ".join(current))
        if tokens:
            commands.append(tokens)
        current = []
    if current:  # trailing '\' continuation with no final non-continued line
        tokens = shlex.split(" ".join(current))
        if tokens:
            commands.append(tokens)
    return commands


def _resolve_dorado_token(tokens: list[str], dorado_path: str) -> list[str]:
    """tokens is a parsed command with or without a leading literal 'dorado'
    (file commands are written with it, e.g. 'dorado basecaller ...';
    inline --command strings conventionally omit it) -- either way, the
    executed command starts with the real --path_to_dorado."""
    if tokens and tokens[0] == "dorado":
        return [dorado_path, *tokens[1:]]
    return [dorado_path, *tokens]


def _extract_flag_value(tokens: list[str], flag_names: set[str]) -> str | None:
    for i, token in enumerate(tokens):
        if token in flag_names and i + 1 < len(tokens):
            return tokens[i + 1]
    return None


def _extract_basecaller_model(tokens: list[str]) -> str | None:
    """tokens = [subcommand, ...args], i.e. a resolved command with the
    dorado path already dropped. dorado basecaller <model> <data>
    [options] -- the first positional argument right after the subcommand
    itself."""
    if len(tokens) > 1 and not tokens[1].startswith("-"):
        return tokens[1]
    return None


def _static_command_builder(cmd: list[str]):
    return lambda _out_dir, _cmd=cmd: _cmd


def main(argv: list[str] | None = None) -> int:
    logger = setup_logging()
    args = parse_args(argv)
    dorado_path = str(args.path_to_dorado)

    resolved_commands = [_resolve_dorado_token(tokens, dorado_path) for tokens in args.commands]
    # Each resolved command is [dorado_path, subcommand, ...args]; index 1
    # is the subcommand throughout.
    subcommands = [cmd[1] for cmd in resolved_commands]
    test_name = "+".join(subcommands)

    dorado_version = version.get_dorado_version(dorado_path)
    logger.info("Dorado version: %s", dorado_version.raw)

    output_root = runner.resolve_output_root(args.output_dir.parent, args.output_dir.name)
    output_root.mkdir(parents=True, exist_ok=True)
    if output_root != args.output_dir:
        logger.info("%s already exists; writing this run to %s instead", args.output_dir, output_root)

    case = runner.TestCase(
        analyte="CUSTOM", library="custom", test_name=test_name,
        output_dir=output_root,
        command_builders=[_static_command_builder(cmd) for cmd in resolved_commands],
    )

    for cmd in resolved_commands:
        logger.info("Will run: %s", shlex.join(cmd))
    results = runner.run_all([case], output_root)
    result = results[0]

    manifest_path = output_root / "manifest.json"
    runner.write_manifest(results, dorado_version, dorado_path, manifest_path)
    logger.info("Manifest written to %s", manifest_path)

    last_subcommand = subcommands[-1]
    last_command = resolved_commands[-1][1:]  # drop dorado_path -> [subcommand, ...args]

    if last_subcommand not in STATS_CAPABLE_SUBCOMMANDS:
        logger.info(
            "'%s' (last step) isn't a basecaller/aligner call; log + manifest only, "
            "no stats.csv.", last_subcommand,
        )
    elif result.status != "success":
        logger.info("Command failed; skipping stats.")
    else:
        bam_dir_str = _extract_flag_value(last_command, _OUTPUT_FLAGS)
        bam_dir = Path(bam_dir_str) if bam_dir_str else output_root
        bam_paths = dorado_commands.find_output_bams(bam_dir)
        if not bam_paths:
            logger.warning("No *.bam found under %s for stats", bam_dir)
        else:
            model = _extract_basecaller_model(last_command) if last_subcommand == "basecaller" else None
            threshold_model = None
            if model:
                try:
                    stats.get_qscore_threshold(model)
                    threshold_model = model
                except ValueError:
                    logger.warning(
                        "Could not determine a qscore pass-threshold for model %r; "
                        "num_reads_passed/num_bases_passed will be blank.", model,
                    )
            try:
                row = stats.compute_bam_stats(dorado_path, bam_paths, threshold_model)
            except Exception as exc:
                logger.error("Stats computation failed (command still ran): %s", exc)
            else:
                row = {
                    "command": " && ".join(shlex.join(cmd) for cmd in resolved_commands),
                    "status": result.status,
                    "wall_time_sec": result.wall_time_sec,
                    **row,
                }
                stats_csv_path = output_root / "stats.csv"
                pd.DataFrame([row]).to_csv(stats_csv_path, index=False)
                logger.info("Stats written to %s", stats_csv_path)

    if args.strict and result.status != "success":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
