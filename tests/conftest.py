"""Shared pytest fixtures for the verso_pdf_export test suite."""

import bson
import pytest
import requests


@pytest.fixture
def session():
    """Provide a requests.Session for tests.

    The `responses` library intercepts HTTP calls at the adapter level,
    so a real Session works correctly under mocking.
    """
    return requests.Session()


@pytest.fixture
def sample_doi():
    """A well-formed DOI string for use in provider tests."""
    return "10.1234/example.2023"


@pytest.fixture
def sample_title():
    """A realistic paper title for use in provider tests."""
    return "A Sample Research Paper Title"


@pytest.fixture
def sample_esploro_record():
    """A realistic Esploro API record dict matching the fields used by
    extract_identifiers() and should_skip() in the harvesting scripts.
    """
    return {
        "title": "A Sample Research Paper Title",
        "description.abstract": [
            {"value": "This is the abstract text of the sample paper."}
        ],
        "originalRepository": {"assetId": 12345678},
        "identifier.doi": "10.1234/example.2023",
        "identifier.uri": "https://example.com/12345678",
        "identifier.wos": "",
        "resourceType": "journal_article",
        "publisher": "Example Academic Press",
        "date.published": "2023-06-15",
        "language": ["en"],
        "displayedDateByPriorityEsploroCP": "2023-06-15",
        "creators": [
            {
                "creatorname": "Smith, Jane",
                "almaUserId": "u123456",
                "user.primaryId": "user123@example.com",
                "additionalIdentifiers": {
                    "EXTERNAL": "EXT123",
                    "BARCODE": "BC456",
                    "Pivot": "PV789",
                    "INST_ID": "INST001",
                    "Other": "OTH002",
                },
            }
        ],
        "files": [
            {
                "file.name": "paper.pdf",
                "file.extension": "pdf",
                "fileDownloadUrl": "https://example.com/download/paper.pdf",
            }
        ],
    }


@pytest.fixture
def sample_file_task():
    """A single file-download task dict as produced by download_files()."""
    return {
        "url": "https://example.com/download/paper.pdf",
        "original_name": "paper.pdf",
        "asset_id": 12345678,
        "file_number": None,
        "file_creation_date": "2023-06-15",
        "file_size_bytes": "1024000",
        "file_order": "1",
    }


@pytest.fixture
def sample_final_output(sample_esploro_record):
    """A minimal final_output dict wrapping a single Esploro record."""
    return {"totalRecordCount": 1, "records": [sample_esploro_record]}


@pytest.fixture
def write_bson_file(tmp_path):
    """Write a list of dicts as a multi-document BSON file."""

    def _write(docs, filename="test.bson"):
        path = tmp_path / filename
        with open(path, "wb") as f:
            for doc in docs:
                f.write(bson.encode(doc))
        return str(path)

    return _write
