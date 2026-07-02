from __future__ import annotations

import json
import shlex
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import yaml

from . import dorado_commands
from .version import DoradoVersion

CommandBuilder = Callable[[Path], list[str]]


@dataclass
class TestCase:
    analyte: str  # "DNA" or "RNA"
    library: str  # "multiplex" or "singleplex"
    test_name: str
    output_dir: Path
    command_builders: list[CommandBuilder]
    model: str | None = None
    mods: list[str] = field(default_factory=list)


@dataclass
class TestResult:
    case: TestCase
    status: str  # "success" or "failed"
    error_message: str | None
    wall_time_sec: float
    commands_executed: list[str]
    log_path: Path


# --- mod discovery -----------------------------------------------------

def load_mods_config(path: Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def get_available_mods_output(dorado_path: str, models_directory: Path | None) -> str | None:
    cmd = dorado_commands.download_list_command(
        dorado_path, str(models_directory) if models_directory else None
    )
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return (result.stdout or "") + (result.stderr or "")


def resolve_compatible_mods(configured_mods: list[str], available_output: str | None) -> list[str]:
    if not available_output:
        return list(configured_mods)
    return [m for m in configured_mods if m in available_output]


# --- test matrix construction -------------------------------------------

def _basecaller_builder(
    dorado_path: str,
    model: str,
    data_dir: Path,
    out_dir: Path,
    *,
    kit_name: str | None = None,
    no_trim: bool = False,
    estimate_poly_a: bool = False,
    models_directory: Path | None = None,
    device: str | None = None,
) -> CommandBuilder:
    def _build(_out_dir: Path) -> list[str]:
        return dorado_commands.basecaller_command(
            dorado_path,
            model,
            str(data_dir),
            str(out_dir),
            kit_name=kit_name,
            no_trim=no_trim,
            estimate_poly_a=estimate_poly_a,
            models_directory=str(models_directory) if models_directory else None,
            device=device,
        )

    return _build


def _demux_builder(dorado_path: str, basecall_out_dir: Path) -> CommandBuilder:
    def _build(_out_dir: Path) -> list[str]:
        bam_files = dorado_commands.find_calls_bams(basecall_out_dir)
        if not bam_files:
            raise FileNotFoundError(
                f"No calls_*.bam found in {basecall_out_dir} for demux step"
            )
        demux_dir = basecall_out_dir / "demux"
        return dorado_commands.demux_command(
            dorado_path, str(demux_dir), [str(b) for b in bam_files]
        )

    return _build


def resolve_model_variants(ignore_sup: bool, test_fast: bool) -> list[str]:
    if test_fast:
        return ["fast"]
    if ignore_sup:
        return ["hac"]
    return ["hac", "sup"]


def resolve_primary_variant(ignore_sup: bool, test_fast: bool) -> str:
    if test_fast:
        return "fast"
    if ignore_sup:
        return "hac"
    return "sup"


def build_test_matrix(
    dorado_path: str,
    dna_pod5_dir: Path,
    rna_pod5_dir: Path | None,
    dna_kit: str,
    rna_kit: str,
    output_root: Path,
    models_directory: Path | None,
    device: str,
    dna_mods: list[str],
    rna_mods: list[str],
    dna_libraries: set[str],
    rna_libraries: set[str],
    ignore_sup: bool = False,
    test_fast: bool = False,
) -> list[TestCase]:
    cases: list[TestCase] = []
    variants = resolve_model_variants(ignore_sup, test_fast)
    primary_variant = resolve_primary_variant(ignore_sup, test_fast)

    def _add_core_cases(analyte: str, library: str, lib_dir: Path, base_out: Path, mods: list[str]) -> None:
        for variant in variants:
            variant_out = base_out / f"simplex_{variant}"
            cases.append(TestCase(
                analyte=analyte, library=library, test_name=f"{analyte.lower()}_{library}_simplex_{variant}",
                output_dir=variant_out,
                command_builders=[_basecaller_builder(
                    dorado_path, variant, lib_dir, variant_out,
                    models_directory=models_directory, device=device,
                )],
                model=variant,
            ))

            if mods:
                model_with_mods = dorado_commands.build_model_with_mods(variant, mods)
                mods_out = base_out / f"{variant}_mods"
                cases.append(TestCase(
                    analyte=analyte, library=library, test_name=f"{analyte.lower()}_{library}_{variant}_mods",
                    output_dir=mods_out,
                    command_builders=[_basecaller_builder(
                        dorado_path, model_with_mods, lib_dir, mods_out,
                        models_directory=models_directory, device=device,
                    )],
                    model=model_with_mods, mods=mods,
                ))

    for library in [l for l in ("multiplex", "singleplex") if l in dna_libraries]:
        lib_dir = dna_pod5_dir / library
        base_out = output_root / "dna" / library
        _add_core_cases("DNA", library, lib_dir, base_out, dna_mods)

        if library == "multiplex":
            barcode_out = base_out / "barcode_kit"
            cases.append(TestCase(
                analyte="DNA", library=library, test_name="dna_multiplex_barcode_kit",
                output_dir=barcode_out,
                command_builders=[
                    _basecaller_builder(
                        dorado_path, primary_variant, lib_dir, barcode_out,
                        kit_name=dna_kit, no_trim=True,
                        models_directory=models_directory, device=device,
                    ),
                    _demux_builder(dorado_path, barcode_out),
                ],
                model=primary_variant,
            ))
        else:
            no_trim_out = base_out / "no_trim"
            cases.append(TestCase(
                analyte="DNA", library=library, test_name="dna_singleplex_no_trim",
                output_dir=no_trim_out,
                command_builders=[_basecaller_builder(
                    dorado_path, primary_variant, lib_dir, no_trim_out, no_trim=True,
                    models_directory=models_directory, device=device,
                )],
                model=primary_variant,
            ))

    if rna_pod5_dir is not None:
        for library in [l for l in ("multiplex", "singleplex") if l in rna_libraries]:
            lib_dir = rna_pod5_dir / library
            base_out = output_root / "rna" / library
            _add_core_cases("RNA", library, lib_dir, base_out, rna_mods)

            poly_a_out = base_out / "poly_a"
            cases.append(TestCase(
                analyte="RNA", library=library, test_name=f"rna_{library}_poly_a",
                output_dir=poly_a_out,
                command_builders=[_basecaller_builder(
                    dorado_path, primary_variant, lib_dir, poly_a_out, estimate_poly_a=True,
                    models_directory=models_directory, device=device,
                )],
                model=primary_variant,
            ))

    return cases


# --- execution ------------------------------------------------------------

def execute_case(case: TestCase, logs_dir: Path) -> TestResult:
    logs_dir.mkdir(parents=True, exist_ok=True)
    case.output_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / f"{case.test_name}.log"

    rendered_commands: list[str] = []
    status = "success"
    error_message: str | None = None

    start = time.monotonic()
    with open(log_path, "w", encoding="utf-8") as log_fh:
        for builder in case.command_builders:
            try:
                cmd = builder(case.output_dir)
            except FileNotFoundError as exc:
                status = "failed"
                error_message = str(exc)
                log_fh.write(f"{error_message}\n")
                break

            rendered = shlex.join(cmd)
            rendered_commands.append(rendered)
            log_fh.write(f"$ {rendered}\n")
            log_fh.flush()

            try:
                result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            except OSError as exc:
                status = "failed"
                error_message = f"Failed to launch command: {exc}"
                log_fh.write(f"{error_message}\n")
                break

            log_fh.write(result.stdout or "")
            log_fh.write(result.stderr or "")
            log_fh.flush()

            if result.returncode != 0:
                status = "failed"
                error_message = (
                    f"Command exited with status {result.returncode}: {rendered}\n"
                    f"{(result.stderr or '').strip()[-2000:]}"
                )
                break
    wall_time_sec = time.monotonic() - start

    return TestResult(
        case=case,
        status=status,
        error_message=error_message,
        wall_time_sec=wall_time_sec,
        commands_executed=rendered_commands,
        log_path=log_path,
    )


def run_all(cases: list[TestCase], output_root: Path) -> list[TestResult]:
    logs_dir = output_root / "logs"
    results: list[TestResult] = []
    for case in cases:
        try:
            result = execute_case(case, logs_dir)
        except Exception as exc:  # a test case must never abort the run
            result = TestResult(
                case=case,
                status="failed",
                error_message=f"Unhandled exception: {exc}",
                wall_time_sec=0.0,
                commands_executed=[],
                log_path=logs_dir / f"{case.test_name}.log",
            )
        results.append(result)
    return results


def write_manifest(
    results: list[TestResult], dorado_version: DoradoVersion, dorado_path: str, path: Path
) -> None:
    payload = {
        "dorado_path": dorado_path,
        "dorado_version": dorado_version.raw,
        "dorado_version_safe": dorado_version.safe,
        "cases": [
            {
                "analyte": r.case.analyte,
                "library": r.case.library,
                "test_name": r.case.test_name,
                "model": r.case.model,
                "mods": r.case.mods,
                "output_dir": str(r.case.output_dir),
                "status": r.status,
                "error_message": r.error_message,
                "wall_time_sec": r.wall_time_sec,
                "commands_executed": r.commands_executed,
                "log_path": str(r.log_path),
            }
            for r in results
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
