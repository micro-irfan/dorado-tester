# Changelog

All notable changes to this project are documented in this file.

## [Unreleased]

### Added

- `run_compare_models.py`: compares specific, pinned Dorado model versions
  (not speed aliases) for one basecalling test, against a single Dorado
  executable — e.g. `dna_..._hac@v5.0.0` vs `dna_..._hac@v6.0.0`. Takes
  `--test` (one of the 8 `{dna,rna}_{singleplex,multiplex}_simplex_{hac,sup}`
  tests), `--models` (2+ full versioned model names, comma-separated), and
  optional `--mods` (comma-separated codes applied to every model). A single
  `--path_to_pod5`/`--kit_name` (not the dual `--path_to_dna_pod5`/
  `--path_to_rna_pod5`/`--dna_kit`/`--rna_kit` of `run_tests.py`), since
  `--test` already implies the analyte. Reuses `run_tests.py`'s per-case
  isolation, logging, `manifest.json`, and `aggregate.py` stats CSV output
  (`stats.get_qscore_threshold` now also recognizes a speed marker inside a
  full pinned model name, not just a bare `hac`/`sup`/`fast` alias); writes
  to `results_compare/<test>/<v1-v2-...>/`, never reusing an existing folder
  (same `_1`/`_2` suffixing as `run_tests.py`).
  - `--mods`: verified against v2.1.0, a bare mod code appended to an
    already-pinned `model@version` doesn't resolve the way it does against a
    floating `hac`/`sup` alias (`'<code>' is not a recognised model name`,
    even for a valid, non-conflicting code). Each code is now resolved to
    its highest available fully-qualified mod model name *for that exact
    pinned base model* (via `dorado download --list`) and passed through
    `--modified-bases-models` (new `dorado_commands`/`runner.basecaller_builder`
    parameter) instead of the model-complex comma form. A model missing a
    requested mod is skipped (warned), not a hard failure. Two codes that
    look like they target the same canonical base (e.g. `5mC_5hmC` +
    `5mCG_5hmCG`, both C) are now rejected upfront with a clear error,
    before anything runs.
  - `--poly_a`: adds `--estimate-poly-a` to the basecall for that comparison
    run. Only meaningful for RNA tests (poly(A) tail length is written to
    the `pt:i:` BAM tag); ignored, with a warning, if `--test` is a DNA
    test.
- `tests/test_run_compare_models.py`: `unittest`-based coverage of
  `run_compare_models.py`'s argument parsing/validation (no real Dorado
  executable or POD5 data needed).
- `--dna_mod` (`run_tests.py`): mirrors `--rna_mod`, but for the DNA
  `*_mods_hac`/`*_mods_sup` cases — `;`-separated groups, each a
  comma-separated set of mods, added alongside (not replacing) the
  `config/mods.yaml` DNA default. Unlike RNA's `_2Ome*`-suffixed sup-only
  mods, DNA's alternates (`4mC_5mC`, `5mC_5hmC`) exist for both `hac` and
  `sup`, so one group covers both variants. `config/mods.yaml` documents the
  recipe (`--dna_mod 4mC_5mC,6mA;5mC_5hmC,6mA`) — all three C-context DNA
  mods (`4mC_5mC`, `5mC_5hmC`, `5mCG_5hmCG`) act on the same canonical base,
  so at most one per group, paired with a non-C mod like `6mA`.
- `--poly_a` (`run_compare_models.py`): adds `--estimate-poly-a` to the
  basecall for that comparison run. Only meaningful for RNA tests; ignored,
  with a warning, if `--test` is a DNA test.
- `config/mods.yaml`: documented (as comments, not new defaults) two fuller
  RNA mod combos verified present in the `dorado download --list` catalog
  at v5.2.0/v5.3.0/v6.0.0 — `m5C,m6A_DRACH,pseU` / `m5C,inosine_m6A,pseU`
  for `hac`, and the `_2OmeC`/`_2OmeU`/`2OmeG`-suffixed sup equivalents for
  `sup`. `m6A_DRACH` and `inosine_m6A(_2OmeA)` both act on adenine and can
  never be combined, and are deliberately kept as two separate options
  rather than picked for the baked-in default (`compatible_mods` stays
  `m6A` for RNA / `5mCG_5hmCG,6mA` for DNA) — test either via `--rna_mod`.
- `gpu` column in `stats_<version>.csv`: the GPU(s) Dorado reported using
  (e.g. `Quadro GV100`; `;`-joined for `--device cuda:all` with more than
  one), parsed from each case's log via `stats.extract_gpu_devices` (looks
  for `cuda:<n> - <name>` lines) — same pattern as `resolved_models`. Blank
  on a CPU-only run, since Dorado prints no such line then.

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
