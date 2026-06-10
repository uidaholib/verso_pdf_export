"""Tests for script.py refactoring — verifying no import side effects and CLI parsing."""

import logging
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_script_import_no_side_effects(tmp_path):
    """Importing script should not create directories or configure logging."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import logging; "
                "baseline_handlers = len(logging.getLogger().handlers); "
                "import script; "
                "import os; "
                "dirs = sorted(os.listdir('.')); "
                "new_handlers = len(logging.getLogger().handlers) - baseline_handlers; "
                "print(f'{dirs}|{new_handlers}')"
            ),
        ],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT)},
    )
    assert result.returncode == 0, f"Import failed: {result.stderr}"
    dir_listing, handler_count = result.stdout.strip().split("|")
    assert "C" not in dir_listing, "Importing script should not create C/ directory"
    assert int(handler_count) == 0, (
        "Importing script should not configure logging handlers"
    )


def test_script_parse_args_defaults():
    """parse_args([]) returns correct defaults."""
    import script

    args = script.parse_args([])
    assert args.csv == "assetsWithPDFs_just_ETDs.csv"
    assert args.debug is False
    assert args.subset_size == 5


def test_script_parse_args_all_flags():
    """parse_args with all flags returns correct overrides."""
    import script

    args = script.parse_args(["--csv", "x.csv", "--debug", "--subset-size", "3"])
    assert args.csv == "x.csv"
    assert args.debug is True
    assert args.subset_size == 3


def test_script_parse_args_debug_only():
    """parse_args with only --debug returns debug=True, others at defaults."""
    import script

    args = script.parse_args(["--debug"])
    assert args.debug is True
    assert args.csv == "assetsWithPDFs_just_ETDs.csv"
    assert args.subset_size == 5


def test_md_script_import_no_side_effects(tmp_path):
    """Importing md_script should not create directories or configure logging."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import logging; "
                "baseline_handlers = len(logging.getLogger().handlers); "
                "import md_script; "
                "import os; "
                "dirs = sorted(os.listdir('.')); "
                "new_handlers = len(logging.getLogger().handlers) - baseline_handlers; "
                "print(f'{dirs}|{new_handlers}')"
            ),
        ],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT)},
    )
    assert result.returncode == 0, f"Import failed: {result.stderr}"
    dir_listing, handler_count = result.stdout.strip().split("|")
    assert "C" not in dir_listing, "Importing md_script should not create C/ directory"
    assert int(handler_count) == 0, (
        "Importing md_script should not configure logging handlers"
    )


def test_md_script_parse_args_defaults():
    """parse_args([]) returns correct defaults."""
    import md_script

    args = md_script.parse_args([])
    assert args.csv == "assetsWithPDFs_without_ETD.csv"
    assert args.debug is False
    assert args.subset_size == 5


def test_md_script_parse_args_all_flags():
    """parse_args with --csv and --debug returns overrides, subset_size at default."""
    import md_script

    args = md_script.parse_args(["--csv", "y.csv", "--debug"])
    assert args.csv == "y.csv"
    assert args.debug is True
    assert args.subset_size == 5


# ---------------------------------------------------------------------------
# generate_metadata_csv enrichment integration tests
# ---------------------------------------------------------------------------

EXPECTED_COLUMNS = 29
ENRICHMENT_COLS = ["abstract", "abstract_source", "abstract_external_id"]


def _read_csv(tmp_path):
    """Read the generated CSV from the output directory."""
    return pd.read_csv(tmp_path / "pdf_metadata.csv")


class TestGenerateMetadataCsvEnrichment:
    """Tests for the enrichment and output_dir extensions to generate_metadata_csv."""

    def test_no_enrichment_produces_29_empty_columns(
        self, tmp_path, sample_file_task, sample_final_output
    ):
        """Test #1 & #6: enrichment_results=None produces 29 columns with
        the last 3 empty and in the correct order."""
        import script

        script.generate_metadata_csv(
            [sample_file_task], sample_final_output, output_dir=str(tmp_path)
        )
        df = _read_csv(tmp_path)

        assert len(df.columns) == EXPECTED_COLUMNS
        assert list(df.columns[-3:]) == ENRICHMENT_COLS
        # All enrichment values should be empty
        row = df.iloc[0]
        for col in ENRICHMENT_COLS:
            assert pd.isna(row[col]) or row[col] == ""

    def test_empty_dict_enrichment_produces_29_empty_columns(
        self, tmp_path, sample_file_task, sample_final_output
    ):
        """Test #2: enrichment_results={} (empty dict) behaves the same as None."""
        import script

        script.generate_metadata_csv(
            [sample_file_task],
            sample_final_output,
            enrichment_results={},
            output_dir=str(tmp_path),
        )
        df = _read_csv(tmp_path)

        assert len(df.columns) == EXPECTED_COLUMNS
        row = df.iloc[0]
        for col in ENRICHMENT_COLS:
            assert pd.isna(row[col]) or row[col] == ""

    def test_matching_enrichment_populates_columns(
        self, tmp_path, sample_file_task, sample_final_output
    ):
        """Test #3: enrichment entry keyed to the asset_id populates the 3 new columns."""
        import script

        enrichment = {
            "12345678": {
                "abstract": "Enriched abstract text.",
                "abstract_source": "crossref",
                "abstract_external_id": "10.1234/example.2023",
            }
        }
        script.generate_metadata_csv(
            [sample_file_task],
            sample_final_output,
            enrichment_results=enrichment,
            output_dir=str(tmp_path),
        )
        df = _read_csv(tmp_path)
        row = df.iloc[0]

        assert row["abstract"] == "Enriched abstract text."
        assert row["abstract_source"] == "crossref"
        assert row["abstract_external_id"] == "10.1234/example.2023"

    def test_missing_enrichment_entry_leaves_columns_empty(
        self, tmp_path, sample_file_task, sample_final_output
    ):
        """Test #4: enrichment dict exists but has no entry for this asset_id."""
        import script

        enrichment = {
            "99999999": {
                "abstract": "Wrong asset.",
                "abstract_source": "openalex",
                "abstract_external_id": "10.9999/other",
            }
        }
        script.generate_metadata_csv(
            [sample_file_task],
            sample_final_output,
            enrichment_results=enrichment,
            output_dir=str(tmp_path),
        )
        df = _read_csv(tmp_path)
        row = df.iloc[0]

        for col in ENRICHMENT_COLS:
            assert pd.isna(row[col]) or row[col] == ""

    def test_description_column_unchanged_by_enrichment(
        self, tmp_path, sample_file_task, sample_final_output
    ):
        """Test #5: the description column still comes from Esploro data,
        even when enrichment provides a different abstract."""
        import script

        enrichment = {
            "12345678": {
                "abstract": "A completely different abstract from enrichment.",
                "abstract_source": "crossref",
                "abstract_external_id": "10.1234/example.2023",
            }
        }
        script.generate_metadata_csv(
            [sample_file_task],
            sample_final_output,
            enrichment_results=enrichment,
            output_dir=str(tmp_path),
        )
        df = _read_csv(tmp_path)
        row = df.iloc[0]

        # description comes from the Esploro record, not enrichment
        assert row["description"] == "This is the abstract text of the sample paper."
        # enrichment abstract is separate
        assert row["abstract"] == "A completely different abstract from enrichment."

    def test_column_order_last_three(
        self, tmp_path, sample_file_task, sample_final_output
    ):
        """Test #6: explicit check that the last 3 column headers are the
        enrichment columns in the correct order."""
        import script

        script.generate_metadata_csv(
            [sample_file_task], sample_final_output, output_dir=str(tmp_path)
        )
        df = _read_csv(tmp_path)
        assert list(df.columns[-3:]) == ENRICHMENT_COLS

    def test_asset_id_int_str_mismatch_resolved(
        self, tmp_path, sample_file_task, sample_final_output
    ):
        """Test #7: asset_id is int in the task but str key in enrichment_results.
        The str() conversion in the lookup must bridge the mismatch."""
        import script

        # sample_file_task has asset_id=12345678 (int)
        # enrichment keys on "12345678" (str)
        enrichment = {
            "12345678": {
                "abstract": "Found via str conversion.",
                "abstract_source": "semantic_scholar",
                "abstract_external_id": "SS:123",
            }
        }
        script.generate_metadata_csv(
            [sample_file_task],
            sample_final_output,
            enrichment_results=enrichment,
            output_dir=str(tmp_path),
        )
        df = _read_csv(tmp_path)
        row = df.iloc[0]

        assert row["abstract"] == "Found via str conversion."
        assert row["abstract_source"] == "semantic_scholar"
        assert row["abstract_external_id"] == "SS:123"


# ---------------------------------------------------------------------------
# script.py enrichment wiring integration tests (Step 6)
# ---------------------------------------------------------------------------

from unittest.mock import MagicMock, patch


class TestScriptEnrichmentWiring:
    """Verify --enrich-abstracts flag wires enrich_final_output into main()."""

    def test_parse_args_defaults_enrich_flags(self):
        """Test #1: Default args have enrich_abstracts=False, fuzzy_threshold=90."""
        import script

        args = script.parse_args([])
        assert args.enrich_abstracts is False
        assert args.fuzzy_threshold == 90

    def test_parse_args_enrich_abstracts_flag(self):
        """Test #2: --enrich-abstracts sets enrich_abstracts=True."""
        import script

        args = script.parse_args(["--enrich-abstracts"])
        assert args.enrich_abstracts is True

    def test_parse_args_fuzzy_threshold_override(self):
        """Test #3: --enrich-abstracts --fuzzy-threshold 85 sets both."""
        import script

        args = script.parse_args(["--enrich-abstracts", "--fuzzy-threshold", "85"])
        assert args.enrich_abstracts is True
        assert args.fuzzy_threshold == 85

    @patch("script.load_dotenv")
    @patch("script.load_data")
    @patch("script.make_api_calls")
    @patch("script.download_asset_files")
    @patch("script.generate_metadata_csv")
    @patch("script.enrich_final_output")
    @patch("logging.FileHandler", return_value=logging.NullHandler())
    def test_no_enrich_flag_skips_enrichment(
        self,
        mock_file_handler,
        mock_enrich,
        mock_gen_csv,
        mock_download,
        mock_api,
        mock_load,
        mock_dotenv,
        tmp_path,
        sample_esploro_record,
    ):
        """Test #4: Without --enrich-abstracts, enrich_final_output is NOT called
        and generate_metadata_csv receives enrichment_results={}."""
        mock_load.return_value = MagicMock()
        mock_api.return_value = {
            "totalRecordCount": 1,
            "records": [sample_esploro_record],
        }
        mock_download.return_value = [{"asset_id": 12345678}]

        import script

        script.main([])

        mock_enrich.assert_not_called()
        mock_gen_csv.assert_called_once()
        call_kwargs = mock_gen_csv.call_args
        assert call_kwargs[1]["enrichment_results"] == {}

    @patch("script.load_dotenv")
    @patch("script.load_data")
    @patch("script.make_api_calls")
    @patch("script.download_asset_files")
    @patch("script.generate_metadata_csv")
    @patch("script.enrich_final_output")
    @patch("logging.FileHandler", return_value=logging.NullHandler())
    def test_enrich_flag_calls_enrichment_and_passes_results(
        self,
        mock_file_handler,
        mock_enrich,
        mock_gen_csv,
        mock_download,
        mock_api,
        mock_load,
        mock_dotenv,
        tmp_path,
        sample_esploro_record,
    ):
        """Test #5: With --enrich-abstracts, enrich_final_output IS called and
        its return value is passed to generate_metadata_csv."""
        mock_load.return_value = MagicMock()
        records = [sample_esploro_record]
        mock_api.return_value = {"totalRecordCount": 1, "records": records}
        mock_download.return_value = [{"asset_id": 12345678}]
        fake_enrichment = {
            "12345678": {
                "abstract": "enriched",
                "abstract_source": "openalex",
                "abstract_external_id": "W123",
            }
        }
        mock_enrich.return_value = fake_enrichment

        import script

        script.main(["--enrich-abstracts"])

        mock_enrich.assert_called_once()
        call_args = mock_enrich.call_args
        assert call_args[0][0] is records
        assert call_args[0][2] == 0.1  # oa_rate from OPENALEX_RATE_INTERVAL default
        assert call_args[0][3] == 1.0  # s2_rate from S2_RATE_INTERVAL default
        assert call_args[0][4] == 90  # fuzzy_threshold default
        assert call_args[0][5] == ["ETD-Doctoral", "ETD-Masters"]

        mock_gen_csv.assert_called_once()
        assert mock_gen_csv.call_args[1]["enrichment_results"] is fake_enrichment

    # Intentionally does NOT mock enrich_final_output — we let the real function
    # run (with try_providers mocked out) so caplog captures the actual warning.
    @patch("script.load_dotenv")
    @patch("script.load_data")
    @patch("script.make_api_calls")
    @patch("script.download_asset_files")
    @patch("script.generate_metadata_csv")
    @patch("providers.harvester.try_providers")
    @patch("logging.FileHandler", return_value=logging.NullHandler())
    def test_all_etd_records_logs_warning(
        self,
        mock_file_handler,
        mock_try_providers,
        mock_gen_csv,
        mock_download,
        mock_api,
        mock_load,
        mock_dotenv,
        caplog,
    ):
        """Test #6: When all records are ETD types and --enrich-abstracts is set,
        a warning is logged that all records were skipped."""
        mock_load.return_value = MagicMock()
        etd_record = {
            "title": "My Dissertation",
            "description.abstract": [],
            "originalRepository": {"assetId": 99999},
            "identifier.doi": "10.1234/diss",
            "resourceType": "ETD-Doctoral",
        }
        mock_api.return_value = {"totalRecordCount": 1, "records": [etd_record]}
        mock_download.return_value = []

        import script

        with caplog.at_level(logging.WARNING, logger="providers.enrich"):
            script.main(["--enrich-abstracts"])

        assert "All 1 records were skipped" in caplog.text
        mock_try_providers.assert_not_called()


class TestMdScriptGenerateMetadataCsvEnrichment:
    """Tests for the enrichment and output_dir extensions to md_script.generate_metadata_csv."""

    def test_no_enrichment_produces_29_columns_with_empty_enrichment(
        self, tmp_path, sample_file_task, sample_final_output
    ):
        """enrichment_results=None produces 29 columns with the last 3 empty."""
        import md_script

        md_script.generate_metadata_csv(
            [sample_file_task], sample_final_output, output_dir=str(tmp_path)
        )
        df = _read_csv(tmp_path)

        assert len(df.columns) == EXPECTED_COLUMNS
        assert list(df.columns[-3:]) == ENRICHMENT_COLS
        row = df.iloc[0]
        for col in ENRICHMENT_COLS:
            assert pd.isna(row[col]) or row[col] == ""

    def test_matching_enrichment_populates_columns(
        self, tmp_path, sample_file_task, sample_final_output
    ):
        """enrichment entry keyed to the asset_id populates the 3 new columns."""
        import md_script

        enrichment = {
            "12345678": {
                "abstract": "Enriched abstract text.",
                "abstract_source": "crossref",
                "abstract_external_id": "10.1234/example.2023",
            }
        }
        md_script.generate_metadata_csv(
            [sample_file_task],
            sample_final_output,
            enrichment_results=enrichment,
            output_dir=str(tmp_path),
        )
        df = _read_csv(tmp_path)
        row = df.iloc[0]

        assert row["abstract"] == "Enriched abstract text."
        assert row["abstract_source"] == "crossref"
        assert row["abstract_external_id"] == "10.1234/example.2023"

    def test_asset_id_int_str_mismatch_resolved(
        self, tmp_path, sample_file_task, sample_final_output
    ):
        """asset_id is int in the task but str key in enrichment_results.
        The str() conversion in the lookup must bridge the mismatch."""
        import md_script

        enrichment = {
            "12345678": {
                "abstract": "Found via str conversion.",
                "abstract_source": "semantic_scholar",
                "abstract_external_id": "SS:123",
            }
        }
        md_script.generate_metadata_csv(
            [sample_file_task],
            sample_final_output,
            enrichment_results=enrichment,
            output_dir=str(tmp_path),
        )
        df = _read_csv(tmp_path)
        row = df.iloc[0]

        assert row["abstract"] == "Found via str conversion."
        assert row["abstract_source"] == "semantic_scholar"
        assert row["abstract_external_id"] == "SS:123"


class TestMdScriptEnrichmentWiring:
    """Verify --enrich-abstracts flag wires enrich_final_output into md_script.main()."""

    def test_parse_args_defaults_enrich_flags(self):
        """Default args have enrich_abstracts=False, fuzzy_threshold=90."""
        import md_script

        args = md_script.parse_args([])
        assert args.enrich_abstracts is False
        assert args.fuzzy_threshold == 90

    def test_parse_args_enrich_abstracts_flag(self):
        """--enrich-abstracts sets enrich_abstracts=True."""
        import md_script

        args = md_script.parse_args(["--enrich-abstracts"])
        assert args.enrich_abstracts is True

    def test_parse_args_fuzzy_threshold_override(self):
        """--enrich-abstracts --fuzzy-threshold 85 sets both."""
        import md_script

        args = md_script.parse_args(["--enrich-abstracts", "--fuzzy-threshold", "85"])
        assert args.enrich_abstracts is True
        assert args.fuzzy_threshold == 85

    @patch("md_script.load_dotenv")
    @patch("md_script.load_data")
    @patch("md_script.make_api_calls")
    @patch("md_script.generate_file_tasks")
    @patch("md_script.generate_metadata_csv")
    @patch("md_script.enrich_final_output")
    @patch("logging.FileHandler", return_value=logging.NullHandler())
    def test_enrich_flag_calls_enrichment_and_passes_results(
        self,
        mock_file_handler,
        mock_enrich,
        mock_gen_csv,
        mock_gen_tasks,
        mock_api,
        mock_load,
        mock_dotenv,
        tmp_path,
        sample_esploro_record,
    ):
        """With --enrich-abstracts, enrich_final_output IS called and
        its return value is passed to generate_metadata_csv."""
        mock_load.return_value = MagicMock()
        records = [sample_esploro_record]
        mock_api.return_value = {"totalRecordCount": 1, "records": records}
        mock_gen_tasks.return_value = MagicMock()
        fake_enrichment = {
            "12345678": {
                "abstract": "enriched",
                "abstract_source": "openalex",
                "abstract_external_id": "W123",
            }
        }
        mock_enrich.return_value = fake_enrichment

        import md_script

        md_script.main(["--enrich-abstracts"])

        mock_enrich.assert_called_once()
        call_args = mock_enrich.call_args
        assert call_args[0][0] is records
        assert call_args[0][2] == 0.1  # oa_rate from OPENALEX_RATE_INTERVAL default
        assert call_args[0][3] == 1.0  # s2_rate from S2_RATE_INTERVAL default
        assert call_args[0][4] == 90  # fuzzy_threshold default
        assert call_args[0][5] == ["ETD-Doctoral", "ETD-Masters"]

        mock_gen_csv.assert_called_once()
        assert mock_gen_csv.call_args[1]["enrichment_results"] is fake_enrichment

    @patch("md_script.load_dotenv")
    @patch("md_script.load_data")
    @patch("md_script.make_api_calls")
    @patch("md_script.generate_file_tasks")
    @patch("md_script.generate_metadata_csv")
    @patch("md_script.enrich_final_output")
    @patch("logging.FileHandler", return_value=logging.NullHandler())
    def test_no_enrich_flag_skips_enrichment(
        self,
        mock_file_handler,
        mock_enrich,
        mock_gen_csv,
        mock_gen_tasks,
        mock_api,
        mock_load,
        mock_dotenv,
        tmp_path,
        sample_esploro_record,
    ):
        """Without --enrich-abstracts, enrich_final_output is NOT called
        and generate_metadata_csv receives enrichment_results={}."""
        mock_load.return_value = MagicMock()
        mock_api.return_value = {
            "totalRecordCount": 1,
            "records": [sample_esploro_record],
        }
        mock_gen_tasks.return_value = MagicMock()

        import md_script

        md_script.main([])

        mock_enrich.assert_not_called()
        mock_gen_csv.assert_called_once()
        call_kwargs = mock_gen_csv.call_args
        assert call_kwargs[1]["enrichment_results"] == {}
