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
from .log import get_logger
from .version import DoradoVersion

CommandBuilder = Callable[[Path], list[str]]
logger = get_logger()

# Built into the matrix (so --list_tests/--only/--add_tests can still see and
# select them), but skipped from a default (no --only) run.
DEFAULT_EXCLUDED_TESTS = frozenset({"dna_singleplex_no_trim", "dna_multiplex_barcode_kit_mods"})


@dataclass
class TestCase:
    analyte: str  # "DNA" or "RNA"
    library: str  # "multiplex" or "singleplex"
    test_name: str
    output_dir: Path
    command_builders: list[CommandBuilder]
    model: str | None = None
    mods: list[str] = field(default_factory=list)
    # Dynamically-generated cases (e.g. extra --rna_mod combos) that should be
    # excluded from a default run, same as DEFAULT_EXCLUDED_TESTS, but can't be
    # listed there statically since their test_name depends on CLI input.
    default_excluded: bool = False


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


def _demux_builder(
    dorado_path: str, basecall_out_dir: Path, kit_name: str, *, no_classify: bool,
) -> CommandBuilder:
    """no_classify=False: basecalling didn't classify inline, so demux does
    the classification (needs the barcode sequence intact, i.e. basecalling
    must have used --no-trim). no_classify=True: basecalling already
    classified (and, since --no-trim wasn't used, already trimmed) inline,
    so demux only needs to split by the existing BC tag -- re-classifying
    here would fail since the barcode sequence is already gone."""
    def _build(_out_dir: Path) -> list[str]:
        demux_dir = basecall_out_dir / "demux"
        # Recursive, so on a rerun this must exclude demux/'s own prior output.
        bam_files = [
            b for b in dorado_commands.find_output_bams(basecall_out_dir)
            if demux_dir not in b.parents
        ]
        if not bam_files:
            raise FileNotFoundError(
                f"No basecaller output *.bam found under {basecall_out_dir} for demux step"
            )
        return dorado_commands.demux_command(
            dorado_path, str(demux_dir), [str(b) for b in bam_files],
            no_classify=no_classify, kit_name=None if no_classify else kit_name,
        )

    return _build


def resolve_model_variants(ignore: set[str]) -> list[str]:
    if "hac" in ignore and "sup" in ignore:
        return ["fast"]
    if "sup" in ignore:
        return ["hac"]
    if "hac" in ignore:
        return ["sup"]
    return ["hac", "sup"]


def resolve_primary_variant(ignore: set[str]) -> str:
    if "hac" in ignore and "sup" in ignore:
        return "fast"
    if "sup" in ignore:
        return "hac"
    return "sup"


def _mods_slug(mods: list[str]) -> str:
    return "+".join(mods)


def build_test_matrix(
    dorado_path: str,
    dna_pod5_dir: Path | None,
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
    ignore: set[str] = frozenset(),
    rna_mod_extra_groups: list[list[str]] = (),
) -> list[TestCase]:
    cases: list[TestCase] = []
    variants = resolve_model_variants(ignore)
    primary_variant = resolve_primary_variant(ignore)

    def _add_core_cases(
        analyte: str, library: str, lib_dir: Path, base_out: Path, mods: list[str],
        kit_name: str | None = None, extra_mod_groups: list[list[str]] = (),
    ) -> None:
        # kit_name (multiplex only): classify inline during basecalling.
        # Verified (v2.0.1): this alone already splits output into per-barcode
        # bam_pass/<barcode>/*.bam files -- no separate demux step needed (and
        # a redundant one fails: demux's positional argument is a single
        # input path, not a list of already-per-barcode bam files).
        for variant in variants:
            variant_out = base_out / f"simplex_{variant}"
            cases.append(TestCase(
                analyte=analyte, library=library, test_name=f"{analyte.lower()}_{library}_simplex_{variant}",
                output_dir=variant_out,
                command_builders=[_basecaller_builder(
                    dorado_path, variant, lib_dir, variant_out,
                    kit_name=kit_name,
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
                        kit_name=kit_name,
                        models_directory=models_directory, device=device,
                    )],
                    model=variant, mods=mods,
                ))

            # Extra combos from --rna_mod: always suffixed by mod combo (so
            # they never collide with the plain case above), and always
            # excluded from a default run -- opt in via --only/--add_tests.
            for extra_mods in extra_mod_groups:
                if not extra_mods:
                    continue
                model_with_mods = dorado_commands.build_model_with_mods(variant, extra_mods)
                slug = _mods_slug(extra_mods)
                mods_out = base_out / f"{variant}_mods_{slug}"
                cases.append(TestCase(
                    analyte=analyte, library=library,
                    test_name=f"{analyte.lower()}_{library}_{variant}_mods_{slug}",
                    output_dir=mods_out,
                    command_builders=[_basecaller_builder(
                        dorado_path, model_with_mods, lib_dir, mods_out,
                        kit_name=kit_name,
                        models_directory=models_directory, device=device,
                    )],
                    model=variant, mods=extra_mods,
                    default_excluded=True,
                ))

    if dna_pod5_dir is not None:
        for library in [l for l in ("multiplex", "singleplex") if l in dna_libraries]:
            lib_dir = dna_pod5_dir / library
            base_out = output_root / "dna" / library
            _add_core_cases(
                "DNA", library, lib_dir, base_out, dna_mods,
                kit_name=dna_kit if library == "multiplex" else None,
            )

            if library == "multiplex":
                barcode_out = base_out / "barcode_kit"
                cases.append(TestCase(
                    analyte="DNA", library=library, test_name="dna_multiplex_barcode_kit",
                    output_dir=barcode_out,
                    command_builders=[
                        _basecaller_builder(
                            dorado_path, primary_variant, lib_dir, barcode_out,
                            no_trim=True,
                            models_directory=models_directory, device=device,
                        ),
                        _demux_builder(dorado_path, barcode_out, dna_kit, no_classify=False),
                    ],
                    model=primary_variant,
                ))

                if dna_mods:
                    barcode_model_with_mods = dorado_commands.build_model_with_mods(primary_variant, dna_mods)
                    barcode_mods_out = base_out / "barcode_kit_mods"
                    cases.append(TestCase(
                        analyte="DNA", library=library, test_name="dna_multiplex_barcode_kit_mods",
                        output_dir=barcode_mods_out,
                        command_builders=[
                            _basecaller_builder(
                                dorado_path, barcode_model_with_mods, lib_dir, barcode_mods_out,
                                no_trim=True,
                                models_directory=models_directory, device=device,
                            ),
                            _demux_builder(dorado_path, barcode_mods_out, dna_kit, no_classify=False),
                        ],
                        model=primary_variant, mods=dna_mods,
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
            _add_core_cases("RNA", library, lib_dir, base_out, rna_mods, extra_mod_groups=rna_mod_extra_groups)

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
    total = len(cases)
    logger.info(
        "Running %d test case(s): %s",
        total, ", ".join(c.test_name for c in cases),
    )
    for i, case in enumerate(cases, start=1):
        logger.info(
            "[%d/%d] Running %s (%s %s, model=%s)",
            i, total, case.test_name, case.analyte, case.library, case.model,
        )
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
        if result.status == "success":
            logger.info(
                "[%d/%d] %s: success (%.1fs)", i, total, case.test_name, result.wall_time_sec,
            )
        else:
            logger.error(
                "[%d/%d] %s: failed (%.1fs) - %s",
                i, total, case.test_name, result.wall_time_sec, result.error_message,
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
