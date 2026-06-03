"""Tests for providers.openalex — reconstruct_abstract(), lookup_by_doi(), and search_by_title()."""

import time
from unittest.mock import patch

import pytest
import responses

import providers.openalex as oa
from providers.openalex import lookup_by_doi, reconstruct_abstract, search_by_title


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


class TestCircuitBreaker:
    """Tests for the module-wide circuit breaker that suspends requests
    after repeated 429 failures to avoid burning API credits."""

    @pytest.fixture(autouse=True)
    def _reset_circuit_breaker(self):
        oa._consecutive_429s = 0
        oa._suspended_until = 0.0

    @responses.activate
    @patch("time.sleep")
    def test_circuit_trips_after_3_exhausted_retry_calls(
        self, mock_sleep, session, sample_doi
    ):
        """After 3 calls each exhaust retries on 429, the 4th call returns
        None immediately without making any HTTP request."""
        # Each call makes 1 initial request + 3 retries = 4 requests.
        # 3 calls × 4 requests = 12 responses, all 429.
        for _ in range(12):
            responses.add(responses.GET, _BASE_URL, status=429)
        # A 13th response that should never be reached
        responses.add(responses.GET, _BASE_URL, json=_VALID_RESPONSE_BODY, status=200)

        # Each call exhausts 3 retries and returns None
        for i in range(3):
            result = lookup_by_doi(session, sample_doi, rate_interval=0.1)
            assert result is None, f"Call {i + 1} should return None"

        assert oa._consecutive_429s == 3
        assert oa._suspended_until > 0.0

        # 4th call should be blocked by circuit breaker — no HTTP request
        result = lookup_by_doi(session, sample_doi, rate_interval=0.1)
        assert result is None
        assert len(responses.calls) == 12  # no additional request was made

    @responses.activate
    @patch("time.sleep")
    def test_circuit_resets_after_cooldown_period(
        self, mock_sleep, session, sample_doi
    ):
        """After the cooldown period elapses, requests resume normally
        and a successful response resets the circuit breaker counter."""
        oa._consecutive_429s = 3
        oa._suspended_until = time.monotonic() - 1  # cooldown already expired

        responses.add(responses.GET, _BASE_URL, json=_VALID_RESPONSE_BODY, status=200)

        result = lookup_by_doi(session, sample_doi, rate_interval=0.1)

        assert result == _EXPECTED_SHAPED
        assert len(responses.calls) == 1
        assert oa._consecutive_429s == 0
        assert oa._suspended_until == 0.0

    @patch("time.sleep")
    def test_circuit_is_module_wide_affects_search_by_title(self, mock_sleep, session):
        """When the circuit is open, search_by_title also returns None
        immediately — the circuit breaker is module-wide, not per-function."""
        from providers.openalex import search_by_title

        oa._consecutive_429s = 3
        oa._suspended_until = time.monotonic() + 300

        result = search_by_title(session, "Some Title", rate_interval=0.1)
        assert result is None

    @responses.activate
    @patch("time.sleep")
    def test_successful_call_resets_counter(self, mock_sleep, session, sample_doi):
        """A successful 200 response resets _consecutive_429s to 0,
        preventing the circuit from tripping prematurely."""
        oa._consecutive_429s = 2  # one failure away from tripping

        responses.add(responses.GET, _BASE_URL, json=_VALID_RESPONSE_BODY, status=200)

        result = lookup_by_doi(session, sample_doi, rate_interval=0.1)
        assert result == _EXPECTED_SHAPED
        assert oa._consecutive_429s == 0


# --- Helpers for TestSearchByTitle ---

_SEARCH_BASE_URL = "https://api.openalex.org/works"

_SEARCH_RESPONSE_BODY = {"results": [_VALID_RESPONSE_BODY]}

_SEARCH_EMPTY_RESPONSE = {"results": []}


class TestSearchByTitle:
    """Test matrix for search_by_title() — OpenAlex title search with retries."""

    @pytest.fixture(autouse=True)
    def _reset_circuit_breaker(self):
        oa._consecutive_429s = 0
        oa._suspended_until = 0.0

    @responses.activate
    @patch("time.sleep")
    def test_search_200_with_results_returns_shaped_dict(self, mock_sleep, session):
        """200 with results containing abstract_inverted_index returns shaped dict."""
        responses.add(
            responses.GET, _SEARCH_BASE_URL, json=_SEARCH_RESPONSE_BODY, status=200
        )
        result = search_by_title(session, "My Paper", rate_interval=0)
        assert result == _EXPECTED_SHAPED

    @responses.activate
    @patch("time.sleep")
    def test_search_200_empty_results_returns_none(self, mock_sleep, session):
        """200 with empty results list returns None."""
        responses.add(
            responses.GET, _SEARCH_BASE_URL, json=_SEARCH_EMPTY_RESPONSE, status=200
        )
        result = search_by_title(session, "Nonexistent Paper", rate_interval=0)
        assert result is None

    @responses.activate
    @patch("time.sleep")
    def test_search_429_then_200_retries_and_returns(self, mock_sleep, session):
        """429 then 200 retries and returns the shaped dict."""
        responses.add(responses.GET, _SEARCH_BASE_URL, status=429)
        responses.add(
            responses.GET, _SEARCH_BASE_URL, json=_SEARCH_RESPONSE_BODY, status=200
        )
        result = search_by_title(session, "My Paper", rate_interval=0)
        assert result == _EXPECTED_SHAPED
        sleep_calls = [c.args[0] for c in mock_sleep.call_args_list]
        assert 3.0 in sleep_calls

    @responses.activate
    @patch("time.sleep")
    def test_search_500_retries_with_same_pattern(self, mock_sleep, session):
        """500 then 200 retries and returns the result."""
        responses.add(responses.GET, _SEARCH_BASE_URL, status=500)
        responses.add(
            responses.GET, _SEARCH_BASE_URL, json=_SEARCH_RESPONSE_BODY, status=200
        )
        result = search_by_title(session, "My Paper", rate_interval=0)
        assert result == _EXPECTED_SHAPED
        assert len(responses.calls) == 2

    @responses.activate
    @patch("time.sleep")
    def test_search_empty_title_returns_none_no_http(self, mock_sleep, session):
        """Empty title returns None with no HTTP call."""
        result = search_by_title(session, "", rate_interval=0)
        assert result is None
        assert len(responses.calls) == 0

    @patch("time.sleep")
    def test_search_circuit_breaker_open_returns_none(self, mock_sleep, session):
        """When circuit breaker is open, returns None immediately."""
        oa._consecutive_429s = 3
        oa._suspended_until = time.monotonic() + 300
        result = search_by_title(session, "My Paper", rate_interval=0)
        assert result is None
