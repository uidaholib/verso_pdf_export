"""Tests for import_abstracts — Phase 3."""

import logging

import pytest

from import_abstracts import build_doi_index, parse_bson_abstracts


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
