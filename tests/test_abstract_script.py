"""Tests for abstract_script.load_metadata() — JSON file loading and validation."""

import json
import logging

import pytest

from abstract_script import extract_identifiers, load_metadata


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
