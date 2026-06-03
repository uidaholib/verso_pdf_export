"""Shared pytest fixtures for the verso_pdf_export test suite."""

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
        "creators": [{"creatorname": "Smith, Jane", "almaUserId": "u123456"}],
        "files": [
            {
                "file.name": "paper.pdf",
                "file.extension": "pdf",
                "fileDownloadUrl": "https://example.com/download/paper.pdf",
            }
        ],
    }
