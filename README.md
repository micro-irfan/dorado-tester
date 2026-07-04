# Dorado-Tester

Version-comparison test harness for [Dorado](https://github.com/nanoporetech/dorado), Oxford Nanopore's basecaller.

Point it at a Dorado executable, and it runs a fixed, reproducible battery of
end-to-end basecalling tests, logs the exact commands and their outcomes, and
namespaces results by Dorado version so runs can be diffed across releases.
A failure in one test case never aborts the run — every case is isolated and
recorded independently.

Refer [here](https://github.com/Kirk3gaard/2025-Crowdsource-GPU-basecalling-stats) to review GPU performance (Gbp/day)

## Install Dorado and Dorado-Tester

```
curl  "https://cdn.oxfordnanoportal.com/software/analysis/dorado-2.0.1-linux-x64.tar.gz" -o dorado-2.0.1-linux-x64.tar.gz
tar -xzf dorado-2.0.1-linux-x64.tar.gz

# To check Dorado - we run a quick check 
dorado-2.0.1-linux-x64/bin/dorado --version

# To Install dorado-tester
git clone https://github.com/micro-irfan/dorado-tester.git
cd dorado-tester
pip install -r requirements.txt

```

## Input layout

At least one of `--path_to_dna_pod5` / `--path_to_rna_pod5` is required
(DNA-only, RNA-only, or both — whichever is omitted is simply skipped).
Whichever is given must contain exactly two subdirectories:

```
<path_to_dna_pod5>/
├── multiplex/     # barcoded library (multiple barcodes pooled)
└── singleplex/    # single-sample library
```

The harness validates this at startup: the path itself not existing, or
neither DNA nor RNA path being given at all, fails fast before any
basecalling runs. A path missing just one of the two subdirectories is not
fatal — that library's cases are skipped with a warning instead.

### Getting sample POD5 data

`download_pod5.py` fetches a handful of real POD5 files from the public
[ont-open-data](https://github.com/nanoporetech/ont-open-data) S3 bucket
(no AWS credentials needed) and lays them out exactly as expected above:

```
python download_pod5.py --output_dir ./pod5_data --num_files 2
# ...
# --path_to_dna_pod5 pod5_data/dna
# --path_to_rna_pod5 pod5_data/rna
```

| Argument | Meaning |
|---|---|
| `--output_dir` | Where to write `dna/{multiplex,singleplex}/` and `rna/{multiplex,singleplex}/`. Default `./pod5_data`. |
| `--num_files`, `-n` | POD5 files per category, 1-10 (default 1). Capped at 10 since each dataset's files are only numbered with a single trailing digit — this is meant for smoke-testing a new Dorado version, not a full benchmark. |
| `--type` | Restrict which of the 4 categories to fetch: comma-separated tokens from `{dna, rna, multiplex, singleplex}`. A category downloads if *all* given tokens apply to it — `--type dna` gets both DNA multiplex and DNA singleplex; `--type dna,multiplex` gets only DNA multiplex. Default: all four. |

It requires the `aws` CLI on PATH and at least 10GB free at `--output_dir`,
and checks both before downloading anything. Each category is synced
independently (`aws s3 sync --no-sign-request ... --exclude '*' --include
'<pattern>'`) — one category failing doesn't stop the others.

## Usage

```
python run_tests.py \
  --path_to_dorado /opt/dorado-1.0.2/bin/dorado \
  --path_to_dna_pod5 /data/dna \
  --path_to_rna_pod5 /data/rna \
  --dna_kit SQK-NBD114-24 \
  --rna_kit SQK-DRB004.24 \
  --output_dir ./results \
  --device auto \
  --models_directory /shared/dorado-models
```

| Argument | Required | Meaning |
|---|---|---|
| `--path_to_dorado` | yes | Path to the Dorado executable to test. |
| `--path_to_dna_pod5` | no* | Directory of DNA POD5 input (see layout above). If omitted, DNA tests are skipped. |
| `--path_to_rna_pod5` | no* | Directory of RNA POD5 input. If omitted, RNA tests are skipped. |
| `--dna_kit` | no | Barcode kit name for the DNA multiplex library. Default `SQK-NBD114-24`. |
| `--rna_kit` | no | Barcode kit name for the RNA multiplex library. Default `SQK-DRB004.24`. |
| `--output_dir` | no | Where results are written. Default `./results`. |
| `--device` | no | Passed through to Dorado's `-x/--device`. Default `auto`. |
| `--models_directory` | no | Passed through to Dorado's `--models-directory` so model downloads are cached/shared between versions. |
| `--strict` | no | Exit non-zero if any test case failed (default: always exits 0). |
| `--ignore VARIANT [VARIANT ...]` | no | Skip basecalling model variant(s): `hac` and/or `sup` (space- and/or comma-separated, e.g. `--ignore sup,hac`). Ignoring one runs only the other everywhere (including downgrading the barcode-kit, no-trim, and poly(A) cases, which default to sup). Ignoring **both** runs the `fast` variant everywhere instead. |
| `--only TEST_NAME [TEST_NAME ...]` | no | Only run these test case(s) by name; skips the rest of the matrix. Accepts space- and/or comma-separated names (`--only a,b c`). Logs, `manifest.json`, and the stats CSV are still written, scoped to just the selected case(s). |
| `--add_tests TEST_NAME [TEST_NAME ...]` | no | Also run these normally-excluded-by-default test case(s), on top of the default run (same space-/comma-separated format as `--only`). Ignored if `--only` is given. |
| `--rna_mod MODS [MODS ...]` | no | Test extra RNA mod combinations in parallel with (not instead of) the `config/mods.yaml`-derived default: `;`-separated groups, each a comma-separated set of mods combined in that one case, e.g. `--rna_mod "m6A,pseU;pseU"` adds two extra cases (m6A+pseU combined, pseU alone). Each is built into the matrix, suffixed by its mod combo, but **excluded from the default run** just like `dna_singleplex_no_trim` — select via `--only`/`--add_tests`. |
| `--list_tests` | no | Print the `test_name` of every case the current arguments would run, then exit without running anything. Use this to find the name to pass to `--only`/`--add_tests`. |

\* At least one of `--path_to_dna_pod5` / `--path_to_rna_pod5` must be given.

`dna_singleplex_no_trim` and `dna_multiplex_barcode_kit_mods` are built into
the matrix (so `--list_tests` shows them and `--only`/`--add_tests` can
select them) but are skipped from a default run — no flag needed to exclude
them, only `--only <name>` or `--add_tests <name>` to explicitly include one.
Any extra combo added via `--rna_mod` is excluded the same way.

## What it runs

For each of `{multiplex, singleplex}`, on DNA (if `--path_to_dna_pod5` is
given) and RNA (if `--path_to_rna_pod5` is given):

- Simplex HAC and SUP basecalling
- HAC/SUP with the maximal non-conflicting set of compatible modified bases
  (configured in [config/mods.yaml](config/mods.yaml), cross-checked against
  `dorado download --list` for the target version — mods the version doesn't
  support are dropped)

For the **multiplex** library (DNA and RNA both), all of the above — plus
RNA's poly(A) case — are basecalled with `--kit-name` (inline
classification, default trim). No separate demux step — verified against
v2.0.1, `--kit-name` during basecalling already splits output into
per-barcode `bam_pass/<barcode>/*.bam` files on its own; a redundant
`demux` call on top of that fails (see [CLAUDE.md](CLAUDE.md) for why).

Plus, DNA-only:

- **Multiplex barcode kit** (a separate, dedicated case): plain basecalling
  with `--no-trim` (no inline classification), followed by
  `dorado demux --kit-name` — here `demux` *is* needed, since this case's
  basecall step deliberately skips inline classification (the opposite
  convention from the cases above; see [CLAUDE.md](CLAUDE.md) for why). Same
  flow with mods (`dna_multiplex_barcode_kit_mods`, model
  `<variant>,<mods>`) also exists, but is excluded from the default run —
  see below.
- **Singleplex**: basecalling with `--no-trim` (`dna_singleplex_no_trim` —
  also excluded from the default run, see below)

And RNA-only:

- poly(A) tail length estimation (`--estimate-poly-a`)


## All possible tests

The exact set of `test_name`s built for a given invocation depends on which
POD5 paths are given, which libraries (`multiplex`/`singleplex`) are present
under them, whether any compatible mods were found, and `--ignore`. This is
the full reference — `--list_tests` shows exactly what your current
arguments produce.

### DNA — multiplex (only if `--path_to_dna_pod5` given and has `multiplex/`)

| test_name | What it does | In default run? |
|---|---|---|
| `dna_multiplex_simplex_hac` | `basecaller hac --kit-name` (auto-splits into `bam_pass/<barcode>/`) | Yes |
| `dna_multiplex_simplex_sup` | Same, `sup` | Yes |
| `dna_multiplex_hac_mods` | `hac,<mods>` + `--kit-name` | Only if DNA mods available |
| `dna_multiplex_sup_mods` | `sup,<mods>` + `--kit-name` | Only if DNA mods available |
| `dna_multiplex_barcode_kit` | Plain basecall `--no-trim` (no inline classify), then `dorado demux --kit-name` | Yes |
| `dna_multiplex_barcode_kit_mods` | Same, with `<variant>,<mods>` as the model | **No** — use `--only`/`--add_tests` |

### DNA — singleplex (only if `--path_to_dna_pod5` given and has `singleplex/`)

| test_name | What it does | In default run? |
|---|---|---|
| `dna_singleplex_simplex_hac` | `basecaller hac` | Yes |
| `dna_singleplex_simplex_sup` | `basecaller sup` | Yes |
| `dna_singleplex_hac_mods` | `hac,<mods>` | Only if DNA mods available |
| `dna_singleplex_sup_mods` | `sup,<mods>` | Only if DNA mods available |
| `dna_singleplex_no_trim` | `basecaller --no-trim` | **No** — use `--only`/`--add_tests` |

### RNA — multiplex / singleplex (only if `--path_to_rna_pod5` given and has that library)

| test_name | What it does | In default run? |
|---|---|---|
| `rna_<library>_simplex_hac` | `basecaller hac` | Yes |
| `rna_<library>_simplex_sup` | `basecaller sup` | Yes |
| `rna_<library>_hac_mods` | `hac,<mods>` (default: `m6A` only — see below) | Only if RNA mods available |
| `rna_<library>_sup_mods` | `sup,<mods>` (default: `m6A` only — see below) | Only if RNA mods available |
| `rna_<library>_poly_a` | `basecaller sup --estimate-poly-a` | Yes |

(`<library>` is `multiplex` or `singleplex`. For `multiplex`, every row above
— poly(A) included — also gets `--kit-name <RNA_KIT>` on the basecall, same
inline-classify-and-auto-split behavior as DNA multiplex, no separate demux
step. RNA has no *dedicated* barcode-kit or no-trim case, though — see
[CLAUDE.md](CLAUDE.md) if you want that mirrored for RNA cDNA kits.)

Two things reshape these names at runtime:

- **`--ignore`**: `hac`/`sup` in every name above only appears for whichever
  variant(s) you *haven't* ignored. If you ignore both (`--ignore sup,hac`),
  every `hac`/`sup` segment becomes `fast` instead (e.g.
  `dna_multiplex_simplex_fast`, `dna_multiplex_barcode_kit` still named the
  same but basecalled with `fast`).
- **Mods-dependent cases** (`*_hac_mods`, `*_sup_mods`,
  `dna_multiplex_barcode_kit_mods`) only exist if `config/mods.yaml` has at
  least one configured mod left for that analyte after cross-checking
  against the target version's `dorado download --list` output (mods it
  doesn't support are dropped) — otherwise they're omitted entirely, not
  built with an empty mods list. If `dorado download --list` itself can't be
  queried, the full configured list is used as-is (unfiltered) rather than
  omitting the cases.
- **`--rna_mod`**: `config/mods.yaml`'s RNA default is `m6A` only —
  `m6A` + `pseU` together fail on v2.0.1 (different mod-model architecture
  types, not something the harness can detect automatically; see
  [CLAUDE.md](CLAUDE.md)). Passing `--rna_mod` **adds** one extra case per
  `;`-separated group *alongside* the default `m6A` case (it doesn't
  replace it), each suffixed with its mod combo, e.g.
  `--rna_mod "m6A,pseU;pseU"` adds `rna_<library>_hac_mods_m6A+pseU` and
  `rna_<library>_hac_mods_pseU` (and the `sup_mods` equivalents) — but like
  `dna_singleplex_no_trim`, these extras are excluded from the default run;
  use `--only`/`--add_tests` to run them.

## Running a single test case

To iterate on one condition without waiting on the full matrix, first list
the available names, then rerun scoped to just one (or a few):

```
python run_tests.py --path_to_dorado ... --path_to_dna_pod5 ... --list_tests
# dna_multiplex_simplex_hac
# dna_multiplex_simplex_sup
# dna_multiplex_hac_mods
# ...

python run_tests.py --path_to_dorado ... --path_to_dna_pod5 ... \
  --only dna_singleplex_no_trim
```

This still produces `logs/dna_singleplex_no_trim.log`, a `manifest.json`
containing just that case, and a `stats_<version>.csv` row for it — the same
outputs a full run would produce, just scoped down. `--only` accepts
multiple names, space- and/or comma-separated
(`--only dna_singleplex_no_trim,dna_multiplex_barcode_kit`), if you want a
handful of cases instead of one.

## Logging

The harness's own operational messages — which test case is currently
running, and any warning/error (missing libraries, a failed case, stats
computation problems) — are logged to **stderr** via the standard `logging`
module (`dorado_tester/log.py`), timestamped, e.g.:

```
2026-07-03 10:02:15 [INFO] Running 6 test case(s): dna_multiplex_simplex_hac, dna_multiplex_barcode_kit, ...
2026-07-03 10:02:15 [INFO] [1/6] Running dna_multiplex_simplex_hac (DNA multiplex, model=hac)
2026-07-03 10:19:52 [INFO] [1/6] dna_multiplex_simplex_hac: success (1057.3s)
2026-07-03 10:19:52 [INFO] [2/6] Running dna_multiplex_barcode_kit (DNA multiplex, model=hac)
2026-07-03 10:37:10 [ERROR] [2/6] dna_multiplex_barcode_kit: failed (1038.1s) - No basecaller output *.bam found under ... for demux step
```

This is separate from each case's raw Dorado stdout/stderr, which is always
captured in full to `results/<version>/logs/<test_name>.log` regardless of
log level. `--list_tests` output (the plain list of test names) goes to
stdout, not through the logger, so it stays easy to pipe/parse on its own.

## Output

Results are namespaced by Dorado version under `results/<version>/`:

```
results/<version>/
├── logs/<test_name>.log   # full stdout/stderr per test case
├── manifest.json          # per-case status, timing, commands, output paths
├── dna/<library>/<test>/  # basecaller/demux output
└── rna/<library>/<test>/
```

If `results/<version>/` already exists from an earlier run, a fresh run
never reuses or merges into it — it writes to `results/<version>_1/`
instead (`_2`, `_3`, ... if those exist too), so one run's manifest/logs can
never get mixed with another's.

Dorado does not write a flat `calls_<timestamp>.bam` into `<test>/` —
it mirrors the source POD5 tree (e.g.
`<test>/<experiment_id>/<sample_id>/<run_id>/bam_pass/<flowcell>_pass_*.bam`),
so bam discovery (`dorado_commands.find_output_bams`) searches recursively
rather than assuming a filename or a flat layout.

`manifest.json` is the handoff point for stats/aggregation: it records
`status`, `error_message`, `wall_time_sec`, `commands_executed`, and
`output_dir` for every case, whether it succeeded or failed.

## Stats & aggregation

`run_tests.py` runs the full matrix and, at the end, automatically calls into
`dorado_tester/stats.py` and `dorado_tester/aggregate.py` to produce:

- `results/<version>/stats_<version>.csv` — one row per test case. `model`
  is always the plain speed (`hac`/`sup`/`fast`) — the mods used for a
  `*_mods` case are in the `mods` column instead, not concatenated into
  `model`. `resolved_models` is the actual versioned model(s) Dorado picked
  for that speed alias (e.g. `dna_r10.4.1_e8.2_400bps_hac@v6.0.0`; `;`-joined
  if a mods case pulled in more than one, one per mod), parsed from that
  case's log — only present when Dorado had to download the model fresh
  (nothing to parse if it was already cached under `--models_directory`), so
  this can legitimately be blank on a warm cache. Plus `dorado_summary`-
  derived stats: `num_reads`/`num_bases` (+ `_passed` variants), `n50`,
  `read_len_{mean,median,mode,min,max}`, `{mean,median}_qscore`,
  `qscore_{min,max}`, plus poly(A) median/mean for the RNA poly(A) case.
  A read counts as "passed" if its `mean_qscore_template` is above 9 (hac),
  12 (sup), or 8 (fast, only relevant when `--ignore` drops both hac and sup).
- `results/<version>/stats_<version>_per_barcode.csv` — per-barcode breakdown
  for every multiplex case, DNA and RNA both (the core cases, which classify
  inline via `--kit-name`, plus DNA's dedicated barcode-kit case, which
  classifies via `demux`), one row per barcode per case; the combined row
  for that case in the main CSV concatenates all of its barcodes together.
  Bam discovery here is recursive and depth-agnostic (see the note above
  under Output) — barcode labels are read from whichever path component
  (directory or filename) matches `barcodeNN`/`unclassified`.
- `results/summary_all_versions.csv` — every version's `stats_<version>.csv`
  concatenated, for cross-version comparison.

The CSVs deliberately omit `error_message` and `commands_executed` — those
are already in `manifest.json` per case, keyed by `test_name`. (A stats
computation failure that happens after a case already succeeded, e.g. a
missing BAM, is printed as a warning to stderr rather than added as a CSV
column.)

Stats aggregation failing does not affect the underlying test run — it's a
post-processing step over `manifest.json` and the produced BAMs, and can be
re-run standalone:

```
python -m dorado_tester.aggregate --output_dir ./results
```

This project is licensed under the GNU General Public License v3.0.
See [LICENSE](LICENSE) for the full text.