"""Turns `dorado summary` TSV output and poly(A) BAM tags into per-test-case
metrics. No knowledge of the test matrix or manifest lives here; see
aggregate.py for that."""

from __future__ import annotations

import io
import re
import subprocess
from pathlib import Path

import pandas as pd
import pysam

from . import dorado_commands

# Qscore pass threshold per model speed. hac/sup are from CLAUDE.md; fast has
# no spec-defined cutoff, so it uses the value confirmed with the user.
QSCORE_THRESHOLDS = {"fast": 8.0, "hac": 9.0, "sup": 12.0}


def get_qscore_threshold(model: str) -> float:
    variant = model.split(",", 1)[0].strip().lower()
    if variant not in QSCORE_THRESHOLDS:
        raise ValueError(f"Unknown model variant for qscore threshold: {model!r}")
    return QSCORE_THRESHOLDS[variant]


def run_summary(dorado_path: str, bam_path: str) -> pd.DataFrame:
    result = subprocess.run(
        dorado_commands.summary_command(dorado_path, bam_path),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"dorado summary failed for {bam_path}: {(result.stderr or '').strip()[-2000:]}"
        )
    return pd.read_csv(io.StringIO(result.stdout), sep="\t")


def read_length_n50(lengths: pd.Series) -> float:
    sorted_lengths = sorted(lengths, reverse=True)
    total = sum(sorted_lengths)
    if total == 0:
        return float("nan")
    half = total / 2
    cumulative = 0
    for length in sorted_lengths:
        cumulative += length
        if cumulative >= half:
            return float(length)
    return float("nan")


def summary_stats(df: pd.DataFrame, qscore_threshold: float) -> dict:
    if df.empty:
        return {
            "num_reads": 0,
            "num_reads_passed": 0,
            "num_bases": 0,
            "num_bases_passed": 0,
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
        }
    lengths = df["sequence_length_template"]
    qscores = df["mean_qscore_template"]
    passed = df[qscores > qscore_threshold]
    mode = lengths.mode()
    return {
        "num_reads": int(len(df)),
        "num_reads_passed": int(len(passed)),
        "num_bases": int(lengths.sum()),
        "num_bases_passed": int(passed["sequence_length_template"].sum()),
        "n50": read_length_n50(lengths),
        "read_len_mean": float(lengths.mean()),
        "read_len_median": float(lengths.median()),
        "read_len_mode": float(mode.iloc[0]) if not mode.empty else float("nan"),
        "read_len_min": float(lengths.min()),
        "read_len_max": float(lengths.max()),
        "mean_qscore": float(qscores.mean()),
        "median_qscore": float(qscores.median()),
        "qscore_min": float(qscores.min()),
        "qscore_max": float(qscores.max()),
    }


def collect_polya_lengths(bam_paths: list[Path]) -> list[int]:
    values: list[int] = []
    for bam_path in bam_paths:
        with pysam.AlignmentFile(str(bam_path), "rb", check_sq=False) as bam:
            for read in bam:
                if read.has_tag("pt"):
                    values.append(int(read.get_tag("pt")))
    return values


def polya_stats(pt_values: list[int]) -> dict:
    if not pt_values:
        return {"polya_mean": float("nan"), "polya_median": float("nan")}
    series = pd.Series(pt_values)
    return {"polya_mean": float(series.mean()), "polya_median": float(series.median())}


def compute_bam_stats(
    dorado_path: str,
    bam_paths: list[Path],
    model: str,
    *,
    estimate_poly_a: bool = False,
) -> dict:
    dfs = [run_summary(dorado_path, str(b)) for b in bam_paths]
    combined = (
        pd.concat(dfs, ignore_index=True)
        if dfs
        else pd.DataFrame(columns=["sequence_length_template", "mean_qscore_template"])
    )
    stats = summary_stats(combined, get_qscore_threshold(model))
    if estimate_poly_a:
        stats.update(polya_stats(collect_polya_lengths(bam_paths)))
    return stats


_BARCODE_RE = re.compile(r"(barcode\d+)", re.IGNORECASE)


def _label_for_bam(bam: Path, demux_dir: Path) -> str:
    """Verified (v2.0.1): dorado output isn't flat or a fixed depth even
    outside of demux (basecaller output mirrors the source POD5 tree, e.g.
    down through a bam_pass/<barcode>/ subtree). So the barcode label isn't
    assumed to live at any particular depth -- every path component between
    demux_dir and the bam (directories and filename) is checked."""
    for part in bam.relative_to(demux_dir).parts:
        if "unclassified" in part.lower():
            return "unclassified"
        match = _BARCODE_RE.search(part)
        if match:
            return match.group(1).lower()
    return bam.stem


def discover_barcode_bams(demux_dir: Path) -> dict[str, list[Path]]:
    if not demux_dir.is_dir():
        return {}
    groups: dict[str, list[Path]] = {}
    for bam in sorted(demux_dir.rglob("*.bam")):
        label = _label_for_bam(bam, demux_dir)
        groups.setdefault(label, []).append(bam)
    return groups


# e.g. "[info]  - downloading dna_r10.4.1_e8.2_400bps_hac@v6.0.0 with httplib"
# -- hac/sup/fast resolve to a specific versioned model at runtime; this is
# the only place that resolved name is ever printed. Only present when the
# model wasn't already cached under --models-directory, so this can come up
# empty on a warm cache -- there's no other line to fall back to.
_RESOLVED_MODEL_RE = re.compile(r"downloading\s+(\S+)")


def extract_resolved_models(log_path: Path) -> list[str]:
    if not log_path.is_file():
        return []
    text = log_path.read_text(encoding="utf-8", errors="replace")
    seen: list[str] = []
    for match in _RESOLVED_MODEL_RE.finditer(text):
        model = match.group(1)
        if model not in seen:
            seen.append(model)
    return seen
