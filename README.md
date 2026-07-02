# dorado-tester

Version-comparison test harness for [Dorado](https://github.com/nanoporetech/dorado), Oxford Nanopore's basecaller.

Point it at a Dorado executable, and it runs a fixed, reproducible battery of
end-to-end basecalling tests, logs the exact commands and their outcomes, and
namespaces results by Dorado version so runs can be diffed across releases.
A failure in one test case never aborts the run — every case is isolated and
recorded independently.

Refer [here](https://github.com/Kirk3gaard/2025-Crowdsource-GPU-basecalling-stats) to review GPU performance (Gbp/day)

## Install

```
pip install -r requirements.txt
```

## Input layout

Both `--path_to_dna_pod5` and (if given) `--path_to_rna_pod5` must each
contain exactly two subdirectories:

```
<path_to_dna_pod5>/
├── multiplex/     # barcoded library (multiple barcodes pooled)
└── singleplex/    # single-sample library
```

The harness validates this at startup and fails fast if the structure is
wrong, before any basecalling runs.

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
| `--path_to_dna_pod5` | yes | Directory of DNA POD5 input (see layout above). |
| `--path_to_rna_pod5` | no | Directory of RNA POD5 input. If omitted, RNA tests are skipped. |
| `--dna_kit` | no | Barcode kit name for the DNA multiplex library. Default `SQK-NBD114-24`. |
| `--rna_kit` | no | Barcode kit name for the RNA multiplex library. Default `SQK-DRB004.24`. |
| `--output_dir` | no | Where results are written. Default `./results`. |
| `--device` | no | Passed through to Dorado's `-x/--device`. Default `auto`. |
| `--models_directory` | no | Passed through to Dorado's `--models-directory` so model downloads are cached/shared between versions. |
| `--strict` | no | Exit non-zero if any test case failed (default: always exits 0). |
| `--ignore_sup` | no | Only run hac-variant test cases (skips sup) to save time. Also downgrades the barcode-kit, no-trim, and poly(A) cases (normally sup) to hac. |
| `--test_fast` | no | Run the `fast` model variant instead of hac/sup (including the barcode-kit, no-trim, and poly(A) cases). Overrides `--ignore_sup`. |

## What it runs

For each of `{multiplex, singleplex}`, on DNA (always) and RNA (if
`--path_to_rna_pod5` is given):

- Simplex HAC and SUP basecalling
- HAC/SUP with the maximal non-conflicting set of compatible modified bases
  (configured in [config/mods.yaml](config/mods.yaml), cross-checked against
  `dorado download --list` for the target version — mods the version doesn't
  support are dropped)

Plus, DNA-only:

- **Multiplex**: inline barcode classification (`--kit-name`, `--no-trim`)
  followed by `dorado demux --no-classify`
- **Singleplex**: basecalling with `--no-trim`

And RNA-only:

- poly(A) tail length estimation (`--estimate-poly-a`)

See [CLAUDE.md](CLAUDE.md) for the full spec this harness implements.

## Output

Results are namespaced by Dorado version under `results/<version>/`:

```
results/<version>/
├── logs/<test_name>.log   # full stdout/stderr per test case
├── manifest.json          # per-case status, timing, commands, output paths
├── dna/<library>/<test>/  # basecaller/demux output (BAMs, etc.)
└── rna/<library>/<test>/
```

`manifest.json` is the handoff point for stats/aggregation: it records
`status`, `error_message`, `wall_time_sec`, `commands_executed`, and
`output_dir` for every case, whether it succeeded or failed.

## Stats & aggregation

`run_tests.py` runs the full matrix and, at the end, automatically calls into
`dorado_tester/stats.py` and `dorado_tester/aggregate.py` to produce:

- `results/<version>/stats_<version>.csv` — one row per test case (`dorado_summary`-
  derived read/base/N50/qscore stats, plus poly(A) median/mean for the RNA
  poly(A) case). A read counts as "passed" if its `mean_qscore_template` is
  above 9 (hac), 12 (sup), or 8 (fast, only relevant with `--test_fast`).
- `results/<version>/stats_<version>_per_barcode.csv` — per-barcode breakdown
  for the DNA multiplex barcode-kit case (each barcode's demuxed BAM summarized
  separately; the combined row in the main CSV concatenates all of them).
- `results/summary_all_versions.csv` — every version's `stats_<version>.csv`
  concatenated, for cross-version comparison.

Stats aggregation failing does not affect the underlying test run — it's a
post-processing step over `manifest.json` and the produced BAMs, and can be
re-run standalone:

```
python -m dorado_tester.aggregate --output_dir ./results
```

This project is licensed under the GNU General Public License v3.0.
See [LICENSE]() for the full text.