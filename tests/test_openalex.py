"""Tests for providers.openalex — reconstruct_abstract() and lookup_by_doi()."""

from unittest.mock import patch

import pytest
import responses

import providers.openalex as oa
from providers.openalex import lookup_by_doi, reconstruct_abstract


class TestReconstructAbstract:
    """Test matrix for converting OpenAlex inverted-index to plain text."""

    def test_valid_inverted_index(self):
        """Two words at sequential positions produce correct word order."""
        index = {"the": [0], "quick": [1]}
        assert reconstruct_abstract(index) == "the quick"

    def test_word_at_multiple_positions(self):
        """A word appearing at multiple positions is placed at each one."""
        index = {"the": [0, 5], "cat": [1]}
        result = reconstruct_abstract(index)
        # Positions: 0=the, 1=cat, 5=the → "the cat the"
        assert result == "the cat the"

    def test_duplicate_position_does_not_crash(self):
        """Two words mapped to the same position produces one of the words."""
        index = {"a": [0], "b": [0]}
        result = reconstruct_abstract(index)
        assert result in ("a", "b")

    def test_none_input(self):
        """None input returns empty string."""
        assert reconstruct_abstract(None) == ""

    def test_empty_dict_input(self):
        """Empty dict input returns empty string."""
        assert reconstruct_abstract({}) == ""

    def test_sparse_index_no_extra_whitespace(self):
        """Gaps in position numbers produce no extra whitespace."""
        index = {"hello": [0], "world": [2], "today": [5]}
        result = reconstruct_abstract(index)
        assert result == "hello world today"
        # No double spaces or leading/trailing whitespace
        assert "  " not in result
        assert result == result.strip()

    def test_large_realistic_index(self):
        """A ~50-word realistic abstract reconstructs to a coherent sentence."""
        # Simulate a real OpenAlex inverted-index for a short abstract
        words = (
            "We present a novel approach to automatic text summarization "
            "that combines extractive and abstractive methods using a "
            "transformer based architecture Our method achieves state of "
            "the art results on the CNN Daily Mail dataset with a ROUGE "
            "score improvement of three points over the previous best "
            "model The key innovation is a two stage pipeline that first "
            "selects salient sentences and then paraphrases them into a "
            "concise summary"
        ).split()

        inverted_index = {}
        for pos, word in enumerate(words):
            inverted_index.setdefault(word, []).append(pos)

        result = reconstruct_abstract(inverted_index)

        expected = " ".join(words)
        assert result == expected


# --- Helpers for TestLookupByDoi ---

_BASE_URL = "https://api.openalex.org/works/doi:10.1234%2Fexample.2023"

_VALID_RESPONSE_BODY = {
    "id": "https://openalex.org/W1234567890",
    "title": "A Sample Research Paper Title",
    "abstract_inverted_index": {"This": [0], "is": [1], "an": [2], "abstract": [3]},
    "display_name": "A Sample Research Paper Title",
}

_EXPECTED_SHAPED = {
    "abstract": "This is an abstract",
    "matched_title": "A Sample Research Paper Title",
    "external_id": "https://openalex.org/W1234567890",
    "source": "openalex",
}


class TestLookupByDoi:
    """Test matrix for lookup_by_doi() — OpenAlex DOI lookup with retries."""

    @pytest.fixture(autouse=True)
    def _reset_circuit_breaker(self):
        oa._consecutive_429s = 0
        oa._suspended_until = 0.0

    @responses.activate
    @patch("time.sleep")
    def test_lookup_by_doi_200_with_abstract_returns_shaped_dict(
        self, mock_sleep, session, sample_doi
    ):
        """200 with valid abstract_inverted_index returns a shaped dict."""
        responses.add(responses.GET, _BASE_URL, json=_VALID_RESPONSE_BODY, status=200)
        result = lookup_by_doi(session, sample_doi, rate_interval=0.1)
        assert result == _EXPECTED_SHAPED

    @responses.activate
    @patch("time.sleep")
    def test_lookup_by_doi_200_null_abstract_returns_none(
        self, mock_sleep, session, sample_doi
    ):
        """200 with null abstract_inverted_index returns None."""
        body = {**_VALID_RESPONSE_BODY, "abstract_inverted_index": None}
        responses.add(responses.GET, _BASE_URL, json=body, status=200)
        result = lookup_by_doi(session, sample_doi, rate_interval=0.1)
        assert result is None

    @responses.activate
    @patch("time.sleep")
    def test_lookup_by_doi_200_missing_abstract_key_returns_none(
        self, mock_sleep, session, sample_doi
    ):
        """200 with no abstract_inverted_index key returns None."""
        body = {
            "id": "https://openalex.org/W1234567890",
            "title": "A Sample Research Paper Title",
        }
        responses.add(responses.GET, _BASE_URL, json=body, status=200)
        result = lookup_by_doi(session, sample_doi, rate_interval=0.1)
        assert result is None

    @responses.activate
    @patch("time.sleep")
    def test_lookup_by_doi_404_returns_none_no_retry(
        self, mock_sleep, session, sample_doi
    ):
        """404 returns None with no retry."""
        responses.add(responses.GET, _BASE_URL, status=404)
        result = lookup_by_doi(session, sample_doi, rate_interval=0.1)
        assert result is None
        assert len(responses.calls) == 1

    @responses.activate
    @patch("time.sleep")
    def test_lookup_by_doi_429_then_200_retries_and_returns(
        self, mock_sleep, session, sample_doi
    ):
        """429 then 200 retries and returns the shaped dict."""
        responses.add(responses.GET, _BASE_URL, status=429)
        responses.add(responses.GET, _BASE_URL, json=_VALID_RESPONSE_BODY, status=200)
        result = lookup_by_doi(session, sample_doi, rate_interval=0.1)
        assert result == _EXPECTED_SHAPED
        # Check that retry backoff sleep was called with 3.0
        sleep_calls = [c.args[0] for c in mock_sleep.call_args_list]
        assert 3.0 in sleep_calls

    @responses.activate
    @patch("time.sleep")
    def test_lookup_by_doi_500_then_200_retries_and_returns(
        self, mock_sleep, session, sample_doi
    ):
        """500 then 200 retries and returns the result."""
        responses.add(responses.GET, _BASE_URL, status=500)
        responses.add(responses.GET, _BASE_URL, json=_VALID_RESPONSE_BODY, status=200)
        result = lookup_by_doi(session, sample_doi, rate_interval=0.1)
        assert result == _EXPECTED_SHAPED
        assert len(responses.calls) == 2

    @responses.activate
    @patch("time.sleep")
    def test_lookup_by_doi_429_three_times_returns_none(
        self, mock_sleep, session, sample_doi, caplog
    ):
        """Three consecutive 429s returns None and logs a warning."""
        responses.add(responses.GET, _BASE_URL, status=429)
        responses.add(responses.GET, _BASE_URL, status=429)
        responses.add(responses.GET, _BASE_URL, status=429)
        import logging

        with caplog.at_level(logging.WARNING, logger="providers.openalex"):
            result = lookup_by_doi(session, sample_doi, rate_interval=0.1)
        assert result is None
        assert any("429" in msg for msg in caplog.messages)

    @responses.activate
    @patch("time.sleep")
    def test_lookup_by_doi_empty_doi_returns_none_no_http(self, mock_sleep, session):
        """Empty DOI returns None with no HTTP call."""
        result = lookup_by_doi(session, "", rate_interval=0.1)
        assert result is None
        assert len(responses.calls) == 0

    @responses.activate
    @patch("time.sleep")
    def test_lookup_by_doi_api_key_in_request_params(
        self, mock_sleep, session, sample_doi, monkeypatch
    ):
        """API key is included in request parameters."""
        monkeypatch.setattr(oa, "OPENALEX_API_KEY", "test-key-123")
        responses.add(responses.GET, _BASE_URL, json=_VALID_RESPONSE_BODY, status=200)
        lookup_by_doi(session, sample_doi, rate_interval=0.1)
        assert "api_key=test-key-123" in responses.calls[0].request.url

    @responses.activate
    @patch("time.sleep")
    def test_lookup_by_doi_rate_interval_sleep_called(
        self, mock_sleep, session, sample_doi
    ):
        """Rate interval sleep is called with the given value."""
        responses.add(responses.GET, _BASE_URL, json=_VALID_RESPONSE_BODY, status=200)
        lookup_by_doi(session, sample_doi, rate_interval=0.5)
        mock_sleep.assert_any_call(0.5)

    @patch("time.sleep")
    def test_lookup_by_doi_connection_error_returns_none(
        self, mock_sleep, session, sample_doi, caplog
    ):
        """ConnectionError returns None and logs a warning."""
        import logging
        import requests as req

        with patch.object(
            session, "get", side_effect=req.exceptions.ConnectionError("refused")
        ):
            with caplog.at_level(logging.WARNING, logger="providers.openalex"):
                result = lookup_by_doi(session, sample_doi, rate_interval=0.1)
        assert result is None
        assert any("connection error" in msg.lower() for msg in caplog.messages)

    @patch("time.sleep")
    def test_lookup_by_doi_timeout_returns_none(
        self, mock_sleep, session, sample_doi, caplog
    ):
        """Timeout returns None and logs a warning."""
        import logging
        import requests as req

        with patch.object(
            session, "get", side_effect=req.exceptions.Timeout("timed out")
        ):
            with caplog.at_level(logging.WARNING, logger="providers.openalex"):
                result = lookup_by_doi(session, sample_doi, rate_interval=0.1)
        assert result is None
        assert any("timeout" in msg.lower() for msg in caplog.messages)

    @responses.activate
    @patch("time.sleep")
    def test_lookup_by_doi_403_then_200_retries_and_returns(
        self, mock_sleep, session, sample_doi
    ):
        """403 (per-second rate limit) then 200 retries and returns result."""
        responses.add(responses.GET, _BASE_URL, status=403)
        responses.add(responses.GET, _BASE_URL, json=_VALID_RESPONSE_BODY, status=200)
        result = lookup_by_doi(session, sample_doi, rate_interval=0.1)
        assert result == _EXPECTED_SHAPED
        assert len(responses.calls) == 2

    @responses.activate
    @patch("time.sleep")
    def test_lookup_by_doi_429_with_ratelimit_remaining_zero_no_retry(
        self, mock_sleep, session, sample_doi, caplog
    ):
        """429 with X-RateLimit-Remaining: 0 returns None without retry and logs warning."""
        import logging

        responses.add(
            responses.GET,
            _BASE_URL,
            status=429,
            headers={"X-RateLimit-Remaining": "0"},
        )
        with caplog.at_level(logging.WARNING, logger="providers.openalex"):
            result = lookup_by_doi(session, sample_doi, rate_interval=0.1)
        assert result is None
        assert len(responses.calls) == 1
        assert any("daily credits" in msg.lower() for msg in caplog.messages)
