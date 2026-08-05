"""CLI/validation tests for run_compare_models.py.

Covers argument parsing and validation only (no real Dorado executable or
POD5 data needed) -- everything that touches an actual `dorado` invocation
(main()'s basecalling) is out of scope here.

Run with:
    python tests/test_run_compare_models.py
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import run_compare_models as rcm


class SplitListTests(unittest.TestCase):
    def test_none_returns_empty(self):
        self.assertEqual(rcm._split_list(None), [])

    def test_empty_string_returns_empty(self):
        self.assertEqual(rcm._split_list(""), [])

    def test_splits_and_strips_whitespace(self):
        self.assertEqual(rcm._split_list(" a , b ,c "), ["a", "b", "c"])

    def test_trailing_comma_ignored(self):
        self.assertEqual(rcm._split_list("a,b,"), ["a", "b"])


class VersionTagTests(unittest.TestCase):
    def test_extracts_tag_after_at(self):
        self.assertEqual(rcm._version_tag("dna_r10.4.1_e8.2_400bps_hac@v6.0.0"), "v6.0.0")

    def test_uses_last_at_when_model_has_more_than_one(self):
        self.assertEqual(rcm._version_tag("rna004_130bps_hac@v5.0.0_m6A@v1"), "v1")


class ValidateModelsTests(unittest.TestCase):
    def test_valid_dna_hac_models_pass(self):
        rcm._validate_models(
            ["dna_r10.4.1_e8.2_400bps_hac@v5.2.0", "dna_r10.4.1_e8.2_400bps_hac@v6.0.0"],
            "DNA", "hac",
        )  # no exception = pass

    def test_valid_rna_sup_models_pass(self):
        rcm._validate_models(
            ["rna004_sup@v6.0.0", "rna004_130bps_sup@v5.0.0"],
            "RNA", "sup",
        )

    def test_wrong_analyte_rejected(self):
        with self.assertRaises(SystemExit):
            rcm._validate_models(["rna004_hac@v6.0.0"], "DNA", "hac")

    def test_wrong_speed_rejected(self):
        with self.assertRaises(SystemExit):
            rcm._validate_models(["dna_r10.4.1_e8.2_400bps_sup@v6.0.0"], "DNA", "hac")

    def test_one_bad_model_among_good_ones_rejects_whole_list(self):
        with self.assertRaises(SystemExit):
            rcm._validate_models(
                [
                    "dna_r10.4.1_e8.2_400bps_hac@v6.0.0",
                    "dna_r10.4.1_e8.2_400bps_sup@v6.0.0",
                ],
                "DNA", "hac",
            )


class TestSpecsTests(unittest.TestCase):
    def test_all_eight_combinations_present(self):
        expected = {
            f"{analyte}_{library}_simplex_{speed}"
            for analyte in ("dna", "rna")
            for library in ("singleplex", "multiplex")
            for speed in ("hac", "sup")
        }
        self.assertEqual(set(rcm.TEST_SPECS), expected)

    def test_spec_tuple_matches_its_own_name(self):
        for name, (analyte, library, speed) in rcm.TEST_SPECS.items():
            self.assertTrue(name.startswith(analyte.lower()))
            self.assertIn(library, name)
            self.assertTrue(name.endswith(speed))

    def test_default_kit_names_cover_both_analytes(self):
        self.assertEqual(rcm.DEFAULT_KIT_NAMES["DNA"], "SQK-NBD114-24")
        self.assertEqual(rcm.DEFAULT_KIT_NAMES["RNA"], "SQK-DRB004-24")


class ParseArgsTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp_path = Path(tmp.name)

        self.dorado_path = self.tmp_path / "dorado"
        self.dorado_path.write_text("fake")

        self.pod5_root = self.tmp_path / "pod5"
        (self.pod5_root / "singleplex").mkdir(parents=True)
        (self.pod5_root / "multiplex").mkdir(parents=True)

        self.dna_hac_models = [
            "dna_r10.4.1_e8.2_400bps_hac@v5.2.0",
            "dna_r10.4.1_e8.2_400bps_hac@v6.0.0",
        ]

    def _argv(self, *, dorado=None, pod5=None, models=None, test=None, extra=None):
        argv = [
            "--path_to_dorado", str(dorado if dorado is not None else self.dorado_path),
            "--path_to_pod5", str(pod5 if pod5 is not None else self.pod5_root),
            "--models", ",".join(models if models is not None else self.dna_hac_models),
        ]
        if test is not None:
            argv += ["--test", test]
        if extra:
            argv += extra
        return argv

    def test_valid_default_test_parses(self):
        args = rcm.parse_args(self._argv())
        self.assertEqual(args.test, "dna_singleplex_simplex_hac")
        self.assertEqual(args.models, self.dna_hac_models)
        self.assertEqual(args.mods, [])

    def test_kit_name_defaults_to_none_until_main_resolves_it(self):
        # main() applies DEFAULT_KIT_NAMES; parse_args itself leaves it unset
        # so --kit_name's absence is distinguishable from an explicit value.
        args = rcm.parse_args(self._argv(test="dna_multiplex_simplex_hac"))
        self.assertIsNone(args.kit_name)

    def test_mods_are_split_and_not_validated(self):
        args = rcm.parse_args(self._argv(extra=["--mods", "5mCG_5hmCG,6mA"]))
        self.assertEqual(args.mods, ["5mCG_5hmCG", "6mA"])

    def test_rna_test_with_matching_models_parses(self):
        argv = self._argv(
            models=["rna004_sup@v6.0.0", "rna004_130bps_sup@v5.0.0"],
            test="rna_singleplex_simplex_sup",
        )
        args = rcm.parse_args(argv)
        self.assertEqual(args.test, "rna_singleplex_simplex_sup")

    def test_missing_dorado_executable_exits(self):
        argv = self._argv(dorado=self.tmp_path / "does_not_exist")
        with self.assertRaises(SystemExit):
            rcm.parse_args(argv)

    def test_single_model_exits(self):
        argv = self._argv(models=[self.dna_hac_models[0]])
        with self.assertRaises(SystemExit):
            rcm.parse_args(argv)

    def test_mismatched_model_analyte_exits(self):
        argv = self._argv(models=["rna004_hac@v6.0.0", "rna004_hac@v5.0.0"])  # --test is dna_*
        with self.assertRaises(SystemExit):
            rcm.parse_args(argv)

    def test_mismatched_model_speed_exits(self):
        argv = self._argv(
            models=["dna_r10.4.1_e8.2_400bps_sup@v5.2.0", "dna_r10.4.1_e8.2_400bps_sup@v6.0.0"],
        )  # --test is ..._hac
        with self.assertRaises(SystemExit):
            rcm.parse_args(argv)

    def test_duplicate_version_tags_exit(self):
        argv = self._argv(models=[
            "dna_r10.4.1_e8.2_400bps_hac@v6.0.0",
            "dna_r9.4.1_e8_400bps_hac@v6.0.0",
        ])
        with self.assertRaises(SystemExit):
            rcm.parse_args(argv)

    def test_missing_required_subdir_exits(self):
        empty_pod5 = self.tmp_path / "empty_pod5"
        empty_pod5.mkdir()
        argv = self._argv(pod5=empty_pod5)
        with self.assertRaises(SystemExit):
            rcm.parse_args(argv)

    def test_pod5_root_not_a_directory_exits(self):
        argv = self._argv(pod5=self.dorado_path)  # a file, not a directory
        with self.assertRaises(SystemExit):
            rcm.parse_args(argv)

    def test_invalid_test_choice_exits(self):
        with self.assertRaises(SystemExit):
            rcm.parse_args(self._argv(test="not_a_real_test"))


if __name__ == "__main__":
    unittest.main()
