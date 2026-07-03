"""All `dorado` CLI invocations live here. Nothing outside this module should
build a `dorado` command line directly."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable


def version_command(dorado_path: str) -> list[str]:
    return [dorado_path, "--version"]


def download_list_command(dorado_path: str, models_directory: str | None = None) -> list[str]:
    cmd = [dorado_path, "download", "--list"]
    if models_directory:
        cmd += ["--models-directory", models_directory]
    return cmd


def build_model_with_mods(variant: str, mods: Iterable[str]) -> str:
    mods = list(mods)
    return ",".join([variant, *mods]) if mods else variant


def basecaller_command(
    dorado_path: str,
    model: str,
    data_dir: str,
    output_dir: str,
    *,
    kit_name: str | None = None,
    no_trim: bool = False,
    estimate_poly_a: bool = False,
    models_directory: str | None = None,
    device: str | None = None,
) -> list[str]:
    cmd = [dorado_path, "basecaller", model, data_dir, "-o", output_dir]
    if kit_name:
        cmd += ["--kit-name", kit_name]
    if no_trim:
        cmd.append("--no-trim")
    if estimate_poly_a:
        cmd.append("--estimate-poly-a")
    if models_directory:
        cmd += ["--models-directory", models_directory]
    if device:
        cmd += ["-x", device]
    return cmd


def demux_command(
    dorado_path: str,
    output_dir: str,
    bam_inputs: Iterable[str],
    *,
    no_classify: bool = True,
    kit_name: str | None = None,
) -> list[str]:
    if no_classify and kit_name:
        raise ValueError("--kit-name and --no-classify are mutually exclusive")
    cmd = [dorado_path, "demux"]
    if no_classify:
        cmd.append("--no-classify")
    if kit_name:
        cmd += ["--kit-name", kit_name]
    cmd += ["--output-dir", output_dir]
    cmd += list(bam_inputs)
    return cmd


def summary_command(dorado_path: str, bam_path: str) -> list[str]:
    return [dorado_path, "summary", bam_path]


def find_output_bams(output_dir: Path) -> list[Path]:
    """`dorado basecaller -o <dir>` does not write a flat calls_<timestamp>.bam;
    verified against v2.0.1, it mirrors the source POD5 tree (e.g.
    <dir>/<experiment_id>/<sample_id>/<run_id>/bam_pass/<flowcell>_pass_*.bam),
    with filenames that aren't predictable. Search recursively instead."""
    return sorted(output_dir.rglob("*.bam"))
