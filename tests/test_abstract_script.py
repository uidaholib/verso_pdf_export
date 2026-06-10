"""Tests for abstract_script.load_metadata() — JSON file loading and validation."""

import json
import logging

import pytest

import pandas as pd

from abstract_script import (
    enrich_records,
    extract_identifiers,
    load_metadata,
    should_skip,
    write_results_csv,
)


class TestLoadMetadata:
    """Validate that load_metadata reads, parses, and validates asset_metadata.json."""

    def test_valid_json_returns_records(self, tmp_path):
        """A well-formed file with matching count returns the records list."""
        records = [{"title": "Paper A"}, {"title": "Paper B"}]
        data = {"totalRecordCount": 2, "records": records}
        path = tmp_path / "asset_metadata.json"
        path.write_text(json.dumps(data))

        result = load_metadata(str(path))

        assert result == records

    def test_file_not_found_raises_valueerror(self):
        """A missing file raises ValueError with the path in the message."""
        with pytest.raises(ValueError, match="nonexistent.json"):
            load_metadata("nonexistent.json")

    def test_invalid_json_raises_valueerror(self, tmp_path):
        """Malformed JSON raises ValueError."""
        path = tmp_path / "bad.json"
        path.write_text("{not valid json!!!")

        with pytest.raises(ValueError, match="invalid JSON"):
            load_metadata(str(path))

    def test_empty_file_raises_valueerror(self, tmp_path):
        """An empty file raises ValueError."""
        path = tmp_path / "empty.json"
        path.write_text("")

        with pytest.raises(ValueError, match="invalid JSON"):
            load_metadata(str(path))

    def test_bare_list_raises_valueerror(self, tmp_path):
        """A bare JSON list (not wrapped in an object) raises ValueError."""
        path = tmp_path / "bare_list.json"
        path.write_text(json.dumps([{"title": "Paper A"}]))

        with pytest.raises(ValueError, match="expected a JSON object"):
            load_metadata(str(path))

    def test_count_mismatch_warns_but_returns_records(self, tmp_path, caplog):
        """When totalRecordCount disagrees with len(records), warn but return."""
        records = [{"title": "Paper A"}]
        data = {"totalRecordCount": 5, "records": records}
        path = tmp_path / "mismatch.json"
        path.write_text(json.dumps(data))

        with caplog.at_level(logging.WARNING):
            result = load_metadata(str(path))

        assert result == records
        assert "totalRecordCount" in caplog.text

    def test_missing_records_key_raises_valueerror(self, tmp_path):
        """A JSON object without a 'records' key raises ValueError."""
        path = tmp_path / "no_records.json"
        path.write_text(json.dumps({"totalRecordCount": 0}))

        with pytest.raises(ValueError, match="records"):
            load_metadata(str(path))


class TestExtractIdentifiers:
    """Validate that extract_identifiers pulls the four key fields from an Esploro record."""

    def test_full_record_returns_all_fields(self, sample_esploro_record):
        """A complete record returns (asset_id_str, doi, title, resource_type)."""
        result = extract_identifiers(sample_esploro_record)

        assert result == (
            "12345678",
            "10.1234/example.2023",
            "A Sample Research Paper Title",
            "journal_article",
        )

    def test_missing_doi_returns_empty_string(self, sample_esploro_record):
        """When 'identifier.doi' is absent, doi slot is empty string."""
        del sample_esploro_record["identifier.doi"]

        result = extract_identifiers(sample_esploro_record)

        assert result == (
            "12345678",
            "",
            "A Sample Research Paper Title",
            "journal_article",
        )

    def test_missing_title_returns_empty_string(self, sample_esploro_record):
        """When 'title' is absent, title slot is empty string."""
        del sample_esploro_record["title"]

        result = extract_identifiers(sample_esploro_record)

        assert result == ("12345678", "10.1234/example.2023", "", "journal_article")

    def test_missing_resource_type_returns_empty_string(self, sample_esploro_record):
        """When 'resourceType' is absent, type slot is empty string."""
        del sample_esploro_record["resourceType"]

        result = extract_identifiers(sample_esploro_record)

        assert result == (
            "12345678",
            "10.1234/example.2023",
            "A Sample Research Paper Title",
            "",
        )

    def test_missing_original_repository_returns_empty_asset_id(
        self, sample_esploro_record
    ):
        """When 'originalRepository' is absent entirely, asset_id slot is empty string."""
        del sample_esploro_record["originalRepository"]

        result = extract_identifiers(sample_esploro_record)

        assert result == (
            "",
            "10.1234/example.2023",
            "A Sample Research Paper Title",
            "journal_article",
        )

    def test_string_asset_id_returned_as_is(self, sample_esploro_record):
        """When assetId is already a string, no double conversion occurs."""
        sample_esploro_record["originalRepository"]["assetId"] = "99999999"

        result = extract_identifiers(sample_esploro_record)

        assert result == (
            "99999999",
            "10.1234/example.2023",
            "A Sample Research Paper Title",
            "journal_article",
        )


class TestShouldSkip:
    """Validate that should_skip gates enrichment for records with abstracts or skipped types."""

    SKIP_TYPES = ["ETD-Doctoral", "ETD-Masters"]

    def test_record_with_abstract_returns_skipped_existing(self):
        """A record that already has a non-empty abstract returns the reason."""
        record = {"description.abstract": [{"value": "Some text"}]}

        assert should_skip(record, self.SKIP_TYPES) == "skipped_existing_abstract"

    def test_empty_abstract_list_returns_none(self):
        """An empty abstract list means no abstract — don't skip."""
        record = {"description.abstract": [], "resourceType": "journal_article"}

        assert should_skip(record, self.SKIP_TYPES) is None

    def test_empty_value_string_returns_none(self):
        """An abstract entry with an empty string value is not a real abstract."""
        record = {
            "description.abstract": [{"value": ""}],
            "resourceType": "journal_article",
        }

        assert should_skip(record, self.SKIP_TYPES) is None

    def test_missing_value_key_returns_none(self):
        """An abstract entry without a 'value' key has no usable abstract."""
        record = {"description.abstract": [{}], "resourceType": "journal_article"}

        assert should_skip(record, self.SKIP_TYPES) is None

    def test_no_abstract_key_returns_none(self):
        """A record with no 'description.abstract' key at all is not skipped."""
        record = {"resourceType": "journal_article"}

        assert should_skip(record, self.SKIP_TYPES) is None

    def test_etd_doctoral_returns_skipped_etd(self):
        """ETD-Doctoral is in skip_types, so it returns the ETD skip reason."""
        record = {"resourceType": "ETD-Doctoral"}

        assert should_skip(record, self.SKIP_TYPES) == "skipped_etd"

    def test_etd_masters_returns_skipped_etd(self):
        """ETD-Masters is in skip_types, so it returns the ETD skip reason."""
        record = {"resourceType": "ETD-Masters"}

        assert should_skip(record, self.SKIP_TYPES) == "skipped_etd"

    def test_journal_article_without_abstract_returns_none(self):
        """A journal_article with no abstract should not be skipped."""
        record = {"resourceType": "journal_article"}

        assert should_skip(record, self.SKIP_TYPES) is None


class TestEnrichRecords:
    """Validate the main enrichment loop over a list of Esploro records."""

    OA_RATE = 0.1
    S2_RATE = 1.0
    THRESHOLD = 90
    SKIP_TYPES = ["ETD-Doctoral", "ETD-Masters"]

    @staticmethod
    def _make_record(
        doi="10.1234/test", title="Test Paper", resource_type="journal_article"
    ):
        """Build a minimal Esploro-shaped record dict."""
        return {
            "originalRepository": {"assetId": "99999"},
            "identifier.doi": doi,
            "title": title,
            "resourceType": resource_type,
        }

    def test_enriches_records_with_abstracts(self, session, monkeypatch):
        """Provider returns abstracts for 2 of 3 records; third gets no_match."""
        records = [
            self._make_record(doi="10.1/a", title="Paper A"),
            self._make_record(doi="10.1/b", title="Paper B"),
            self._make_record(doi="10.1/c", title="Paper C"),
        ]

        call_count = 0

        def mock_try_providers(sess, doi, title, oa_rate, s2_rate, threshold):
            nonlocal call_count
            call_count += 1
            if doi in ("10.1/a", "10.1/b"):
                return (
                    {
                        "abstract": f"Abstract for {doi}",
                        "matched_title": title,
                        "external_id": f"ext_{doi}",
                        "source": "openalex",
                    },
                    "ok",
                    [f"oa_doi={doi}"],
                )
            return (None, "no_match", ["oa_doi=miss", "s2_doi=miss"])

        monkeypatch.setattr("abstract_script.try_providers", mock_try_providers)

        results = enrich_records(
            records,
            session,
            self.OA_RATE,
            self.S2_RATE,
            self.THRESHOLD,
            self.SKIP_TYPES,
        )

        assert len(results) == 3
        assert results[0]["harvest_status"] == "ok"
        assert results[0]["abstract"] == "Abstract for 10.1/a"
        assert results[1]["harvest_status"] == "ok"
        assert results[1]["abstract"] == "Abstract for 10.1/b"
        assert results[2]["harvest_status"] == "no_match"
        assert results[2]["abstract"] == ""
        assert call_count == 3

    def test_skips_record_with_existing_abstract(self, session, monkeypatch):
        """A record with an existing abstract gets skipped; provider is never called."""
        record = self._make_record()
        record["description.abstract"] = [{"value": "Already here"}]

        def should_not_be_called(*args, **kwargs):
            raise AssertionError(
                "try_providers should not be called for skipped records"
            )

        monkeypatch.setattr("abstract_script.try_providers", should_not_be_called)

        results = enrich_records(
            [record],
            session,
            self.OA_RATE,
            self.S2_RATE,
            self.THRESHOLD,
            self.SKIP_TYPES,
        )

        assert len(results) == 1
        assert results[0]["harvest_status"] == "skipped_existing_abstract"

    def test_skips_etd_record(self, session, monkeypatch):
        """An ETD-Doctoral record gets skipped; provider is never called."""
        record = self._make_record(resource_type="ETD-Doctoral")

        def should_not_be_called(*args, **kwargs):
            raise AssertionError("try_providers should not be called for ETD records")

        monkeypatch.setattr("abstract_script.try_providers", should_not_be_called)

        results = enrich_records(
            [record],
            session,
            self.OA_RATE,
            self.S2_RATE,
            self.THRESHOLD,
            self.SKIP_TYPES,
        )

        assert len(results) == 1
        assert results[0]["harvest_status"] == "skipped_etd"

    def test_skips_record_with_no_identifiers(self, session, monkeypatch):
        """A record with no DOI and no title gets harvest_status='no_identifiers'."""
        record = self._make_record(doi="", title="")

        def should_not_be_called(*args, **kwargs):
            raise AssertionError(
                "try_providers should not be called with no identifiers"
            )

        monkeypatch.setattr("abstract_script.try_providers", should_not_be_called)

        results = enrich_records(
            [record],
            session,
            self.OA_RATE,
            self.S2_RATE,
            self.THRESHOLD,
            self.SKIP_TYPES,
        )

        assert len(results) == 1
        assert results[0]["harvest_status"] == "no_identifiers"

    def test_handles_low_confidence_result(self, session, monkeypatch):
        """A low_confidence result still includes the abstract in the output."""
        record = self._make_record()

        def mock_try_providers(sess, doi, title, oa_rate, s2_rate, threshold):
            return (
                {
                    "abstract": "Fuzzy abstract",
                    "matched_title": "Close Title",
                    "external_id": "ext_123",
                    "source": "s2",
                },
                "low_confidence",
                ["oa_doi=miss", "s2_title=low_confidence"],
            )

        monkeypatch.setattr("abstract_script.try_providers", mock_try_providers)

        results = enrich_records(
            [record],
            session,
            self.OA_RATE,
            self.S2_RATE,
            self.THRESHOLD,
            self.SKIP_TYPES,
        )

        assert len(results) == 1
        assert results[0]["harvest_status"] == "low_confidence"
        assert results[0]["abstract"] == "Fuzzy abstract"
        assert results[0]["abstract_source"] == "s2"
        assert results[0]["abstract_external_id"] == "ext_123"

    def test_handles_provider_exception(self, session, monkeypatch, caplog):
        """When try_providers raises, the record gets harvest_status='error' and loop continues."""
        records = [
            self._make_record(doi="10.1/a", title="Paper A"),
            self._make_record(doi="10.1/b", title="Paper B"),
        ]

        call_count = 0

        def mock_try_providers(sess, doi, title, oa_rate, s2_rate, threshold):
            nonlocal call_count
            call_count += 1
            if doi == "10.1/a":
                raise RuntimeError("provider exploded")
            return (
                {
                    "abstract": "Good abstract",
                    "matched_title": title,
                    "external_id": "ext_b",
                    "source": "openalex",
                },
                "ok",
                ["oa_doi=hit"],
            )

        monkeypatch.setattr("abstract_script.try_providers", mock_try_providers)

        with caplog.at_level(logging.WARNING):
            results = enrich_records(
                records,
                session,
                self.OA_RATE,
                self.S2_RATE,
                self.THRESHOLD,
                self.SKIP_TYPES,
            )

        assert len(results) == 2
        assert results[0]["harvest_status"] == "error"
        assert results[1]["harvest_status"] == "ok"
        assert results[1]["abstract"] == "Good abstract"
        assert "Unexpected error" in caplog.text
        assert call_count == 2

    def test_empty_records_list(self, session, monkeypatch):
        """An empty records list returns an empty results list."""

        def should_not_be_called(*args, **kwargs):
            raise AssertionError("try_providers should not be called for empty list")

        monkeypatch.setattr("abstract_script.try_providers", should_not_be_called)

        results = enrich_records(
            [], session, self.OA_RATE, self.S2_RATE, self.THRESHOLD, self.SKIP_TYPES
        )

        assert results == []

    def test_handles_malformed_record(self, session, monkeypatch, caplog):
        """A malformed record (string instead of dict) triggers the error handler."""
        records = ["not a dict", self._make_record()]

        def mock_try_providers(sess, doi, title, oa_rate, s2_rate, threshold):
            return (
                {
                    "abstract": "Good",
                    "matched_title": title,
                    "external_id": "ext_1",
                    "source": "openalex",
                },
                "ok",
                ["oa_doi=hit"],
            )

        monkeypatch.setattr("abstract_script.try_providers", mock_try_providers)

        with caplog.at_level(logging.WARNING):
            results = enrich_records(
                records,
                session,
                self.OA_RATE,
                self.S2_RATE,
                self.THRESHOLD,
                self.SKIP_TYPES,
            )

        assert len(results) == 2
        assert results[0]["harvest_status"] == "error"
        assert results[1]["harvest_status"] == "ok"
        assert "Unexpected error" in caplog.text


class TestWriteResultsCsv:
    """Tests for write_results_csv() — CSV serialization of enrichment results."""

    def _make_result(self, **overrides):
        """Build a result dict with sensible defaults, applying any overrides."""
        base = {
            "asset_id": "123",
            "doi": "10.1234/test",
            "title": "Test Title",
            "abstract": "Some abstract text",
            "abstract_source": "openalex",
            "abstract_external_id": "W123",
            "harvest_status": "ok",
            "trace": ["oa_doi=hit"],
        }
        base.update(overrides)
        return base

    def test_creates_csv_at_path(self, tmp_path):
        csv_path = tmp_path / "results.csv"
        write_results_csv([self._make_result()], str(csv_path))

        assert csv_path.exists()

    def test_csv_has_expected_headers(self, tmp_path):
        csv_path = tmp_path / "results.csv"
        write_results_csv([self._make_result()], str(csv_path))

        df = pd.read_csv(csv_path)
        expected_columns = [
            "asset_id",
            "doi",
            "title",
            "abstract",
            "abstract_source",
            "abstract_external_id",
            "harvest_status",
            "trace",
        ]
        assert list(df.columns) == expected_columns

    def test_none_abstract_becomes_empty_string(self, tmp_path):
        csv_path = tmp_path / "results.csv"
        write_results_csv([self._make_result(abstract=None)], str(csv_path))

        df = pd.read_csv(csv_path, keep_default_na=False)
        assert df.iloc[0]["abstract"] == ""

    def test_trace_list_serialized_with_semicolons(self, tmp_path):
        csv_path = tmp_path / "results.csv"
        write_results_csv(
            [self._make_result(trace=["oa_doi=miss", "s2_doi=hit"])],
            str(csv_path),
        )

        df = pd.read_csv(csv_path)
        assert df.iloc[0]["trace"] == "oa_doi=miss;s2_doi=hit"

    def test_empty_results_creates_header_only_csv(self, tmp_path):
        csv_path = tmp_path / "results.csv"
        write_results_csv([], str(csv_path))

        df = pd.read_csv(csv_path)
        assert len(df) == 0
        assert "asset_id" in df.columns

    def test_abstract_with_commas_and_newlines_escaped(self, tmp_path):
        csv_path = tmp_path / "results.csv"
        tricky_abstract = "Results show that, surprisingly,\nnewlines appear."
        write_results_csv(
            [self._make_result(abstract=tricky_abstract)],
            str(csv_path),
        )

        df = pd.read_csv(csv_path)
        assert df.iloc[0]["abstract"] == tricky_abstract
