# CLAUDE.md

## Project purpose

This repository is a **version-comparison test harness for [Dorado](https://github.com/nanoporetech/dorado)**, Oxford Nanopore's basecaller. Its job is to run a fixed, reproducible battery of end-to-end basecalling tests against a *given Dorado executable*, collect basic per-run statistics, and write them into a single spreadsheet so results can be compared **across Dorado versions**.

The core workflow the user cares about:

> When a new Dorado version is released, point the harness at the new executable, re-run the same test matrix, and diff the resulting stats against previous versions.

Because the whole point is testing, **a failure in one test must never abort the run.** Every test step is isolated, its status recorded, and the harness continues.

---

## Inputs (CLI)

The main entry point is a runner (Python, see "Structure" below) that accepts:

| Argument | Required | Meaning |
|---|---|---|
| `--path_to_dorado` | yes | Path to the Dorado **executable** to test (e.g. `/opt/dorado-1.0.2/bin/dorado`). |
| `--path_to_dna_pod5` | no* | Directory of DNA POD5 input (see layout below). **If provided, DNA tests run; if omitted, they are skipped.** |
| `--path_to_rna_pod5` | no* | Directory of RNA POD5 input. **If provided, RNA tests run; if omitted, they are skipped.** |

\* At least one of `--path_to_dna_pod5` / `--path_to_rna_pod5` is required — providing neither is a config error (fail fast, not a test failure).
| `--dna_kit` | no (default configurable) | Barcode kit name for the DNA multiplex library, e.g. `SQK-NBD114-24`. |
| `--rna_kit` | no (default configurable) | Barcode kit name for the RNA multiplex library, e.g. `SQK-DRB004.24`. |
| `--output_dir` | no (default `./results`) | Where results are written. |
| `--device` | no (default `auto`) | Passed through to Dorado's `-x/--device` (`auto`, `cpu`, `cuda:all`, …). |
| `--models_directory` | no | Passed through to Dorado's `--models-directory` so model downloads are cached/shared between versions. |

### Expected input layout

Whichever POD5 path(s) are given should contain exactly two subdirectories:

```
<path_to_dna_pod5>/   # only if --path_to_dna_pod5 is given
├── multiplex/     # barcoded library (multiple barcodes pooled)
└── singleplex/    # single-sample library

<path_to_rna_pod5>/   # only if --path_to_rna_pod5 is given
├── multiplex/
└── singleplex/
```

The runner should validate these exist at startup and fail fast (before any basecalling) if the structure is wrong, or if neither path is given at all — these are config errors, not test failures. A given path missing just one of the two subdirectories is not fatal — that library's cases are skipped (warned), not the whole run.

---

## Version handling

- At startup, extract the version by running `"$DORADO" --version` and parsing the output. Store it verbatim (e.g. `1.0.2+abc1234`). Dorado prints version to stderr on some builds, so **capture both stdout and stderr**.
- Use a filesystem-safe form of the version to namespace all outputs: `results/<version>/...`. This is what makes cross-version comparison possible — each run lives in its own tree, and the aggregation step reads across them.
- Never reuse or merge into an existing `results/<version>/` — if one already exists, write to `results/<version>_1/` instead (`_2`, `_3`, ... as needed), so one invocation's manifest.json/logs can never mix with another's.
- Set `--models-directory` (or `DORADO_MODELS_DIRECTORY`) to a shared cache so different Dorado versions reuse downloaded models where compatible, avoiding re-downloading multi-GB models each run.

---

## Test matrix

Every combination below is one **test case**. Each runs in isolation and records: command, exit status, wall-clock time, output path, and (on success) parsed stats.

### DNA (only when `--path_to_dna_pod5` is given)

For **each** library in `{multiplex, singleplex}`:

1. **Simplex HAC** — `dorado basecaller hac <lib>`
2. **Simplex SUP** — `dorado basecaller sup <lib>`
3. **HAC + all compatible base mods** — `dorado basecaller hac,<mods> <lib>`
4. **SUP + all compatible base mods** — `dorado basecaller sup,<mods> <lib>`

For the **multiplex** library specifically, cases 1–4 above each get `--kit-name
<DNA_KIT>` added to the basecall (default trim applies — classification and
trimming happen together, same as ordinary inline barcoding):
```
dorado basecaller {hac|sup|hac,<mods>|sup,<mods>} <multiplex> --kit-name <DNA_KIT> -o <out>
```
No separate demux step here. Verified against v2.0.1: `--kit-name` during
basecalling on its own already splits output into per-barcode
`<out>/.../bam_pass/<barcode>/*.bam` files (and `bam_pass/unclassified/*.bam`)
— a bam_pass/barcode tree mirroring the structure MinKNOW itself uses, not
something dorado additionally needs `demux` to produce. Adding a `demux` step
here is not just redundant, it fails outright: `demux`'s positional argument
is a single input path, not a list of individual (already per-barcode) bam
files, so passing every discovered bam as a separate argument is a usage
error (dorado exits 1 and dumps its help text). This is why case 5 below
takes the opposite approach — it *needs* `demux` to do the splitting, because
its basecall step deliberately skips inline classification.

Then the dedicated barcoding-specific flows:

5. **Multiplex barcode kit** — plain basecall (no-trim, no inline classification), then classify + trim via demux:
   ```
   dorado basecaller sup <multiplex> --no-trim -o <out>
   dorado demux --kit-name <DNA_KIT> --output-dir <out>/demux <all *.bam found recursively under <out>>
   ```
   (Verified against v2.0.1: passing `--kit-name` together with `--no-trim` at the
   `basecaller` step does not produce the expected basecaller output. Classification
   is done at the `demux` step instead — `--no-classify` is only for bams that were
   already classified inline. See the bam-naming note below — the demux input bams
   have to be discovered recursively, not assumed to be `<out>/calls_*.bam`.)

   A mods variant of this case (`dna_multiplex_barcode_kit_mods`, model
   `<variant>,<mods>`, same `--no-trim` + `demux --kit-name` flow) also exists,
   but — like case 6 below — is excluded from the harness's default run (built
   into the matrix, selectable via `--only`/`--add_tests`; see README.md).
6. **Singleplex, no trim** — `dorado basecaller sup <singleplex> --no-trim` (also excluded from the harness's default run, same as case 5's mods variant above)

### RNA (only when `--path_to_rna_pod5` is given)

For **each** library in `{multiplex, singleplex}`:

1. **Simplex HAC** and **Simplex SUP** (same as DNA cases 1–2).
2. **HAC + mods** and **SUP + mods** (RNA mods differ — see below).
3. **poly(A) tail estimation** — `dorado basecaller sup <lib> --estimate-poly-a`. The estimated tail length is written to the `pt:i:` BAM tag per read.

For the **multiplex** library, all of the above (including poly(A)) get
`--kit-name <RNA_KIT>` added to the basecall, same as DNA multiplex — this
was missed initially (`rna_kit`/`--rna_kit` was accepted on the CLI but never
actually passed through to any command). No dedicated demux step here either,
for the same reason as DNA: inline `--kit-name` already splits output into
per-barcode `bam_pass/<barcode>/*.bam`.

> If the user later wants the DNA barcode/demux flow mirrored for RNA cDNA kits (PCB/PCS) — i.e. a *dedicated* case with the opposite (no-trim + demux) convention, like DNA case 5 — that's a natural extension, but it is **not** in the current spec — do not add it unless asked.

---

## Dorado command reference (verified against v1.x, output-layout notes updated against v2.0.1)

Keep the exact invocations centralised in one module (`dorado_commands.py`) so that when a new version changes a flag, there is **one** place to adjust.

- **Simplex:** `dorado basecaller {hac|sup} <data> -o <out_dir>` → does **not** write a flat `calls_<timestamp>.bam`. Verified against v2.0.1: it mirrors the source POD5 tree under `<out_dir>` (e.g. `<out_dir>/<experiment_id>/<sample_id>/<run_id>/bam_pass/<flowcell>_pass_<run_id>_<hash>_<n>.bam`), with unpredictable filenames. Always discover output bams with a recursive search (`Path(<out_dir>).rglob("*.bam")`, see `dorado_commands.find_output_bams`) — never assume a fixed filename or a flat layout.
- **Model complex + mods:** append comma-separated mod codes to the model, e.g. `dorado basecaller hac,5mCG_5hmCG,6mA <data>`. Equivalent alternative: `--modified-bases <space separated codes>`.
- **Constraint (important):** two mod models on the **same canonical base** cannot be combined (e.g. `sup,4mC_5mC,5mC` is invalid — both act on C). "All available mods" therefore means a **maximal non-conflicting set**, not literally every code.
- **Inline barcoding:** `--kit-name <KIT>` classifies during basecalling (BC tag + read group). **Do not** combine with `--no-trim` at the `basecaller` step (verified against v2.0.1: this does not produce the expected `calls_*.bam` output) — for the no-trim-then-demux flow, basecall plain with `--no-trim` and classify at the `demux` step instead.
- **Demux:** `dorado demux --output-dir <dir> <input.bam>`, with either `--kit-name <KIT>` (classify now) or `--no-classify` (reads were already classified inline during basecalling — otherwise demux re-searches, and fails on trimmed reads). `--kit-name` and `--no-classify` are mutually exclusive.
- **Summary:** `dorado summary <calls.bam> > summary.tsv` — read-level TSV including `sequence_length_template` and `mean_qscore_template`. This is the primary source for stats.
- **poly(A):** `--estimate-poly-a` on `basecaller`; result in `pt:i:` tag (read via `pysam`, not present in `dorado summary`).
- **Version:** `dorado --version`.
- **List models/mods:** `dorado download --list` — use this to *discover* which mods a given model/version actually supports rather than hard-coding assumptions.

### Configurable mod sets

Keep a config mapping (e.g. `config/mods.yaml`) of compatible mods per chemistry/speed, because available mods change between versions and models:

```yaml
dna:
  compatible_mods: ["5mCG_5hmCG", "6mA"]   # C-context + A-context, no conflict
rna:
  compatible_mods: ["m6A"]   # see note below on why pseU isn't combined by default
```

Ideally the harness cross-checks this list against `dorado download --list` for the target version and drops any mod the version doesn't offer (recording that it was skipped), so an old executable doesn't fail on a newer mod name.

**Not every mod incompatibility is a canonical-base conflict.** Verified against v2.0.1: `m6A` + `pseU` act on different canonical bases (A vs U/T) but still fail combined —
```
[error] Modbase models have different types A:conv_lstm T:conv_lstm_v3.
[error] Cannot mix the types of modified bases models
```
Mod models also carry an internal architecture "type" (here, `m6A@v1` is
`conv_lstm`, `pseU@v1` is `conv_lstm_v3`), and Dorado refuses to mix
different types regardless of canonical base. `dorado download --list`
doesn't expose this type info in a way the harness parses, so this can't be
detected automatically — it has to be discovered by trying it (as here) and
encoded into `config/mods.yaml` by hand. Use `--rna_mod` (see `run_tests.py`
CLI / README.md) to test additional RNA mod combinations — each is added as
a separate, default-excluded case rather than replacing the config default.

---

## Statistics & aggregation

A single Python program produces **one spreadsheet** (`results/<version>/stats_<version>.csv` plus a combined `results/summary_all_versions.csv`). One row per test case. For Multiplex Cases - due to the nature of output in individual barcode directory and unclassified - it is possible to print a separate csv to summarize per barcode while concatenating the bam file for combined csv with the other runs. The exact commands executed and any error messages are recorded per-case in `results/<version>/manifest.json` (not duplicated into the CSV).

Bam discovery for both the plain per-case stats and the per-barcode demux breakdown must **not** assume a fixed output depth or a flat layout — verified against v2.0.1, `dorado` output (basecaller *and* demux) mirrors the source POD5/run tree to an arbitrary depth (e.g. `.../bam_pass/<barcode>/...`), so both `dorado_commands.find_output_bams` and `stats.discover_barcode_bams` search recursively (`rglob("*.bam")`) and derive labels (barcode name, if any) from whichever path component matches, rather than a fixed directory level.

Columns per test case:

- `dorado_version`, `analyte` (DNA/RNA), `library` (multiplex/singleplex), `test_name`, `model`, `mods`
  - `model` is always the plain speed alias (`hac`/`sup`/`fast`) passed to `basecaller` — never the mods-suffixed form (`hac,5mCG_5hmCG,6mA`); the mods themselves are in the `mods` column, not concatenated into `model`.
  - `resolved_models`: the actual versioned model(s) that speed alias resolved to at runtime (e.g. `dna_r10.4.1_e8.2_400bps_hac@v6.0.0`), `;`-joined if a mods case pulled in more than one (base + each mod). Parsed from the case's log via `stats.extract_resolved_models` (looks for `downloading <model>` lines — the only place Dorado prints the resolved name). Only present when the model wasn't already cached under `--models-directory`; blank on a warm cache, since there's no other reliable line to fall back to.
- `status` (`success` / `failed`) — see `manifest.json` for the error message on failure
- `wall_time_sec` (measured around each Dorado invocation)
- `num_reads`
- `num_reads_passed` (Qscore of >9 for HAC and >12 for SUP)
- `num_bases`
- `num_bases_passed` (Qscore of >9 for HAC and >12 for SUP)
- `n50` (read-length N50)
- `read_len_mean`, `read_len_median`, `read_len_mode`, `read_len_min`, `read_len_max`
- `mean_qscore`, `median_qscore`, `qscore_min`, `qscore_max` (all of per-read `mean_qscore_template`)
- `polya_median` / `polya_mean` (RNA poly(A) cases only, from `pt:i:` tag)

Sourcing:

- Read length + qscore: parse `dorado summary` TSV with `pandas`. Do **not** re-implement BAM parsing when the summary already has the columns.
- poly(A): iterate the BAM with `pysam`, read the `pt` tag.
- Timing: wrap each subprocess call; record `time.monotonic()` deltas.

Failed test cases still get a row (with `status=failed` and NaN stats) so the comparison stays complete.

---

## Error resilience (non-negotiable)

- Each test case runs in its own try/except. A non-zero Dorado exit, a crash, or a missing output file marks that case `failed` and records the captured stderr — **the runner continues to the next case.**
- Capture and persist each Dorado command's stdout/stderr to `results/<version>/logs/<test_name>.log`.
- The overall process exits 0 even if individual cases fail (so CI/schedulers don't treat a known-flaky Dorado build as a hard failure). Optionally support `--strict` to exit non-zero if any case failed.

---

## Suggested repository structure

```
.
├── CLAUDE.md
├── README.md
├── run_tests.py            # CLI entry point (argparse), orchestrates the matrix
├── download_pod5.py        # fetches sample POD5s from ont-open-data into the expected layout
├── dorado_tester/
│   ├── __init__.py
│   ├── cli.py              # argument parsing + input validation
│   ├── version.py          # extract & normalise Dorado version
│   ├── dorado_commands.py  # ALL dorado invocations live here
│   ├── runner.py           # test-matrix construction + isolated execution
│   ├── stats.py            # summary TSV + pysam parsing -> per-run metrics
│   ├── aggregate.py        # combine into csv, build cross-version comparison
│   └── log.py              # stderr logging setup shared by run_tests.py/aggregate.py/download_pod5.py
├── config/
│   └── mods.yaml
├── results/                # gitignored; per-version output trees
└── requirements.txt        # pysam, pandas, pyyaml
└── tests/                  # to be added (expected summary file and bam)
```

---

## Conventions for working in this repo

- **Single source of truth for commands:** never inline a `dorado` call outside `dorado_commands.py`. Version-breaking flag changes should require editing one file.
- **Never let a test failure propagate** up and kill the run (except startup config validation).
- **Reproducibility:** log the exact command line executed for every case, alongside its output.
- **Don't hard-code model versions** unless the user asks to pin them; prefer variant selection (`hac`/`sup`) so Dorado picks the appropriate model for the data, and let `--models-directory` cache them.
- **Prefer `dorado summary` + `pandas`** over bespoke BAM parsing for length/qscore stats; use `pysam` only where summary lacks the field (poly(A)).
- When adding support for a **new Dorado version**, the expected change surface is: (1) confirm flags in `dorado_commands.py`, (2) refresh `config/mods.yaml` against `dorado download --list`. Nothing else should need to change.
- Keep GPU/`--device` and thread settings pass-through and configurable; don't assume CUDA is present.

## Testing Python Scripts

- There is no need to test the workflow; feedback will be passed back if any 

## Expected output For Dorado --version and download

Since there is a lot of versions, run_tests.py by default should select the latest version unless otherwise stated 

```
./dorado --version
[2026-07-02 16:34:19.777] [info] Running: "--version"
2.0.1+bf630305

./dorado download --list
[2026-07-02 16:34:54.106] [info] Running: "download" "--list"
[2026-07-02 16:34:54.106] [info] > variant models
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_hac@v5.2.0_smallvar@v1.0
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_hac@v6.0.0_smallvar@v1.0
[2026-07-02 16:34:54.106] [info] > correction models
[2026-07-02 16:34:54.106] [info]  - herro-v1
[2026-07-02 16:34:54.106] [info] > simplex models
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_fast@v4.2.0
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_hac@v4.2.0
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_sup@v4.2.0
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_fast@v4.3.0
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_hac@v4.3.0
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_sup@v4.3.0
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_fast@v5.0.0
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_hac@v5.0.0
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_sup@v5.0.0
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_apk_sup@v5.0.0
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_fast@v5.2.0
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_hac@v5.2.0
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_sup@v5.2.0
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_hac@v6.0.0
[2026-07-02 16:34:54.106] [info]  - rna004_130bps_fast@v3.0.1
[2026-07-02 16:34:54.106] [info]  - rna004_130bps_hac@v3.0.1
[2026-07-02 16:34:54.106] [info]  - rna004_130bps_sup@v3.0.1
[2026-07-02 16:34:54.106] [info]  - rna004_130bps_fast@v5.0.0
[2026-07-02 16:34:54.106] [info]  - rna004_130bps_hac@v5.0.0
[2026-07-02 16:34:54.106] [info]  - rna004_130bps_sup@v5.0.0
[2026-07-02 16:34:54.106] [info]  - rna004_130bps_fast@v5.1.0
[2026-07-02 16:34:54.106] [info]  - rna004_130bps_hac@v5.1.0
[2026-07-02 16:34:54.106] [info]  - rna004_130bps_sup@v5.1.0
[2026-07-02 16:34:54.106] [info]  - rna004_130bps_fast@v5.2.0
[2026-07-02 16:34:54.106] [info]  - rna004_130bps_hac@v5.2.0
[2026-07-02 16:34:54.106] [info]  - rna004_130bps_sup@v5.2.0
[2026-07-02 16:34:54.106] [info]  - rna004_130bps_fast@v5.3.0
[2026-07-02 16:34:54.106] [info]  - rna004_130bps_hac@v5.3.0
[2026-07-02 16:34:54.106] [info]  - rna004_130bps_sup@v5.3.0
[2026-07-02 16:34:54.106] [info]  - rna004_fast@v6.0.0
[2026-07-02 16:34:54.106] [info]  - rna004_hac@v6.0.0
[2026-07-02 16:34:54.106] [info]  - rna004_sup@v6.0.0
[2026-07-02 16:34:54.106] [info] > polish models
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_hac@v5.0.0_polish_rl
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_hac@v5.0.0_polish_rl_mv
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_sup@v5.0.0_polish_rl
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_sup@v5.0.0_polish_rl_mv
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_hac@v5.2.0_polish_rl
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_hac@v5.2.0_polish_rl_mv
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_sup@v5.2.0_polish_rl
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_sup@v5.2.0_polish_rl_mv
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_hac@v6.0.0_polish_rl
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_hac@v6.0.0_polish_rl_mv
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_polish_bacterial_methylation_v5.0.0
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_hac@v4.2.0_polish
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_sup@v4.2.0_polish
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_hac@v4.3.0_polish
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_sup@v4.3.0_polish
[2026-07-02 16:34:54.106] [info] > modification models
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_fast@v4.2.0_5mCG_5hmCG@v2
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_hac@v4.2.0_5mCG_5hmCG@v2
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_sup@v4.2.0_5mCG_5hmCG@v2
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_sup@v4.2.0_5mCG_5hmCG@v3.1
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_sup@v4.2.0_5mC@v2
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_sup@v4.2.0_6mA@v2
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_sup@v4.2.0_6mA@v3
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_sup@v4.2.0_5mC_5hmC@v1
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_hac@v4.3.0_5mC_5hmC@v1
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_sup@v4.3.0_5mC_5hmC@v1
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_hac@v4.3.0_6mA@v1
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_sup@v4.3.0_6mA@v1
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_hac@v4.3.0_6mA@v2
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_sup@v4.3.0_6mA@v2
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_hac@v4.3.0_5mCG_5hmCG@v1
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_sup@v4.3.0_5mCG_5hmCG@v1
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_hac@v5.0.0_4mC_5mC@v1
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_sup@v5.0.0_4mC_5mC@v1
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_hac@v5.0.0_4mC_5mC@v2
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_hac@v5.0.0_4mC_5mC@v3
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_sup@v5.0.0_4mC_5mC@v2
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_sup@v5.0.0_4mC_5mC@v3
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_hac@v5.0.0_5mC_5hmC@v1
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_sup@v5.0.0_5mC_5hmC@v1
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_hac@v5.0.0_5mC_5hmC@v2
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_hac@v5.0.0_5mC_5hmC@v3
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_sup@v5.0.0_5mC_5hmC@v2.0.1
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_sup@v5.0.0_5mC_5hmC@v3
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_hac@v5.0.0_5mCG_5hmCG@v1
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_sup@v5.0.0_5mCG_5hmCG@v1
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_hac@v5.0.0_5mCG_5hmCG@v2
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_hac@v5.0.0_5mCG_5hmCG@v3
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_sup@v5.0.0_5mCG_5hmCG@v2.0.1
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_sup@v5.0.0_5mCG_5hmCG@v3
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_hac@v5.0.0_6mA@v1
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_sup@v5.0.0_6mA@v1
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_hac@v5.0.0_6mA@v2
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_hac@v5.0.0_6mA@v3
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_sup@v5.0.0_6mA@v2
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_sup@v5.0.0_6mA@v3
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_hac@v5.2.0_4mC_5mC@v1
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_sup@v5.2.0_4mC_5mC@v1
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_hac@v5.2.0_5mC_5hmC@v1
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_hac@v5.2.0_5mC_5hmC@v2
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_sup@v5.2.0_5mC_5hmC@v1
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_sup@v5.2.0_5mC_5hmC@v2
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_hac@v5.2.0_5mCG_5hmCG@v1
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_hac@v5.2.0_5mCG_5hmCG@v2
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_sup@v5.2.0_5mCG_5hmCG@v1
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_sup@v5.2.0_5mCG_5hmCG@v2
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_hac@v5.2.0_6mA@v1
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_sup@v5.2.0_6mA@v1
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_hac@v6.0.0_4mC_5mC@v1
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_hac@v6.0.0_5mC_5hmC@v1
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_hac@v6.0.0_5mCG_5hmCG@v1
[2026-07-02 16:34:54.106] [info]  - dna_r10.4.1_e8.2_400bps_hac@v6.0.0_6mA@v1
[2026-07-02 16:34:54.106] [info]  - rna004_130bps_sup@v3.0.1_m6A_DRACH@v1
[2026-07-02 16:34:54.106] [info]  - rna004_130bps_hac@v5.0.0_m6A@v1
[2026-07-02 16:34:54.106] [info]  - rna004_130bps_sup@v5.0.0_m6A@v1
[2026-07-02 16:34:54.106] [info]  - rna004_130bps_hac@v5.0.0_m6A_DRACH@v1
[2026-07-02 16:34:54.106] [info]  - rna004_130bps_sup@v5.0.0_m6A_DRACH@v1
[2026-07-02 16:34:54.106] [info]  - rna004_130bps_hac@v5.0.0_pseU@v1
[2026-07-02 16:34:54.106] [info]  - rna004_130bps_sup@v5.0.0_pseU@v1
[2026-07-02 16:34:54.106] [info]  - rna004_130bps_hac@v5.1.0_m5C@v1
[2026-07-02 16:34:54.106] [info]  - rna004_130bps_sup@v5.1.0_m5C@v1
[2026-07-02 16:34:54.106] [info]  - rna004_130bps_hac@v5.1.0_inosine_m6A@v1
[2026-07-02 16:34:54.106] [info]  - rna004_130bps_sup@v5.1.0_inosine_m6A@v1
[2026-07-02 16:34:54.106] [info]  - rna004_130bps_hac@v5.1.0_m6A_DRACH@v1
[2026-07-02 16:34:54.107] [info]  - rna004_130bps_sup@v5.1.0_m6A_DRACH@v1
[2026-07-02 16:34:54.107] [info]  - rna004_130bps_hac@v5.1.0_pseU@v1
[2026-07-02 16:34:54.107] [info]  - rna004_130bps_sup@v5.1.0_pseU@v1
[2026-07-02 16:34:54.107] [info]  - rna004_130bps_sup@v5.2.0_2OmeG@v1
[2026-07-02 16:34:54.107] [info]  - rna004_130bps_hac@v5.2.0_m5C@v1
[2026-07-02 16:34:54.107] [info]  - rna004_130bps_sup@v5.2.0_m5C_2OmeC@v1
[2026-07-02 16:34:54.107] [info]  - rna004_130bps_hac@v5.2.0_inosine_m6A@v1
[2026-07-02 16:34:54.107] [info]  - rna004_130bps_sup@v5.2.0_inosine_m6A_2OmeA@v1
[2026-07-02 16:34:54.107] [info]  - rna004_130bps_hac@v5.2.0_m6A_DRACH@v1
[2026-07-02 16:34:54.107] [info]  - rna004_130bps_sup@v5.2.0_m6A_DRACH@v1
[2026-07-02 16:34:54.107] [info]  - rna004_130bps_hac@v5.2.0_pseU@v1
[2026-07-02 16:34:54.107] [info]  - rna004_130bps_sup@v5.2.0_pseU_2OmeU@v1
[2026-07-02 16:34:54.107] [info]  - rna004_130bps_sup@v5.3.0_2OmeG@v1
[2026-07-02 16:34:54.107] [info]  - rna004_130bps_hac@v5.3.0_m5C@v1
[2026-07-02 16:34:54.107] [info]  - rna004_130bps_sup@v5.3.0_m5C_2OmeC@v1
[2026-07-02 16:34:54.107] [info]  - rna004_130bps_hac@v5.3.0_inosine_m6A@v1
[2026-07-02 16:34:54.107] [info]  - rna004_130bps_sup@v5.3.0_inosine_m6A_2OmeA@v1
[2026-07-02 16:34:54.107] [info]  - rna004_130bps_hac@v5.3.0_m6A_DRACH@v1
[2026-07-02 16:34:54.107] [info]  - rna004_130bps_sup@v5.3.0_m6A_DRACH@v1
[2026-07-02 16:34:54.107] [info]  - rna004_130bps_hac@v5.3.0_pseU@v1
[2026-07-02 16:34:54.107] [info]  - rna004_130bps_sup@v5.3.0_pseU_2OmeU@v1
[2026-07-02 16:34:54.107] [info]  - rna004_sup@v6.0.0_2OmeG@v1
[2026-07-02 16:34:54.107] [info]  - rna004_hac@v6.0.0_m5C@v1
[2026-07-02 16:34:54.107] [info]  - rna004_sup@v6.0.0_m5C_2OmeC@v1
[2026-07-02 16:34:54.107] [info]  - rna004_hac@v6.0.0_inosine_m6A@v1
[2026-07-02 16:34:54.107] [info]  - rna004_sup@v6.0.0_inosine_m6A_2OmeA@v1
[2026-07-02 16:34:54.107] [info]  - rna004_hac@v6.0.0_m6A_DRACH@v1
[2026-07-02 16:34:54.107] [info]  - rna004_sup@v6.0.0_m6A_DRACH@v1
[2026-07-02 16:34:54.107] [info]  - rna004_hac@v6.0.0_pseU@v1
[2026-07-02 16:34:54.107] [info]  - rna004_sup@v6.0.0_pseU_2OmeU@v1
[2026-07-02 16:34:54.107] [info] > stereo models
[2026-07-02 16:34:54.107] [info]  - dna_r10.4.1_e8.2_5khz_stereo@v1.1
[2026-07-02 16:34:54.107] [info]  - dna_r10.4.1_e8.2_5khz_stereo@v1.2
[2026-07-02 16:34:54.107] [info]  - dna_r10.4.1_e8.2_5khz_stereo@v1.3
[2026-07-02 16:34:54.107] [info]  - dna_r10.4.1_e8.2_5khz_stereo@v1.4
[2026-07-02 16:34:54.107] [info]  - dna_r10.4.1_e8.2_5khz_stereo@v1.5

```

## Script to Prepare Pod5 Files 

A download script to download pod5 files from ont-open-data and organise them into dna/rna and multiplex/singleplex

 - Option to download X number of pod5 (default of 1 and max of 10 since this is only to test dorado's newest specs)
 - Output directory is given too 
 - check that aws is installed 
 - check that there is enough space (at least 10GB)
 - structure is what is expected in the path_to_dna_pod5 and path_to_rna_pod5 
 - Option to select for type to download --type dna,multiplex; if --type dna > it will download both multiplex and singleplex files (default download all 4)

Path to pod5 files
```
## RNA multiplex
aws s3 sync --no-sign-request s3://ont-open-data/UHRR_HG002_2026.06/raw/dRNA/HG002/DRB004_24/HG002_DRB004_24_PolyA_1/ . --exclude '*' --include 'PBM60192_598e5b4d_0120de47_1<>.pod5' where 0 for 1 pod5 file or [0-X] for multiple; eg. 2 should return [0-1]; this is similar for the rest of the dataset  

## RNA singleplex
aws s3 sync --no-sign-request s3://ont-open-data/UHRR_HG002_2026.06/raw/dRNA/HG002/RNA004/HG002_RNA004_PolyA_1/ . --exclude '*' --include 'PBE81341_30374973_a683f47a_1<>.pod5'

## DNA Singleplex 
aws s3 sync --no-sign-request s3://ont-open-data/giab_2025.01/flowcells/HG002/PAW70337/pod5/ . --exclude '*' --include 'PAW70337_66b2eea5_de8117b1_1<>.pod5'

## DNA Multiplex
aws s3 sync --no-sign-request s3://ont-open-data/pgx_as_2025.07/flowcells/cohort_1/pod5/ . --exclude '*' --include 'PBC88003_08351ad4_aada6c04_1<>.pod5'

```