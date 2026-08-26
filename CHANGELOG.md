# Changelog

All notable changes to this project are documented in this file.

## Unreleased 

### Added 

- `convert_fast5_to_pod5.py`: converts a directory of FAST5 files to POD5
  via the [`pod5`](https://pod5-file-format.readthedocs.io/) CLI
  (`pip install pod5`), for feeding older FAST5 data into `run_tests.py`/
  `run_compare_models.py` (which expect POD5, same as `download_pod5.py`'s
  output). `--input_dir`/`--output_dir` plus `--merge` (single combined
  `converted.pod5`, vs. the default one-`.pod5`-per-`.fast5` mirroring the
  input structure via `pod5`'s `--output-one-to-one`) and `--force`. The
  `pod5 convert fast5` flags it wraps are taken from `pod5`'s published
  docs, not verified against a real install in this repo the way Dorado's
  own commands are — check `pod5 convert fast5 --help` for your installed
  version if something doesn't match.

## [1.1.0] - 2026-08-17

### Added

- `run_custom_command.py`: an escape hatch for testing Dorado functionality
  that isn't (yet) built into `run_tests.py`'s or `run_compare_models.py`'s
  fixed matrices — Dorado's CLI surface evolves faster than any fixed
  matrix can track every subcommand/flag combination, so this runs
  whatever `dorado` command you give it (or a short pipeline of them).
  `--command` takes either a literal command string or a path to a text
  file listing one or more
  commands, run in sequence (stopping at the first failure) — a file
  supports `\`-continued multi-line commands, `#` comments, and a literal
  `dorado` token that gets replaced with `--path_to_dorado` (see
  `examples/` for sample pipelines). Same conventions as the other
  scripts — log file + `manifest.json` always; if the *last* command is
  `basecaller` or `aligner` and the pipeline succeeds, a best-effort
  `stats.csv` is also computed from whatever `*.bam` it produced. Any
  other last-step subcommand (`demux`, `trim`, `correct`, `smallvar`, ...)
  just gets the log + manifest, since this repo hasn't verified their
  output shape. `stats.summary_stats`/`compute_bam_stats` now accept
  `model=None` (skips the qscore pass-threshold lookup, leaving
  `num_reads_passed`/`num_bases_passed` blank rather than guessed) for an
  `aligner` case or an unrecognized `basecaller` model name.
- `run_compare_models.py`: compares specific, pinned Dorado model versions
  (not speed aliases) for one basecalling test, against a single Dorado
  executable — e.g. `dna_..._hac@v5.0.0` vs `dna_..._hac@v6.0.0`.
  `--test` picks one of the 8 `{dna,rna}_{singleplex,multiplex}_simplex_{hac,sup}`
  cases; `--models` takes 2+ full versioned model names to compare;
  `--mods` applies mod codes to every model, each resolved to its
  fully-qualified name (via `dorado download --list`) and passed through
  `--modified-bases-models`, since a bare code doesn't auto-resolve against
  an already-pinned `model@version` the way it does for a floating
  `hac`/`sup` alias. Two mod codes on the same canonical base are rejected
  upfront; a model missing some (or all) of the requested mods still runs,
  with whichever did resolve; a `--models` entry not found in the download
  catalog gets a warning but still runs, letting Dorado's own error be the
  real failure record if it truly doesn't exist. Also takes `--poly_a`,
  `--kit_name`, `--path_to_pod5`, `--device`, `--models_directory`,
  `--strict`, `--dry_run`. Reuses `run_tests.py`'s per-case isolation,
  logging, `manifest.json`, and stats CSV output; writes to
  `results_compare/<test>/<v1-v2-...>/`, never reusing an existing folder.
- `tests/test_run_compare_models.py`: `unittest`-based coverage of its
  argument parsing/validation.
- `--dry_run` (both `run_tests.py` and `run_compare_models.py`): renders
  every case's dorado command(s) without launching dorado. Still writes
  `manifest.json`/logs/stats CSV as usual, with `status: "dry_run"` and
  NaN stats. A demux command that depends on a prior basecall step's real
  output gets a placeholder instead of being treated as a failure.
  `--strict` ignores `dry_run` results.
- `--dna_mod` (`run_tests.py`): mirrors `--rna_mod`, but for DNA's
  alternate C-context mods (`4mC_5mC`, `5mC_5hmC`), added alongside the
  `config/mods.yaml` default rather than replacing it.
- `config/mods.yaml`: documented (as comments, not new defaults) two
  fuller RNA mod combos for `hac`/`sup`, verified against the
  v5.2.0–v6.0.0 catalog — see the file for the exact `--rna_mod` recipes.
- `gpu` column in `stats_<version>.csv`: the GPU(s) Dorado reported using,
  parsed from each case's log (blank on a CPU-only run).
- `polya_min`/`polya_max` alongside the existing `polya_mean`/
  `polya_median`, and `polya_tails_called`/`polya_tails_not_called`/
  `polya_avg_length_log` (Dorado's own run-level poly(A) call-rate
  summary, parsed from its log line) — distinct from the per-read
  `pt:i:`-tag-derived stats, which now exclude `pt:i:0` (uncalled) reads.
- `--species` (`download_pod5.py`, default and currently only `human`):
  `CATEGORIES` is keyed by species first, so more can be added later
  without touching the human defaults.

### Changed

- Poly(A) tail estimation is no longer a dedicated, RNA-only test case.
  `--poly_a` (both scripts) adds `--estimate-poly-a` to every case instead
  — DNA and RNA both, since it also works on cDNA, not just direct RNA —
  tracked via an explicit `TestCase.estimate_poly_a` field rather than a
  `rna_<library>_poly_a` name.
- Standardized `stats_<version>.csv` column names: `mean_qscore`/
  `median_qscore` → `qscore_mean`/`qscore_median`, and the `polya_*`
  columns reordered to mean-before-median — both now match the
  metric-name-first convention already used by `read_len_*`.

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
