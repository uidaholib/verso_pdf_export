"""Tests for import_abstracts — Phase 3."""

import json
import logging
from datetime import datetime

import pytest

from unittest.mock import patch

import pandas as pd

from import_abstracts import (
    build_doi_index,
    load_verso_records,
    main,
    match_records,
    parse_args,
    parse_bson_abstracts,
    write_import_csv,
)


class TestParseBsonAbstracts:
    """Tests for parse_bson_abstracts()."""

    # 1. Filters to only docs with both abstract and abstract_source
    def test_filters_docs_missing_abstract(self, write_bson_file):
        docs = [
            {
                "abstract": "Good one",
                "abstract_source": "s2",
                "abstract_external_id": "id1",
                "identifier_doi": "10.1/a",
                "title": "T1",
            },
            {
                "abstract": "Good two",
                "abstract_source": "s2",
                "abstract_external_id": "id2",
                "identifier_doi": "10.1/b",
                "title": "T2",
            },
            {
                "abstract_source": "s2",
                "abstract_external_id": "id3",
                "identifier_doi": "10.1/c",
                "title": "T3",
            },
        ]
        path = write_bson_file(docs)
        result = parse_bson_abstracts(path)
        assert len(result) == 2
        assert result[0]["abstract"] == "Good one"
        assert result[1]["abstract"] == "Good two"

    # 2. Empty abstract string excluded
    def test_empty_abstract_excluded(self, write_bson_file):
        docs = [
            {
                "abstract": "",
                "abstract_source": "s2",
                "abstract_external_id": "id1",
                "identifier_doi": "10.1/a",
                "title": "T1",
            },
        ]
        path = write_bson_file(docs)
        result = parse_bson_abstracts(path)
        assert result == []

    # 3. Missing abstract_source key excluded
    def test_missing_abstract_source_key_excluded(self, write_bson_file):
        docs = [
            {
                "abstract": "Has abstract but no source",
                "abstract_external_id": "id1",
                "identifier_doi": "10.1/a",
                "title": "T1",
            },
        ]
        path = write_bson_file(docs)
        result = parse_bson_abstracts(path)
        assert result == []

    # 4. Empty abstract_source excluded
    def test_empty_abstract_source_excluded(self, write_bson_file):
        docs = [
            {
                "abstract": "Has abstract",
                "abstract_source": "",
                "abstract_external_id": "id1",
                "identifier_doi": "10.1/a",
                "title": "T1",
            },
        ]
        path = write_bson_file(docs)
        result = parse_bson_abstracts(path)
        assert result == []

    # 5. Non-existent file raises ValueError with path in message
    def test_nonexistent_file_raises_valueerror(self):
        with pytest.raises(ValueError, match="nonexistent.bson"):
            parse_bson_abstracts("nonexistent.bson")

    # 6. Empty file returns empty list and logs warning
    def test_empty_file_returns_empty_list_logs_warning(self, tmp_path, caplog):
        path = tmp_path / "empty.bson"
        path.write_bytes(b"")
        with caplog.at_level(logging.WARNING):
            result = parse_bson_abstracts(str(path))
        assert result == []
        assert "0 documents" in caplog.text

    # 7. Missing identifier_doi defaults to ""
    def test_missing_doi_defaults_to_empty_string(self, write_bson_file):
        docs = [
            {
                "abstract": "Text",
                "abstract_source": "s2",
                "abstract_external_id": "id1",
                "title": "T1",
            },
        ]
        path = write_bson_file(docs)
        result = parse_bson_abstracts(path)
        assert len(result) == 1
        assert result[0]["identifier_doi"] == ""

    # 8. Explicit None title coerced to ""
    def test_none_title_coerced_to_empty_string(self, write_bson_file):
        docs = [
            {
                "abstract": "Text",
                "abstract_source": "s2",
                "abstract_external_id": "id1",
                "identifier_doi": "10.1/a",
                "title": None,
            },
        ]
        path = write_bson_file(docs)
        result = parse_bson_abstracts(path)
        assert len(result) == 1
        assert result[0]["title"] == ""

    # 9. Absent abstract key excluded (distinct from empty string)
    def test_absent_abstract_key_excluded(self, write_bson_file):
        docs = [
            {
                "abstract_source": "s2",
                "abstract_external_id": "id1",
                "identifier_doi": "10.1/a",
                "title": "T1",
            },
        ]
        path = write_bson_file(docs)
        result = parse_bson_abstracts(path)
        assert result == []

    # 10. Returned dict has exactly the expected keys
    def test_returned_dict_shape(self, write_bson_file):
        docs = [
            {
                "abstract": "Text",
                "abstract_source": "s2",
                "abstract_external_id": "id1",
                "identifier_doi": "10.1/a",
                "title": "T1",
            },
        ]
        path = write_bson_file(docs)
        result = parse_bson_abstracts(path)
        assert len(result) == 1
        expected_keys = {
            "abstract",
            "abstract_source",
            "abstract_external_id",
            "identifier_doi",
            "title",
        }
        assert set(result[0].keys()) == expected_keys

    # 11. Truncated/corrupt BSON raises ValueError
    def test_corrupt_bson_raises_valueerror(self, tmp_path):
        path = tmp_path / "corrupt.bson"
        path.write_bytes(b"\x05\x00\x00\x00garbage bytes here")
        with pytest.raises(ValueError, match="corrupt|decode|invalid|BSON"):
            parse_bson_abstracts(str(path))


def _make_doc(doi="10.1/a", abstract="Text", abstract_source="s2"):
    """Helper to build a minimal doc dict for build_doi_index tests."""
    return {
        "abstract": abstract,
        "abstract_source": abstract_source,
        "abstract_external_id": "",
        "identifier_doi": doi,
        "title": "T",
    }


class TestBuildDoiIndex:
    """Tests for build_doi_index()."""

    # 1. 3 docs with distinct DOIs -> dict with 3 entries, keys lowercase
    def test_three_distinct_dois(self):
        docs = [_make_doc("10.1/aaa"), _make_doc("10.2/bbb"), _make_doc("10.3/ccc")]
        index = build_doi_index(docs)
        assert len(index) == 3
        assert all(k == k.lower() for k in index)

    # 2. Case-insensitive lookup
    def test_case_insensitive_lookup(self):
        docs = [_make_doc("10.1/ABC")]
        index = build_doi_index(docs)
        assert "10.1/abc" in index

    # 3. Leading/trailing whitespace stripped
    def test_whitespace_stripped(self):
        docs = [_make_doc("  10.1/x  ")]
        index = build_doi_index(docs)
        assert "10.1/x" in index
        assert len(index) == 1

    # 4. Empty DOI not included
    def test_empty_doi_excluded(self):
        docs = [_make_doc("10.1/a"), _make_doc("")]
        index = build_doi_index(docs)
        assert len(index) == 1
        assert "10.1/a" in index

    # 5. Duplicate DOIs (different case) -> last one wins, logs warning
    def test_duplicate_doi_last_wins_and_warns(self, caplog):
        doc_upper = _make_doc("10.1/DUP")
        doc_upper["title"] = "First"
        doc_lower = _make_doc("10.1/dup")
        doc_lower["title"] = "Second"
        with caplog.at_level(logging.WARNING):
            index = build_doi_index([doc_upper, doc_lower])
        assert len(index) == 1
        assert index["10.1/dup"]["title"] == "Second"
        assert "duplicate" in caplog.text.lower()

    # 6. Empty list returns empty dict
    def test_empty_list_returns_empty_dict(self):
        assert build_doi_index([]) == {}


def _write_metadata(tmp_path, records, total_count=None):
    """Write a minimal asset_metadata.json to tmp_path and return its path."""
    data = {
        "totalRecordCount": len(records) if total_count is None else total_count,
        "records": records,
    }
    path = tmp_path / "asset_metadata.json"
    path.write_text(json.dumps(data))
    return str(path)


class TestLoadVersoRecords:
    """Tests for load_verso_records()."""

    # 1. Valid file with 3 records returns 3 dicts with expected keys
    def test_valid_three_records(self, tmp_path):
        records = [
            {
                "originalRepository": {"assetId": 111},
                "identifier.doi": "10.1/a",
                "title": "Title A",
            },
            {
                "originalRepository": {"assetId": 222},
                "identifier.doi": "10.2/b",
                "title": "Title B",
            },
            {
                "originalRepository": {"assetId": 333},
                "identifier.doi": "10.3/c",
                "title": "Title C",
            },
        ]
        path = _write_metadata(tmp_path, records)
        result = load_verso_records(path)
        assert len(result) == 3
        assert all(set(r.keys()) == {"asset_id", "doi", "title"} for r in result)
        assert result[0] == {"asset_id": "111", "doi": "10.1/a", "title": "Title A"}
        assert result[1] == {"asset_id": "222", "doi": "10.2/b", "title": "Title B"}
        assert result[2] == {"asset_id": "333", "doi": "10.3/c", "title": "Title C"}

    # 2. Nonexistent file raises ValueError
    def test_nonexistent_file_raises_valueerror(self):
        with pytest.raises(ValueError, match="nonexistent.json"):
            load_verso_records("nonexistent.json")

    # 3. Invalid JSON raises ValueError
    def test_invalid_json_raises_valueerror(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{not valid json")
        with pytest.raises(ValueError, match="invalid JSON"):
            load_verso_records(str(path))

    # 4. Missing 'records' key raises ValueError
    def test_missing_records_key_raises_valueerror(self, tmp_path):
        path = tmp_path / "no_records.json"
        path.write_text(json.dumps({"totalRecordCount": 0}))
        with pytest.raises(ValueError, match="missing 'records' key"):
            load_verso_records(str(path))

    # 5. Record with no DOI returns doi=""
    def test_no_doi_defaults_to_empty_string(self, tmp_path):
        records = [
            {
                "originalRepository": {"assetId": 111},
                "title": "No DOI",
            },
        ]
        path = _write_metadata(tmp_path, records)
        result = load_verso_records(path)
        assert result[0]["doi"] == ""

    # 6. Integer assetId converted to string
    def test_int_asset_id_converted_to_string(self, tmp_path):
        records = [
            {
                "originalRepository": {"assetId": 12345678},
                "identifier.doi": "10.1/a",
                "title": "T",
            },
        ]
        path = _write_metadata(tmp_path, records)
        result = load_verso_records(path)
        assert result[0]["asset_id"] == "12345678"
        assert isinstance(result[0]["asset_id"], str)

    # 7. DOI normalized to lowercase and stripped
    def test_doi_normalized_lowercase_stripped(self, tmp_path):
        records = [
            {
                "originalRepository": {"assetId": 1},
                "identifier.doi": "  10.1234/ABC.Def  ",
                "title": "T",
            },
        ]
        path = _write_metadata(tmp_path, records)
        result = load_verso_records(path)
        assert result[0]["doi"] == "10.1234/abc.def"

    # 8. Missing originalRepository key -> asset_id=""
    def test_missing_original_repository_defaults_to_empty(self, tmp_path):
        records = [
            {
                "identifier.doi": "10.1/a",
                "title": "No repo",
            },
        ]
        path = _write_metadata(tmp_path, records)
        result = load_verso_records(path)
        assert result[0]["asset_id"] == ""

    # 9. Missing title key -> title=""
    def test_missing_title_defaults_to_empty(self, tmp_path):
        records = [
            {
                "originalRepository": {"assetId": 1},
                "identifier.doi": "10.1/a",
            },
        ]
        path = _write_metadata(tmp_path, records)
        result = load_verso_records(path)
        assert result[0]["title"] == ""


def _make_verso(asset_id="1", doi="10.1/a", title="Title A"):
    """Helper to build a minimal VERSO record dict."""
    return {"asset_id": asset_id, "doi": doi, "title": title}


class TestMatchRecords:
    """Tests for match_records()."""

    # 1. VERSO record DOI matches BSON index -> doi match, score 100.0
    def test_doi_match(self):
        bson_docs = [_make_doc(doi="10.1/a", abstract="Abstract A")]
        verso = [_make_verso(asset_id="1", doi="10.1/a", title="Title A")]
        result = match_records(bson_docs, verso, 90)
        assert len(result) == 1
        assert result[0]["match_method"] == "doi"
        assert result[0]["match_score"] == 100.0
        assert result[0]["asset_id"] == "1"
        assert result[0]["abstract"] == "Abstract A"

    # 2. DOI not in index, title fuzzy match >= threshold
    def test_title_fuzzy_match_above_threshold(self):
        bson_docs = [
            _make_doc(doi="10.1/other", abstract="Abstract B"),
        ]
        bson_docs[0]["title"] = "Target Title"
        verso = [_make_verso(asset_id="2", doi="10.1/nomatch", title="Target Title")]
        with patch("import_abstracts.title_match_score") as mock_score:
            mock_score.return_value = 92.0
            result = match_records(bson_docs, verso, 80)
        assert len(result) == 1
        assert result[0]["match_method"] == "title"
        assert result[0]["match_score"] == 92.0
        assert result[0]["asset_id"] == "2"
        assert result[0]["abstract"] == "Abstract B"

    # 3. DOI not in index, title below threshold -> not matched
    def test_title_below_threshold_not_matched(self):
        bson_docs = [_make_doc(doi="10.1/other", abstract="Abstract C")]
        bson_docs[0]["title"] = "Completely unrelated quantum physics paper"
        verso = [
            _make_verso(asset_id="3", doi="10.1/nomatch", title="Marine biology study")
        ]
        result = match_records(bson_docs, verso, 90)
        assert len(result) == 0

    # 4. VERSO record with no DOI and no title -> skipped
    def test_no_doi_no_title_skipped(self):
        bson_docs = [_make_doc(doi="10.1/a", abstract="Abstract D")]
        verso = [_make_verso(asset_id="4", doi="", title="")]
        result = match_records(bson_docs, verso, 90)
        assert len(result) == 0

    # 5. Multiple BSON docs match same VERSO title, scores differ by >2 -> best wins, no warning
    def test_multiple_matches_best_wins_no_warning(self, caplog):
        bson_docs = [
            _make_doc(doi="10.1/x", abstract="Abstract X"),
            _make_doc(doi="10.1/y", abstract="Abstract Y"),
        ]
        bson_docs[0]["title"] = "First Candidate"
        bson_docs[1]["title"] = "Second Candidate"
        verso = [_make_verso(asset_id="5", doi="10.1/nomatch", title="Target Title")]
        with patch("import_abstracts.title_match_score") as mock_score:

            def score_fn(local, candidate):
                if candidate == "First Candidate":
                    return 95.0
                if candidate == "Second Candidate":
                    return 85.0
                return 0.0

            mock_score.side_effect = score_fn
            with caplog.at_level(logging.WARNING):
                result = match_records(bson_docs, verso, 80)
        assert len(result) == 1
        assert result[0]["match_score"] == 95.0
        assert result[0]["abstract"] == "Abstract X"
        assert "ambiguous" not in caplog.text.lower()

    # 6. Multiple BSON docs match same VERSO title, scores within 2 points -> warning logged
    def test_ambiguous_match_logs_warning(self, caplog):
        bson_docs = [
            _make_doc(doi="10.1/x", abstract="Abstract X"),
            _make_doc(doi="10.1/y", abstract="Abstract Y"),
        ]
        bson_docs[0]["title"] = "First Candidate"
        bson_docs[1]["title"] = "Second Candidate"
        verso = [_make_verso(asset_id="6", doi="10.1/nomatch", title="Target Title")]
        with patch("import_abstracts.title_match_score") as mock_score:

            def score_fn(local, candidate):
                if candidate == "First Candidate":
                    return 92.0
                if candidate == "Second Candidate":
                    return 91.0
                return 0.0

            mock_score.side_effect = score_fn
            with caplog.at_level(logging.WARNING):
                result = match_records(bson_docs, verso, 80)
        assert len(result) == 1
        assert result[0]["match_score"] == 92.0
        assert "ambiguous" in caplog.text.lower()

    # 7. Empty BSON docs list -> empty results
    def test_empty_bson_docs(self):
        verso = [_make_verso(asset_id="7", doi="10.1/a", title="Title")]
        result = match_records([], verso, 90)
        assert result == []

    # 8. Empty VERSO records list -> empty results
    def test_empty_verso_records(self):
        bson_docs = [_make_doc(doi="10.1/a", abstract="Abstract")]
        result = match_records(bson_docs, [], 90)
        assert result == []

    # 9. VERSO record already DOI-matched is not duplicated by title pass
    def test_doi_matched_not_duplicated_by_title(self):
        bson_docs = [_make_doc(doi="10.1/a", abstract="Abstract A")]
        bson_docs[0]["title"] = "Exact Same Title"
        verso = [_make_verso(asset_id="9", doi="10.1/a", title="Exact Same Title")]
        result = match_records(bson_docs, verso, 80)
        assert len(result) == 1
        assert result[0]["match_method"] == "doi"

    # 10. Returned dict shape has exactly the 8 expected keys
    def test_returned_dict_shape(self):
        bson_docs = [_make_doc(doi="10.1/a", abstract="Abstract")]
        verso = [_make_verso(asset_id="10", doi="10.1/a", title="Title")]
        result = match_records(bson_docs, verso, 90)
        assert len(result) == 1
        expected_keys = {
            "asset_id",
            "verso_doi",
            "verso_title",
            "abstract",
            "abstract_source",
            "abstract_external_id",
            "match_method",
            "match_score",
        }
        assert set(result[0].keys()) == expected_keys


class TestWriteImportCsv:
    """Tests for write_import_csv()."""

    COLUMNS = [
        "asset_id",
        "verso_doi",
        "verso_title",
        "abstract",
        "abstract_source",
        "abstract_external_id",
        "match_method",
        "match_score",
    ]

    @staticmethod
    def _make_match(**overrides):
        """Return a match dict with sensible defaults."""
        defaults = {
            "asset_id": "1",
            "verso_doi": "10.1/a",
            "verso_title": "Title A",
            "abstract": "Some abstract text",
            "abstract_source": "s2",
            "abstract_external_id": "ext1",
            "match_method": "doi",
            "match_score": 100.0,
        }
        defaults.update(overrides)
        return defaults

    # 1. Creates CSV at path
    def test_creates_csv_at_path(self, tmp_path):
        matches = [self._make_match()]
        path = str(tmp_path / "output.csv")
        write_import_csv(matches, path)
        df = pd.read_csv(path)
        assert len(df) == 1
        assert str(df.iloc[0]["asset_id"]) == "1"
        assert df.iloc[0]["abstract"] == "Some abstract text"

    # 2. Has exactly the 8 expected columns in order
    def test_csv_has_expected_columns(self, tmp_path):
        matches = [self._make_match()]
        path = str(tmp_path / "output.csv")
        write_import_csv(matches, path)
        df = pd.read_csv(path)
        assert list(df.columns) == self.COLUMNS

    # 3. Empty matches list creates CSV with header row only
    def test_empty_matches_header_only(self, tmp_path):
        path = str(tmp_path / "empty.csv")
        write_import_csv([], path)
        df = pd.read_csv(path)
        assert len(df) == 0
        assert list(df.columns) == self.COLUMNS

    # 4. Abstract with commas and newlines properly escaped
    def test_commas_and_newlines_escaped(self, tmp_path):
        matches = [self._make_match(abstract="has, commas\nand newlines")]
        path = str(tmp_path / "special.csv")
        write_import_csv(matches, path)
        df = pd.read_csv(path)
        assert df.iloc[0]["abstract"] == "has, commas\nand newlines"

    # 5. None values written as empty string, not literal "None"
    def test_none_values_become_empty_string(self, tmp_path):
        matches = [self._make_match(abstract_external_id=None, verso_doi=None)]
        path = str(tmp_path / "nones.csv")
        write_import_csv(matches, path)
        raw = (tmp_path / "nones.csv").read_text()
        assert "None" not in raw
        df = pd.read_csv(path, keep_default_na=False)
        assert df.iloc[0]["abstract_external_id"] == ""
        assert df.iloc[0]["verso_doi"] == ""


class TestParseArgs:
    """Tests for parse_args()."""

    def test_positional_args_and_default_threshold(self):
        args = parse_args(["data.bson", "meta.json"])
        assert args.bson_path == "data.bson"
        assert args.metadata_path == "meta.json"
        assert args.threshold == 90

    def test_missing_metadata_path_raises_system_exit(self):
        with pytest.raises(SystemExit):
            parse_args(["data.bson"])

    def test_no_args_raises_system_exit(self):
        with pytest.raises(SystemExit):
            parse_args([])

    def test_custom_threshold(self):
        args = parse_args(["a.bson", "b.json", "--threshold", "85"])
        assert args.threshold == 85


@pytest.fixture
def _reset_logging():
    """Reset root logging handlers after tests that call main()."""
    yield
    root = logging.getLogger()
    for handler in root.handlers[:]:
        handler.close()
        root.removeHandler(handler)
    root.setLevel(logging.WARNING)


@pytest.mark.usefixtures("_reset_logging")
class TestMain:
    """Tests for main() orchestration."""

    @staticmethod
    def _fake_bson_docs():
        return [
            {
                "abstract": "A",
                "abstract_source": "s2",
                "abstract_external_id": "",
                "identifier_doi": "10.1/a",
                "title": "T",
            }
        ]

    @staticmethod
    def _fake_verso_records():
        return [{"asset_id": "1", "doi": "10.1/a", "title": "T"}]

    @staticmethod
    def _fake_matches():
        return [
            {
                "asset_id": "1",
                "verso_doi": "10.1/a",
                "verso_title": "T",
                "abstract": "A",
                "abstract_source": "s2",
                "abstract_external_id": "",
                "match_method": "doi",
                "match_score": 100.0,
            }
        ]

    def _mock_all(self, monkeypatch, call_order=None):
        """Wire up all mocks for a happy-path main() run."""
        if call_order is None:
            call_order = []

        def mock_parse(path):
            call_order.append("parse_bson_abstracts")
            return self._fake_bson_docs()

        def mock_load(path):
            call_order.append("load_verso_records")
            return self._fake_verso_records()

        def mock_match(bson_docs, verso_records, threshold):
            call_order.append("match_records")
            return self._fake_matches()

        def mock_write(matches, path):
            call_order.append("write_import_csv")

        monkeypatch.setattr("import_abstracts.parse_bson_abstracts", mock_parse)
        monkeypatch.setattr("import_abstracts.load_verso_records", mock_load)
        monkeypatch.setattr("import_abstracts.match_records", mock_match)
        monkeypatch.setattr("import_abstracts.write_import_csv", mock_write)

    def test_happy_path_calls_pipeline_in_order(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        call_order = []
        self._mock_all(monkeypatch, call_order)

        main(["fake.bson", "fake.json"])

        assert call_order == [
            "parse_bson_abstracts",
            "load_verso_records",
            "match_records",
            "write_import_csv",
        ]

    def test_bad_bson_path_exits(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        # Don't mock parse_bson_abstracts — let it raise on missing file
        monkeypatch.setattr(
            "import_abstracts.load_verso_records", lambda p: self._fake_verso_records()
        )
        monkeypatch.setattr(
            "import_abstracts.match_records", lambda *a: self._fake_matches()
        )
        monkeypatch.setattr("import_abstracts.write_import_csv", lambda *a: None)

        with pytest.raises(SystemExit, match="nonexistent.bson"):
            main(["nonexistent.bson", "fake.json"])

    def test_bad_metadata_path_exits(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            "import_abstracts.parse_bson_abstracts", lambda p: self._fake_bson_docs()
        )
        # Don't mock load_verso_records — let it raise on missing file

        with pytest.raises(SystemExit, match="nonexistent.json"):
            main(["fake.bson", "nonexistent.json"])

    def test_creates_timestamped_directory(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        self._mock_all(monkeypatch)

        main(["fake.bson", "fake.json"])

        c_dir = tmp_path / "C"
        assert c_dir.exists()
        subdirs = list(c_dir.iterdir())
        assert len(subdirs) == 1
        parsed = datetime.strptime(subdirs[0].name, "%Y-%m-%d_%H-%M-%S")
        assert parsed is not None

    def test_creates_log_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        self._mock_all(monkeypatch)

        main(["fake.bson", "fake.json"])

        c_dir = tmp_path / "C"
        subdirs = list(c_dir.iterdir())
        assert len(subdirs) == 1
        log_file = subdirs[0] / "logs.log"
        assert log_file.exists()

    def test_summary_stats_printed(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)

        bson_docs = self._fake_bson_docs() * 5
        verso_records = [
            {"asset_id": str(i), "doi": f"10.1/{i}", "title": f"T{i}"} for i in range(7)
        ]
        matches = [
            {
                "asset_id": str(i),
                "verso_doi": f"10.1/{i}",
                "verso_title": f"T{i}",
                "abstract": f"A{i}",
                "abstract_source": "s2",
                "abstract_external_id": "",
                "match_method": "doi",
                "match_score": 100.0,
            }
            for i in range(3)
        ] + [
            {
                "asset_id": str(i),
                "verso_doi": "",
                "verso_title": f"T{i}",
                "abstract": f"A{i}",
                "abstract_source": "s2",
                "abstract_external_id": "",
                "match_method": "title",
                "match_score": 92.0,
            }
            for i in range(3, 5)
        ]

        monkeypatch.setattr(
            "import_abstracts.parse_bson_abstracts", lambda p: bson_docs
        )
        monkeypatch.setattr(
            "import_abstracts.load_verso_records", lambda p: verso_records
        )
        monkeypatch.setattr("import_abstracts.match_records", lambda *a: matches)
        monkeypatch.setattr("import_abstracts.write_import_csv", lambda *a: None)

        main(["fake.bson", "fake.json"])

        captured = capsys.readouterr().out
        assert "Total BSON docs with abstracts: 5" in captured
        assert "Total VERSO records: 7" in captured
        assert "DOI: 3" in captured
        assert "title: 2" in captured
        assert "Unmatched: 2" in captured
