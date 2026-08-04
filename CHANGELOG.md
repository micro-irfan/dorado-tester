# Changelog

All notable changes to this project are documented in this file.

## [Unreleased]

## [1.0.0] - 2026-08-04

### Added

- `run_tests.py`: CLI entry point that runs a fixed, reproducible battery of
  Dorado basecalling tests against a given executable and writes results to
  a version-namespaced `results/<version>/` tree (never reused across runs —
  an existing folder gets a fresh `_1`, `_2`, ... suffix instead).
- Dorado version detection via `--version` (stdout + stderr captured).
- Input validation for `--path_to_dna_pod5` / `--path_to_rna_pod5` (at least
  one required): checks the `multiplex/`/`singleplex/` layout, warning
  (not failing) when only one of the two subdirectories is present.
- Full DNA + RNA test matrix:
  - Simplex `hac`/`sup` basecalling, and `hac`/`sup` + compatible modified
    bases (`config/mods.yaml`, cross-checked against `dorado download
    --list` for the target version).
  - Multiplex libraries (DNA and RNA) basecall with `--kit-name` inline,
    which auto-splits output into per-barcode `bam_pass/<barcode>/` files —
    no separate `demux` step needed.
  - Dedicated DNA multiplex barcode-kit case (`--no-trim` basecall +
    `dorado demux --kit-name`), for both `hac` and `sup`, plus a mods
    variant — excluded from the default run.
  - DNA singleplex no-trim case — excluded from the default run.
  - RNA poly(A) tail-length estimation case (`--estimate-poly-a`).
- `--ignore hac,sup`: skip a basecalling variant, or both (runs `fast`
  everywhere instead).
- `--only`, `--add_tests`, `--list_tests`: select, opt in, or discover
  individual test cases by name.
- `--rna_mod`: test extra RNA modified-base combinations as additional
  parallel cases, on top of the `config/mods.yaml` default.
- Per-case isolation — a failing case is recorded and the run continues;
  full Dorado stdout/stderr is captured to
  `results/<version>/logs/<test_name>.log` regardless.
- `manifest.json` per run: status, timing, exact commands, and error
  messages for every case.
- `dorado_tester/stats.py` + `aggregate.py`: `stats_<version>.csv` (read and
  base counts, N50, qscore stats, resolved model versions),
  `stats_<version>_per_barcode.csv` for every multiplex case, and
  `summary_all_versions.csv` across all runs.
- `download_pod5.py`: fetches sample POD5 data from `ont-open-data` into the
  layout `run_tests.py` expects.
- Centralized stderr logging (`dorado_tester/log.py`).
- `--strict`: exit non-zero if any test case failed (default: always exits
  0, so a flaky Dorado build doesn't fail CI).
