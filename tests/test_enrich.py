"""Smoke tests for providers.enrich — verify functions are importable and correct."""

from providers.enrich import extract_identifiers, should_skip


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
