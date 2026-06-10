"""Smoke tests for providers.enrich — verify functions are importable and correct."""

import logging

import requests

from providers.enrich import enrich_final_output, extract_identifiers, should_skip


def test_extract_identifiers_returns_four_fields(sample_esploro_record):
    result = extract_identifiers(sample_esploro_record)
    assert result == (
        "12345678",
        "10.1234/example.2023",
        "A Sample Research Paper Title",
        "journal_article",
    )


def test_should_skip_record_with_abstract_returns_skip_reason(sample_esploro_record):
    assert should_skip(sample_esploro_record, []) == "skipped_existing_abstract"


def test_should_skip_record_without_abstract_returns_none(sample_esploro_record):
    record_without_abstract = dict(sample_esploro_record)
    record_without_abstract["description.abstract"] = []
    assert should_skip(record_without_abstract, []) is None


# ---------------------------------------------------------------------------
# Helpers for enrich_final_output tests
# ---------------------------------------------------------------------------


def _make_record(
    asset_id="99999",
    doi="10.1234/test",
    title="Test Paper",
    resource_type="journal_article",
    abstract_value="",
):
    record: dict = {
        "originalRepository": {"assetId": asset_id},
        "identifier.doi": doi,
        "title": title,
        "resourceType": resource_type,
    }
    if abstract_value:
        record["description.abstract"] = [{"value": abstract_value}]
    return record


def _provider_result(abstract="An abstract.", source="openalex", ext_id="W12345"):
    return {
        "abstract": abstract,
        "source": source,
        "external_id": ext_id,
        "matched_title": "Test Paper",
    }


# ---------------------------------------------------------------------------
# enrich_final_output tests (12 cases)
# ---------------------------------------------------------------------------


class TestEnrichFinalOutput:
    """Tests for the enrich_final_output orchestration function."""

    def test_mixed_results_two_ok_one_no_match(self, monkeypatch):
        """#1: 3 records, provider returns abstracts for 2, no match for 1."""
        call_count = 0

        def mock_try_providers(session, doi, title, oa_rate, s2_rate, threshold):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return (_provider_result(), "ok", ["oa_doi=hit"])
            return (None, "no_match", ["oa_doi=miss"])

        monkeypatch.setattr("providers.enrich.try_providers", mock_try_providers)

        records = [
            _make_record(asset_id="1", doi="10.1/a"),
            _make_record(asset_id="2", doi="10.1/b"),
            _make_record(asset_id="3", doi="10.1/c"),
        ]
        result = enrich_final_output(records, requests.Session(), 0.0, 0.0)

        assert len(result) == 3
        expected_keys = {
            "abstract",
            "abstract_source",
            "abstract_external_id",
            "harvest_status",
            "trace",
        }
        assert set(result["1"].keys()) == expected_keys
        assert result["1"]["harvest_status"] == "ok"
        assert result["1"]["abstract"] == "An abstract."
        assert result["1"]["abstract_source"] == "openalex"
        assert result["1"]["abstract_external_id"] == "W12345"
        assert result["1"]["trace"] == ["oa_doi=hit"]
        assert result["2"]["harvest_status"] == "ok"
        assert result["3"]["harvest_status"] == "no_match"
        assert result["3"]["abstract"] == ""
        assert result["3"]["trace"] == ["oa_doi=miss"]

    def test_skips_record_with_existing_abstract(self, monkeypatch):
        """#2: Record with existing abstract is skipped; try_providers NOT called."""

        def mock_try_providers(*args, **kwargs):
            raise AssertionError(
                "try_providers should not be called for skipped record"
            )

        monkeypatch.setattr("providers.enrich.try_providers", mock_try_providers)

        records = [_make_record(abstract_value="Already have one")]
        result = enrich_final_output(records, requests.Session(), 0.0, 0.0)

        assert result["99999"]["harvest_status"] == "skipped_existing_abstract"

    def test_empty_abstract_value_not_skipped(self, monkeypatch):
        """#3: Record with empty abstract value string is NOT skipped."""

        def mock_try_providers(session, doi, title, oa_rate, s2_rate, threshold):
            return (_provider_result(), "ok", ["oa_doi=hit"])

        monkeypatch.setattr("providers.enrich.try_providers", mock_try_providers)

        record = _make_record()
        record["description.abstract"] = [{"value": ""}]
        result = enrich_final_output([record], requests.Session(), 0.0, 0.0)

        assert result["99999"]["harvest_status"] == "ok"

    def test_etd_record_skipped(self, monkeypatch):
        """#4: ETD record is skipped when its type is in skip_types."""

        def mock_try_providers(*args, **kwargs):
            raise AssertionError("try_providers should not be called for ETD")

        monkeypatch.setattr("providers.enrich.try_providers", mock_try_providers)

        records = [_make_record(resource_type="ETD-Doctoral")]
        result = enrich_final_output(
            records, requests.Session(), 0.0, 0.0, skip_types=["ETD-Doctoral"]
        )

        assert result["99999"]["harvest_status"] == "skipped_etd"

    def test_no_doi_no_title_returns_no_identifiers(self, monkeypatch):
        """#5: Record with no DOI and no title gets no_identifiers status."""

        def mock_try_providers(*args, **kwargs):
            raise AssertionError("try_providers should not be called")

        monkeypatch.setattr("providers.enrich.try_providers", mock_try_providers)

        records = [_make_record(doi="", title="")]
        result = enrich_final_output(records, requests.Session(), 0.0, 0.0)

        assert result["99999"]["harvest_status"] == "no_identifiers"

    def test_low_confidence_result(self, monkeypatch):
        """#6: Provider returns low_confidence — abstract still populated."""

        def mock_try_providers(session, doi, title, oa_rate, s2_rate, threshold):
            return (_provider_result(), "low_confidence", ["oa_title=hit"])

        monkeypatch.setattr("providers.enrich.try_providers", mock_try_providers)

        records = [_make_record()]
        result = enrich_final_output(records, requests.Session(), 0.0, 0.0)

        assert result["99999"]["harvest_status"] == "low_confidence"
        assert result["99999"]["abstract"] == "An abstract."

    def test_provider_exception_yields_error_status(self, monkeypatch):
        """#7: Provider raises exception — error status, continues to next."""

        call_count = 0

        def mock_try_providers(session, doi, title, oa_rate, s2_rate, threshold):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("API exploded")
            return (_provider_result(), "ok", ["oa_doi=hit"])

        monkeypatch.setattr("providers.enrich.try_providers", mock_try_providers)

        records = [_make_record(asset_id="1"), _make_record(asset_id="2")]
        result = enrich_final_output(records, requests.Session(), 0.0, 0.0)

        assert result["1"]["harvest_status"] == "error"
        assert result["2"]["harvest_status"] == "ok"

    def test_empty_records_returns_empty_dict(self):
        """#8: Empty records list returns empty dict."""
        result = enrich_final_output([], requests.Session(), 0.0, 0.0)
        assert result == {}

    def test_missing_original_repository_does_not_crash(self, monkeypatch):
        """#9: Record missing originalRepository handled gracefully."""

        def mock_try_providers(session, doi, title, oa_rate, s2_rate, threshold):
            return (_provider_result(), "ok", ["oa_doi=hit"])

        monkeypatch.setattr("providers.enrich.try_providers", mock_try_providers)

        record = {
            "identifier.doi": "10.1234/test",
            "title": "Test Paper",
            "resourceType": "journal_article",
        }
        result = enrich_final_output([record], requests.Session(), 0.0, 0.0)

        # asset_id defaults to "" via extract_identifiers
        assert "" in result
        assert result[""]["harvest_status"] == "ok"

    def test_skip_types_none_default_no_skipping(self, monkeypatch):
        """#10: skip_types=None (default) means no type-based skipping."""

        def mock_try_providers(session, doi, title, oa_rate, s2_rate, threshold):
            return (_provider_result(), "ok", ["oa_doi=hit"])

        monkeypatch.setattr("providers.enrich.try_providers", mock_try_providers)

        records = [_make_record(resource_type="ETD-Doctoral")]
        result = enrich_final_output(records, requests.Session(), 0.0, 0.0)

        # Without skip_types containing "ETD-Doctoral", should NOT be skipped
        assert result["99999"]["harvest_status"] == "ok"

    def test_asset_id_keys_are_strings(self, monkeypatch):
        """#11: Result dict keys are always strings, even if assetId was int."""

        def mock_try_providers(session, doi, title, oa_rate, s2_rate, threshold):
            return (_provider_result(), "ok", ["oa_doi=hit"])

        monkeypatch.setattr("providers.enrich.try_providers", mock_try_providers)

        record = _make_record()
        record["originalRepository"]["assetId"] = 42
        result = enrich_final_output([record], requests.Session(), 0.0, 0.0)

        assert all(isinstance(k, str) for k in result)
        assert "42" in result

    def test_all_skipped_logs_warning(self, monkeypatch, caplog):
        """#12: All records skipped logs a warning about check skip_types."""

        def mock_try_providers(*args, **kwargs):
            raise AssertionError("should not be called")

        monkeypatch.setattr("providers.enrich.try_providers", mock_try_providers)

        records = [
            _make_record(asset_id="1", resource_type="ETD-Doctoral"),
            _make_record(asset_id="2", resource_type="ETD-Doctoral"),
        ]
        with caplog.at_level(logging.WARNING, logger="providers.enrich"):
            result = enrich_final_output(
                records,
                requests.Session(),
                0.0,
                0.0,
                skip_types=["ETD-Doctoral"],
            )

        assert any("All 2 records were skipped" in msg for msg in caplog.messages)
        assert len(result) == 2
        assert result["1"]["harvest_status"] == "skipped_etd"
        assert result["2"]["harvest_status"] == "skipped_etd"
