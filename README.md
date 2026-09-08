# Dorado-Tester

Version-comparison test harness for [Dorado](https://github.com/nanoporetech/dorado), Oxford Nanopore's basecaller.

Point it at a Dorado executable, and it runs a fixed, reproducible battery of
end-to-end basecalling tests, logs the exact commands and their outcomes, and
namespaces results by Dorado version so runs can be diffed across releases.
A failure in one test case never aborts the run — every case is isolated and
recorded independently.

Refer [here](https://github.com/Kirk3gaard/2025-Crowdsource-GPU-basecalling-stats) to review GPU performance (Gbp/day)

See [CHANGELOG.md](CHANGELOG.md) for release history (currently v1.0.0).

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
| `--species` | Which species' dataset to pull from. Default (and currently only) `human`. |
| `--num_files`, `-n` | POD5 files per category, 1-10 (default 1). Capped at 10 since each dataset's files are only numbered with a single trailing digit — this is meant for smoke-testing a new Dorado version, not a full benchmark. |
| `--type` | Restrict which of the 4 categories to fetch: comma-separated tokens from `{dna, rna, multiplex, singleplex}`. A category downloads if *all* given tokens apply to it — `--type dna` gets both DNA multiplex and DNA singleplex; `--type dna,multiplex` gets only DNA multiplex. Default: all four. |

It requires the `aws` CLI on PATH and at least 10GB free at `--output_dir`,
and checks both before downloading anything. Each category is synced
independently (`aws s3 sync --no-sign-request ... --exclude '*' --include
'<pattern>'`) — one category failing doesn't stop the others.

### Converting FAST5 to POD5

If you're starting from older FAST5 files instead, `convert_fast5_to_pod5.py`
wraps the [`pod5`](https://pod5-file-format.readthedocs.io/) CLI (`pip
install pod5`, or `pod5[fast5]` if your platform's build needs explicit
FAST5 read support) to convert them:

```
python convert_fast5_to_pod5.py --input_dir ./fast5_data --output_dir ./pod5_data
```

| Argument | Meaning |
|---|---|
| `--input_dir` | Directory of `.fast5` files, searched recursively. |
| `--output_dir` | Where to write `.pod5` output. |
| `--merge` | Merge every input `.fast5` into a single `<output_dir>/converted.pod5`, instead of the default one `.pod5` per `.fast5` (mirroring `--input_dir`'s structure under `--output_dir`, via `pod5`'s `--output-one-to-one`) — the default is safer for a large FAST5 set than one big merged file. |
| `--force` | Overwrite existing output `.pod5` file(s). |

Unlike the `dorado` invocations elsewhere in this repo, the exact `pod5
convert fast5` flags this wraps are taken from the `pod5` project's
published docs, not verified against a real install here — if something
doesn't match, check `pod5 convert fast5 --help` for your installed
version. Whatever it writes to `--output_dir` still needs to land in the
`multiplex/`/`singleplex/` layout `run_tests.py` expects (see
[Input layout](#input-layout)) — this script doesn't do that sorting for
you.

### Extracting specific reads from POD5

`extract_reads.py` pulls a chosen set of reads out of one or more POD5
files (by read ID) and merges them into a single new POD5 file — e.g. to
build a small repro/test POD5 from a handful of interesting reads found
during basecalling, without shipping the whole source dataset:

```
python extract_reads.py \
  --pod5 ./pod5_data/dna/singleplex \
  --read_ids read_ids.txt \
  --output ./repro.pod5
```

| Argument | Required | Meaning |
|---|---|---|
| `--pod5` | yes | A single `.pod5` file, or a directory of `.pod5` files (searched recursively). |
| `--read_ids` | yes | Either a single read ID, or a path to a text file listing read IDs, one per line. |
| `--output` | yes | Path to write the merged output `.pod5` file. Refuses to overwrite an existing file — pick a different path or remove it first. |

Read IDs are validated as UUIDs and de-duplicated case-insensitively before
searching; malformed ones are skipped with a warning rather than sent to
`pod5`. Every `.pod5` file under `--pod5` is scanned (stopping early once
every requested ID has been found), and any IDs not found anywhere are
logged individually, e.g.:

```
2026-09-04 10:02:15 [WARNING] 1 read ID(s) not found:
2026-09-04 10:02:15 [WARNING]   0000173c-bf67-44e7-9a9c-1ad0bc728e74
2026-09-04 10:02:15 [INFO] 4/5 read IDs found. Output written to ./repro.pod5
```

If none of the requested IDs are found, no output file is written and the
script exits non-zero. Uses the
[`pod5`](https://pod5-file-format.readthedocs.io/) Python package's
Reader/Writer API — note `Writer.add_read()` takes a plain `Read`, not the
`ReadRecord` that `Reader.reads()` yields, so each match is converted with
`ReadRecord.to_read()` first.

### Counting reads in POD5

`count_reads.py` reports how many reads are in a `.pod5` file, or every
`.pod5` file under a directory (searched recursively):

```
python count_reads.py --pod5 ./pod5_data/dna/singleplex
```

| Argument | Required | Meaning |
|---|---|---|
| `--pod5` | yes | A single `.pod5` file, or a directory of `.pod5` files (searched recursively). |

Logs one line per file with its read count, then a final summed total:

```
2026-09-08 18:10:02 [INFO] Found 2 .pod5 file(s) under ./pod5_data/dna/singleplex
2026-09-08 18:10:02 [INFO] pod5_data/dna/singleplex/PAW70337_..._10.pod5: 4213 read(s)
2026-09-08 18:10:03 [INFO] pod5_data/dna/singleplex/PAW70337_..._11.pod5: 4187 read(s)
2026-09-08 18:10:03 [INFO] Total: 8400 read(s) across 2 file(s)
```

Uses the `pod5` Reader API's `num_reads` if the installed version exposes
it (property or method), falling back to counting via `reader.reads()`
otherwise — same not-fully-verified-against-a-real-install caveat as
`extract_reads.py` above.

## Usage

```
python run_tests.py \
  --path_to_dorado /opt/dorado-1.0.2/bin/dorado \
  --path_to_dna_pod5 /data/dna \
  --path_to_rna_pod5 /data/rna \
  --dna_kit SQK-NBD114-24 \
  --rna_kit SQK-DRB004-24 \
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
| `--rna_kit` | no | Barcode kit name for the RNA multiplex library. Default `SQK-DRB004-24`. |
| `--output_dir` | no | Where results are written. Default `./results`. |
| `--device` | no | Passed through to Dorado's `-x/--device`. Default `auto`. |
| `--models_directory` | no | Passed through to Dorado's `--models-directory` so model downloads are cached/shared between versions. |
| `--strict` | no | Exit non-zero if any test case failed (default: always exits 0). |
| `--overwrite` | no | If `results/<version>/` already exists, delete and replace it instead of writing to a fresh `results/<version>_1/`, `_2/`, ... Off by default, since one invocation's `manifest.json`/logs overwriting another's breaks the "compare across versions" premise this repo is built on. |
| `--ignore VARIANT [VARIANT ...]` | no | Skip basecalling model variant(s): `hac` and/or `sup` (space- and/or comma-separated, e.g. `--ignore sup,hac`). Ignoring one runs only the other everywhere (including downgrading the barcode-kit and no-trim cases, which default to sup). Ignoring **both** runs the `fast` variant everywhere instead. |
| `--only TEST_NAME [TEST_NAME ...]` | no | Only run these test case(s) by name; skips the rest of the matrix. Accepts space- and/or comma-separated names (`--only a,b c`). Logs, `manifest.json`, and the stats CSV are still written, scoped to just the selected case(s). |
| `--add_tests TEST_NAME [TEST_NAME ...]` | no | Also run these normally-excluded-by-default test case(s), on top of the default run (same space-/comma-separated format as `--only`). Ignored if `--only` is given. |
| `--rna_mod MODS [MODS ...]` | no | Test extra RNA mod combinations in parallel with (not instead of) the `config/mods.yaml`-derived default: `;`-separated groups, each a comma-separated set of mods combined in that one case, e.g. `--rna_mod "m6A,pseU;pseU"` adds two extra cases (m6A+pseU combined, pseU alone). Each is built into the matrix, suffixed by its mod combo, but **excluded from the default run** just like `dna_singleplex_no_trim` — select via `--only`/`--add_tests`. |
| `--dna_mod MODS [MODS ...]` | no | Same as `--rna_mod`, but for DNA, e.g. `--dna_mod "4mC_5mC,6mA;5mC_5hmC,6mA"` tests both as extra parallel cases alongside the `config/mods.yaml` default (`5mCG_5hmCG,6mA`). `4mC_5mC`, `5mC_5hmC`, and `5mCG_5hmCG` all act on the same canonical base (C) — combine at most one per group, with a non-C mod like `6mA`. |
| `--poly_a` | no | Add `--estimate-poly-a` to every basecall in the matrix — DNA and RNA both, poly(A) tail estimation isn't RNA-only, it also works on cDNA. Doesn't add or remove any test case, just changes every case's command and, correspondingly, its stats row (see `polya_*` columns below). Replaces the old dedicated `rna_<library>_poly_a` case. |
| `--list_tests` | no | Print the `test_name` of every case the current arguments would run, then exit without running anything. Use this to find the name to pass to `--only`/`--add_tests`. |
| `--dry_run` | no | Build the matrix and render every case's dorado command(s) — without launching dorado. Still writes `manifest.json` (`status: "dry_run"`, `wall_time_sec: null`) and per-case logs under `logs/` with the rendered command(s), plus the usual stats CSV (all-NaN rows, since nothing basecalled) — same downstream shape as a real run, so tooling that reads these outputs doesn't need a special case. A demux command that depends on a prior basecall step's actual output (bam file discovery) can't be fully resolved without that step having run; it's logged with a placeholder for the unresolved part rather than being skipped. |

\* At least one of `--path_to_dna_pod5` / `--path_to_rna_pod5` must be given.

`dna_singleplex_no_trim` and `dna_multiplex_barcode_kit_mods_{hac,sup}` are
built into the matrix (so `--list_tests` shows them and `--only`/`--add_tests`
can select them) but are skipped from a default run — no flag needed to
exclude them, only `--only <name>` or `--add_tests <name>` to explicitly
include one. Any extra combo added via `--rna_mod` is excluded the same way.

## What it runs

For each of `{multiplex, singleplex}`, on DNA (if `--path_to_dna_pod5` is
given) and RNA (if `--path_to_rna_pod5` is given):

- Simplex HAC and SUP basecalling
- HAC/SUP with the maximal non-conflicting set of compatible modified bases
  (configured in [config/mods.yaml](config/mods.yaml), cross-checked against
  `dorado download --list` for the target version — mods the version doesn't
  support are dropped)

For the **multiplex** library (DNA and RNA both), all of the above are
basecalled with `--kit-name` (inline classification, default trim). No
separate demux step — verified against
v2.0.1, `--kit-name` during basecalling already splits output into
per-barcode `bam_pass/<barcode>/*.bam` files on its own; a redundant
`demux` call on top of that fails (see [CLAUDE.md](CLAUDE.md) for why).

Plus, DNA-only:

- **Multiplex barcode kit** (a separate, dedicated case, run for both hac
  and sup — `dna_multiplex_barcode_kit_hac`/`_sup`): plain basecalling with
  `--no-trim` (no inline classification), followed by `dorado demux
  --kit-name` — here `demux` *is* needed, since this case's basecall step
  deliberately skips inline classification (the opposite convention from
  the cases above; see [CLAUDE.md](CLAUDE.md) for why). Same flow with mods
  (`dna_multiplex_barcode_kit_mods_hac`/`_sup`) also exists, but is excluded
  from the default run — see below.
- **Singleplex**: basecalling with `--no-trim` (`dna_singleplex_no_trim` —
  also excluded from the default run, see below)

Poly(A) tail length estimation (`--estimate-poly-a`) isn't a separate test
case — pass `--poly_a` to add it to every case in the matrix, DNA and RNA
both (see the args table above).

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
| `dna_multiplex_mods_hac` | `hac,<mods>` + `--kit-name` | Only if DNA mods available |
| `dna_multiplex_mods_sup` | `sup,<mods>` + `--kit-name` | Only if DNA mods available |
| `dna_multiplex_barcode_kit_hac` | Plain basecall `--no-trim` (no inline classify), then `dorado demux --kit-name` | Yes |
| `dna_multiplex_barcode_kit_sup` | Same, `sup` | Yes |
| `dna_multiplex_barcode_kit_mods_hac` | Same as `_hac`, with `hac,<mods>` as the model | **No** — use `--only`/`--add_tests` |
| `dna_multiplex_barcode_kit_mods_sup` | Same as `_sup`, with `sup,<mods>` as the model | **No** — use `--only`/`--add_tests` |

### DNA — singleplex (only if `--path_to_dna_pod5` given and has `singleplex/`)

| test_name | What it does | In default run? |
|---|---|---|
| `dna_singleplex_simplex_hac` | `basecaller hac` | Yes |
| `dna_singleplex_simplex_sup` | `basecaller sup` | Yes |
| `dna_singleplex_mods_hac` | `hac,<mods>` | Only if DNA mods available |
| `dna_singleplex_mods_sup` | `sup,<mods>` | Only if DNA mods available |
| `dna_singleplex_no_trim` | `basecaller --no-trim` | **No** — use `--only`/`--add_tests` |

### RNA — multiplex / singleplex (only if `--path_to_rna_pod5` given and has that library)

| test_name | What it does | In default run? |
|---|---|---|
| `rna_<library>_simplex_hac` | `basecaller hac` | Yes |
| `rna_<library>_simplex_sup` | `basecaller sup` | Yes |
| `rna_<library>_mods_hac` | `hac,<mods>` (default: `m6A` only — see below) | Only if RNA mods available |
| `rna_<library>_mods_sup` | `sup,<mods>` (default: `m6A` only — see below) | Only if RNA mods available |

(`<library>` is `multiplex` or `singleplex`. For `multiplex`, every row above
also gets `--kit-name <RNA_KIT>` on the basecall, same inline-classify-and-
auto-split behavior as DNA multiplex, no separate demux step. RNA has no
*dedicated* barcode-kit or no-trim case, though — see [CLAUDE.md](CLAUDE.md)
if you want that mirrored for RNA cDNA kits. Every row above also gets
`--estimate-poly-a` if `--poly_a` is passed, same as every DNA row.)

Two things reshape these names at runtime:

- **`--ignore`**: `hac`/`sup` in every name above only appears for whichever
  variant(s) you *haven't* ignored. If you ignore both (`--ignore sup,hac`),
  every `hac`/`sup` segment becomes `fast` instead (e.g.
  `dna_multiplex_simplex_fast`, `dna_multiplex_barcode_kit_fast`).
- **Mods-dependent cases** (`*_mods_hac`, `*_mods_sup`,
  `dna_multiplex_barcode_kit_mods_hac`/`_sup`) only exist if `config/mods.yaml` has at
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
  `--rna_mod "m6A,pseU;pseU"` adds `rna_<library>_mods_m6A+pseU_hac` and
  `rna_<library>_mods_pseU_hac` (and the `_sup` equivalents) — but like
  `dna_singleplex_no_trim`, these extras are excluded from the default run;
  use `--only`/`--add_tests` to run them. A group applies identically to
  both `hac` and `sup` (there's no per-variant targeting), so a group built
  from `hac`-only or `sup`-only mod names (see `config/mods.yaml`'s fuller
  example combos) will fail — isolated, non-fatal — for whichever variant
  doesn't have that exact mod name; run the two flavours as separate
  `--rna_mod` invocations if that matters to you.
- **`--dna_mod`**: same mechanism as `--rna_mod`, alongside (not replacing)
  `config/mods.yaml`'s DNA default (`5mCG_5hmCG,6mA`). Unlike the RNA case
  above, DNA's alternate C-context mods (`4mC_5mC`, `5mC_5hmC`) exist for
  both `hac` and `sup`, so a single group works for both variants without
  the same caveat.

## Running a single test case

To iterate on one condition without waiting on the full matrix, first list
the available names, then rerun scoped to just one (or a few):

```
python run_tests.py --path_to_dorado ... --path_to_dna_pod5 ... --list_tests
# dna_multiplex_simplex_hac
# dna_multiplex_simplex_sup
# dna_multiplex_mods_hac
# ...

python run_tests.py --path_to_dorado ... --path_to_dna_pod5 ... \
  --only dna_singleplex_no_trim
```

This still produces `logs/dna_singleplex_no_trim.log`, a `manifest.json`
containing just that case, and a `stats_<version>.csv` row for it — the same
outputs a full run would produce, just scoped down. `--only` accepts
multiple names, space- and/or comma-separated
(`--only dna_singleplex_no_trim,dna_multiplex_barcode_kit_sup`), if you want a
handful of cases instead of one.

## Logging

The harness's own operational messages — which test case is currently
running, and any warning/error (missing libraries, a failed case, stats
computation problems) — are logged to **stderr** via the standard `logging`
module (`dorado_tester/log.py`), timestamped, e.g.:

```
2026-07-03 10:02:15 [INFO] Running 6 test case(s): dna_multiplex_simplex_hac, dna_multiplex_barcode_kit_hac, ...
2026-07-03 10:02:15 [INFO] [1/6] Running dna_multiplex_simplex_hac (DNA multiplex, model=hac)
2026-07-03 10:19:52 [INFO] [1/6] dna_multiplex_simplex_hac: success (1057.3s)
2026-07-03 10:19:52 [INFO] [2/6] Running dna_multiplex_barcode_kit_hac (DNA multiplex, model=hac)
2026-07-03 10:37:10 [ERROR] [2/6] dna_multiplex_barcode_kit_hac: failed (1038.1s) - No basecaller output *.bam found under ... for demux step
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
  this can legitimately be blank on a warm cache. `gpu` is the GPU(s) Dorado
  reported using (e.g. `Quadro GV100`; `;`-joined for `--device cuda:all`
  with more than one), also parsed from the log — blank on a CPU-only run,
  since there's nothing to parse then. Plus `dorado_summary`-
  derived stats: `num_reads`/`num_bases` (+ `_passed` variants), `n50`,
  `read_len_{mean,median,mode,min,max}`, `qscore_{mean,median,min,max}`,
  plus poly(A) columns for any case run with
  `--estimate-poly-a`: `polya_mean`/`polya_median`/`polya_min`/`polya_max`
  (per-read, from the `pt:i:` BAM tag via `pysam` — reads with no `pt:i:`
  tag, or `pt:i:0` for a tail Dorado didn't call, are excluded from all
  four, so an uncalled read can't drag the mean/median/min down), and
  `polya_tails_called`/
  `polya_tails_not_called`/`polya_avg_length_log` (Dorado's own run-level
  call-rate summary, parsed from its log line, e.g. `PolyA tails called
  112832, not called 13433, avg tail length 96` — a different figure than
  `polya_mean`, since it's Dorado's own summary rather than derived from the
  tag values here). Which cases get these is tracked explicitly via
  `TestCase.estimate_poly_a` in `manifest.json`, not guessed from the test
  name, so it also works for `run_compare_models.py --poly_a` cases (named
  after the version tag, not `*_poly_a`).
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

## Comparing model versions

`run_tests.py` compares Dorado *executables* at a fixed speed alias (Dorado
picks whichever model version it thinks is best for each build).
`run_compare_models.py` instead holds the Dorado executable fixed and
compares specific, pinned **model versions** against each other — e.g. is
`dna_r10.4.1_e8.2_400bps_hac@v5.0.0` meaningfully different from
`...@v6.0.0`? Model names must be given in full (no speed-alias resolution)
— see [the model list](https://software-docs.nanoporetech.com/dorado/latest/models/list/)
or `<dorado> download --list`.

```
python run_compare_models.py \
  --path_to_dorado /opt/dorado-2.0.1/bin/dorado \
  --test dna_singleplex_simplex_hac \
  --models dna_r10.4.1_e8.2_400bps_hac@v5.2.0,dna_r10.4.1_e8.2_400bps_hac@v6.0.0 \
  --path_to_pod5 /data/dna

# with mods -- resolved per pinned model, e.g. for v5.2.0 this becomes
# --modified-bases-models dna_..._hac@v5.2.0_5mCG_5hmCG@v2,dna_..._hac@v5.2.0_6mA@v1
python run_compare_models.py \
  --path_to_dorado /opt/dorado-2.0.1/bin/dorado \
  --models dna_r10.4.1_e8.2_400bps_hac@v5.2.0,dna_r10.4.1_e8.2_400bps_hac@v6.0.0 \
  --mods 5mCG_5hmCG,6mA \
  --path_to_pod5 /data/dna
```

| Argument | Required | Meaning |
|---|---|---|
| `--path_to_dorado` | yes | Path to the Dorado executable (kept constant across the comparison). |
| `--test` | no | One of `dna_singleplex_simplex_hac`, `dna_singleplex_simplex_sup`, `dna_multiplex_simplex_hac`, `dna_multiplex_simplex_sup`, and the `rna_*` equivalents. Default `dna_singleplex_simplex_hac`. |
| `--models` | yes | 2+ full versioned model names, comma-separated. Must match `--test`'s analyte (`dna`/`rna`) and speed (`_hac@`/`_sup@`) — checked before anything runs, but this is just a name-shape check, not an existence check (e.g. `dna_..._sup@v6.0.0` looks valid but was never actually released — v6.0.0 only shipped `hac`). Each model is also checked against `dorado download --list` for this Dorado version at runtime and, if not found, a warning is logged before it runs — but it still runs; if it truly doesn't exist, Dorado itself errors when asked to fetch/load it, and that failure is recorded and the run moves on to the next model, same as any other case. |
| `--mods` | no | Comma-separated mod codes applied to every model in `--models`, e.g. `5mCG_5hmCG,6mA`. Each is resolved to the highest available fully-qualified mod model name *for that exact pinned base model* (via `dorado download --list`) and passed through `--modified-bases-models` — a bare code appended to a pinned `model@version` doesn't auto-resolve the way it does for a floating `hac`/`sup` alias, so this script does that resolution itself. A model is never skipped over mods: if only some of the requested codes resolve for that exact pinned model, it basecalls with just the ones that did (warned); if none resolve, it basecalls with no mods at all (also warned) — either way it still runs and gets a row, so the comparison stays complete across all requested versions. Two codes that look like they act on the same canonical base (e.g. `5mC_5hmC` + `5mCG_5hmCG`, both C) are rejected upfront with a clear error, before anything runs — best-effort, not exhaustive (can't catch e.g. the mod-model architecture-type conflicts noted in [CLAUDE.md](CLAUDE.md)). |
| `--path_to_pod5` | yes | Directory containing `multiplex/`/`singleplex/`, same layout as `run_tests.py`. One flag, not two — `--test` already says which analyte, so which one it needs (and validates) follows from that. |
| `--kit_name` | no | Only used if `--test` is a multiplex test (adds `--kit-name`, same as `run_tests.py`). One flag, not `--dna_kit`/`--rna_kit` — defaults to `SQK-NBD114-24` for DNA tests / `SQK-DRB004-24` for RNA tests if omitted. |
| `--poly_a` | no | Adds `--estimate-poly-a` to the basecall (poly(A) tail length in the `pt:i:` BAM tag). Works for DNA tests too, not just RNA. |
| `--output_dir` | no | Default `./results_compare`. |
| `--device`, `--models_directory`, `--strict`, `--dry_run`, `--overwrite` | no | Same meaning as `run_tests.py`. |

Output goes to `results_compare/<test>/<v1-v2-...>/` (never reused — an
existing folder gets a fresh `_1`, `_2`, ... suffix, same as `run_tests.py`,
unless `--overwrite` is given), with one subfolder + log per model version
and a `manifest.json` covering
the whole comparison. It also produces a `stats_<dorado_version>.csv` in
that same folder — one row per model version compared, via the same
`aggregate.py` used by `run_tests.py` (`stats.get_qscore_threshold` now
also recognizes a speed marker inside a full pinned model name, e.g.
`_hac@`, not just a bare `hac`/`sup`/`fast` alias). If `--test` is a
multiplex test, a `stats_<dorado_version>_per_barcode.csv` is produced too,
same as `run_tests.py`'s multiplex cases.

`tests/test_run_compare_models.py` covers its argument parsing/validation
(no real Dorado executable or POD5 data needed — stdlib `unittest`, no extra
dependency to install):

```
python tests/test_run_compare_models.py
```

## Running an arbitrary custom command

`run_tests.py` and `run_compare_models.py` both cover a fixed matrix.
`run_custom_command.py` is the escape hatch for anything outside that —
exercising a new subcommand, a one-off flag combination, or a Dorado
feature that isn't (yet) wired into either matrix, without having to add a
test case for it first.

```
python run_custom_command.py \
  --path_to_dorado /opt/dorado-2.0.1/bin/dorado \
  --command "basecaller hac /data/pod5" \
  --output_dir ./results_custom/my_run

# or a short pipeline, from a file (see examples/):
python run_custom_command.py \
  --path_to_dorado /opt/dorado-2.0.1/bin/dorado \
  --command examples/basecaller_then_trim.txt \
  --output_dir ./results_custom/basecall_then_trim
```

| Argument | Required | Meaning |
|---|---|---|
| `--path_to_dorado` | yes | Path to the Dorado executable. |
| `--command` | yes | Either a single command string, e.g. `"aligner ref.mmi reads.bam"`, or a path to a text file listing one or more commands — whichever `--command` resolves to an existing file is read as a file, otherwise it's a literal command string. Each command is run directly (not through a shell — no pipes/redirects). Any flags (`--kit-name`, `-x`, `--models-directory`, ...) belong in the string/file. A `basecaller`/`aligner`/`demux` step that doesn't specify its own `-o`/`--output-dir` gets `--output_dir` appended to it automatically (see below); everything else the wrapper leaves untouched. |
| `--output_dir` | yes | Where the wrapper writes its own `logs/<subcommand[+subcommand...]>.log`, `manifest.json`, and (if applicable) `stats.csv`. Also used as dorado's own output directory for any `basecaller`/`aligner` (`-o`) or `demux` (`--output-dir`) step in `--command` that doesn't already specify one, so the two don't need to be given separately. A step that does supply its own `-o`/`--output-dir` is left alone and that path is used instead (e.g. to send one step of a pipeline somewhere else). Never reused — an existing directory gets a fresh `_1`, `_2`, ... suffix, same as the other scripts, unless `--overwrite` is given. |
| `--strict` | no | Exit non-zero if the command (or, for a pipeline, any step of it) failed. |
| `--overwrite` | no | If `--output_dir` already exists, delete and replace it instead of writing to a fresh `_1`, `_2`, ... suffixed directory. |

### `--command` as a file

A file lists one or more commands, run in sequence as steps of a single
pipeline (stopping at the first failed step, same as e.g.
`dna_multiplex_barcode_kit`'s basecall-then-demux case in `run_tests.py`).
Rules:

- A command can span multiple lines: a line ending in `\` continues onto
  the next (joined with a space); it ends at the first line that doesn't.
  A single-line command needs no `\` at all.
- Blank lines and `#` comment lines are ignored — useful for separating
  and annotating commands, but not required; two commands on consecutive,
  non-continued lines are already treated as separate.
- The literal word `dorado` at the start of a command is replaced with
  `--path_to_dorado`'s value — write commands the way you'd normally type
  them (`dorado basecaller ...`), or omit it, either works.

See [`examples/`](examples/) for three sample two-step pipelines
(`basecaller_then_trim.txt`, `basecaller_then_correct.txt`,
`align_then_smallvar.txt`) demonstrating this syntax — their exact `trim`/
`correct`/`smallvar` flags are illustrative, not verified against a real
Dorado build (unlike `basecaller`/`aligner`, see [CLAUDE.md](CLAUDE.md)),
so check `dorado <subcommand> --help` for your version before relying on
them.

### Stats

If the **last** command in the pipeline is `basecaller` or `aligner` and
the whole pipeline exits successfully, the wrapper recursively searches
that last command's own `-o`/`--output-dir` directory — `--output_dir` by
default, or wherever it was pointed instead — for `*.bam` and writes a
one-row `stats.csv` from
them (read/base counts, N50, qscore stats — same fields as
`stats_<version>.csv`, minus the test-matrix columns). For `basecaller`,
the model is read from that command's first positional argument to pick a
qscore pass-threshold; if that's not a recognized `hac`/`sup`/`fast` name
(or the last command is `aligner`, which has no model), `num_reads_passed`/
`num_bases_passed` come back blank rather than guessing a threshold. Any
other last-step subcommand (`demux`, `duplex`, `download`, `summary`,
`trim`, `correct`, `smallvar`, ...) just gets the log + manifest — their
output shape isn't verified in this repo, so no stats are attempted.

This project is licensed under the GNU General Public License v3.0.
See [LICENSE](LICENSE) for the full text.