"""Tests for abstract_script.load_metadata() — JSON file loading and validation."""

import json
import logging

import pytest

from abstract_script import load_metadata


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
