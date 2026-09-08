# Changelog

All notable changes to this project are documented in this file.

## Unreleased

### Added

- `extract_reads.py`: extracts reads by ID from POD5 file(s) (a single file
  or a directory, searched recursively) and merges them into one output
  POD5 — for building a small repro/test file from a handful of reads.
  `--pod5`, `--read_ids` (a single ID or a newline-delimited file),
  `--output`. Skips malformed IDs and logs any requested IDs not found,
  finishing with an `X/Y read IDs found` summary; refuses to overwrite an
  existing `--output`. Uses the `pod5` package's Reader/Writer API —
  `Writer.add_read()` takes a `Read`, not the `ReadRecord` yielded by
  `Reader.reads()`, so each match is converted via `ReadRecord.to_read()`.
- `convert_fast5_to_pod5.py`: converts a directory of FAST5 files to POD5
  via the `pod5` CLI, for feeding older data into `run_tests.py`/
  `run_compare_models.py`. `--input_dir`/`--output_dir`, `--merge` (single
  combined file vs. one-per-input default), `--force`. Flags taken from
  `pod5`'s published docs, not verified against a real install in this repo.

## [1.1.0] - 2026-08-17

### Added

- `run_custom_command.py`: escape hatch to run an arbitrary `dorado`
  command, or a short `\`-continued/`#`-commented pipeline from a file,
  outside the fixed test matrices. Best-effort `stats.csv` when the last
  step is `basecaller`/`aligner`; log + manifest always.
- `run_compare_models.py`: compares pinned Dorado **model versions** (not
  executables/speed aliases) for one test case. `--test`, `--models`
  (2+ full versioned names), `--mods` (resolved per pinned model via
  `dorado download --list`, passed through `--modified-bases-models`),
  plus `--poly_a`/`--kit_name`/`--path_to_pod5`/`--dry_run`. Reuses
  `run_tests.py`'s isolation, logging, manifest, and stats output.
- `tests/test_run_compare_models.py`: argument-parsing/validation coverage.
- `--dry_run` (both runners): renders every case's command(s) without
  launching Dorado; still writes manifest/logs/stats (NaN'd).
- `--dna_mod` (`run_tests.py`): DNA counterpart to `--rna_mod`.
- New stats columns: `gpu` (parsed from each case's log), `polya_min`/
  `polya_max`, and `polya_tails_called`/`polya_tails_not_called`/
  `polya_avg_length_log` (Dorado's own run-level poly(A) summary).
- `--species` (`download_pod5.py`, default/only `human` for now).

### Changed

- Poly(A) estimation is now a run-wide `--poly_a` flag (DNA and RNA, since
  it also works on cDNA) instead of a dedicated RNA-only test case.
- Standardized stats CSV column names (`qscore_mean`/`qscore_median`,
  `polya_*` reordered to mean-before-median).

## [1.0.0] - 2026-08-04

Initial release.

- `run_tests.py`: fixed, reproducible Dorado test matrix (DNA/RNA ×
  multiplex/singleplex × hac/sup/mods, plus dedicated barcode-kit and
  no-trim cases) against a given executable, writing version-namespaced
  `results/<version>/` output (never reused — existing runs get a `_1`,
  `_2`, ... suffix).
- Per-case isolation: a failing case is recorded, not fatal; full stdout/
  stderr captured to `logs/<test_name>.log`; `manifest.json` records
  status, timing, exact commands, and errors for every case.
- `dorado_tester/stats.py` + `aggregate.py`: `stats_<version>.csv`,
  per-barcode CSV for multiplex cases, and `summary_all_versions.csv`.
- `download_pod5.py`: fetches sample POD5 data from `ont-open-data` into
  the expected layout.
- `--ignore`, `--only`, `--add_tests`, `--list_tests`, `--rna_mod`,
  `--strict`; centralized stderr logging (`dorado_tester/log.py`).
