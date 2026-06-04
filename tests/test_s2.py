"""Tests for providers.s2 — lookup_by_doi() and match_by_title() for the Semantic Scholar API."""

import logging
from unittest.mock import patch

import responses

import providers.s2 as s2
from providers.s2 import lookup_by_doi, match_by_title


# --- Helpers ---

_BASE_URL = "https://api.semanticscholar.org/graph/v1/paper/DOI:10.1234%2Fexample.2023"

_VALID_RESPONSE_BODY = {
    "paperId": "abc123def456",
    "title": "A Sample Research Paper Title",
    "abstract": "This is an abstract from Semantic Scholar.",
    "externalIds": {"DOI": "10.1234/example.2023", "CorpusId": 999999},
}

_EXPECTED_SHAPED = {
    "abstract": "This is an abstract from Semantic Scholar.",
    "matched_title": "A Sample Research Paper Title",
    "external_id": "abc123def456",
    "source": "semantic_scholar",
}


class TestLookupByDoi:
    """Test matrix for lookup_by_doi() — Semantic Scholar DOI lookup with retries."""

    # 1. 200 with abstract → returns shaped dict
    @responses.activate
    @patch("time.sleep")
    def test_200_with_abstract_returns_shaped_dict(
        self, mock_sleep, session, sample_doi
    ):
        """200 with abstract present returns a shaped dict."""
        responses.add(responses.GET, _BASE_URL, json=_VALID_RESPONSE_BODY, status=200)
        result = lookup_by_doi(session, sample_doi, rate_interval=0)
        assert result == _EXPECTED_SHAPED

    # 2. 200 but abstract is null → returns None
    @responses.activate
    @patch("time.sleep")
    def test_200_null_abstract_returns_none(self, mock_sleep, session, sample_doi):
        """200 with abstract=null returns None."""
        body = {**_VALID_RESPONSE_BODY, "abstract": None}
        responses.add(responses.GET, _BASE_URL, json=body, status=200)
        result = lookup_by_doi(session, sample_doi, rate_interval=0)
        assert result is None

    # 3. 200 but abstract key missing entirely → returns None
    @responses.activate
    @patch("time.sleep")
    def test_200_missing_abstract_key_returns_none(
        self, mock_sleep, session, sample_doi
    ):
        """200 with no abstract key returns None."""
        body = {
            "paperId": "abc123def456",
            "title": "A Sample Research Paper Title",
            "externalIds": {"DOI": "10.1234/example.2023"},
        }
        responses.add(responses.GET, _BASE_URL, json=body, status=200)
        result = lookup_by_doi(session, sample_doi, rate_interval=0)
        assert result is None

    # 4. 404 → returns None, no retry
    @responses.activate
    @patch("time.sleep")
    def test_404_returns_none_no_retry(self, mock_sleep, session, sample_doi):
        """404 returns None with no retry."""
        responses.add(responses.GET, _BASE_URL, status=404)
        result = lookup_by_doi(session, sample_doi, rate_interval=0)
        assert result is None
        assert len(responses.calls) == 1

    # 5. 429 with Retry-After header, then 200 → sleeps Retry-After seconds
    @responses.activate
    @patch("time.sleep")
    def test_429_with_retry_after_header_then_200(
        self, mock_sleep, session, sample_doi
    ):
        """429 with Retry-After header sleeps that many seconds, then retries."""
        responses.add(
            responses.GET, _BASE_URL, status=429, headers={"Retry-After": "7"}
        )
        responses.add(responses.GET, _BASE_URL, json=_VALID_RESPONSE_BODY, status=200)
        result = lookup_by_doi(session, sample_doi, rate_interval=0)
        assert result == _EXPECTED_SHAPED
        sleep_calls = [c.args[0] for c in mock_sleep.call_args_list]
        assert 7.0 in sleep_calls

    # 6. 429 without Retry-After, then 200 → uses fallback backoff
    @responses.activate
    @patch("time.sleep")
    def test_429_without_retry_after_uses_fallback_backoff(
        self, mock_sleep, session, sample_doi
    ):
        """429 without Retry-After header uses fallback backoff schedule."""
        responses.add(responses.GET, _BASE_URL, status=429)
        responses.add(responses.GET, _BASE_URL, json=_VALID_RESPONSE_BODY, status=200)
        result = lookup_by_doi(session, sample_doi, rate_interval=0)
        assert result == _EXPECTED_SHAPED
        sleep_calls = [c.args[0] for c in mock_sleep.call_args_list]
        # First fallback backoff value is 3.0
        assert 3.0 in sleep_calls

    # 7. 500 then 200 → retries, returns result
    @responses.activate
    @patch("time.sleep")
    def test_500_then_200_retries_and_returns(self, mock_sleep, session, sample_doi):
        """500 then 200 retries and returns the result."""
        responses.add(responses.GET, _BASE_URL, status=500)
        responses.add(responses.GET, _BASE_URL, json=_VALID_RESPONSE_BODY, status=200)
        result = lookup_by_doi(session, sample_doi, rate_interval=0)
        assert result == _EXPECTED_SHAPED
        assert len(responses.calls) == 2

    # 8. API key present → x-api-key header included
    @responses.activate
    @patch("time.sleep")
    def test_api_key_present_includes_header(
        self, mock_sleep, session, sample_doi, monkeypatch
    ):
        """When S2_API_KEY is set, x-api-key header is included in the request."""
        monkeypatch.setattr(s2, "S2_API_KEY", "test-s2-key-abc")
        responses.add(responses.GET, _BASE_URL, json=_VALID_RESPONSE_BODY, status=200)
        result = lookup_by_doi(session, sample_doi, rate_interval=0)
        assert result == _EXPECTED_SHAPED
        assert responses.calls[0].request.headers["x-api-key"] == "test-s2-key-abc"

    # 9. API key absent → no x-api-key header
    @responses.activate
    @patch("time.sleep")
    def test_api_key_absent_no_header(
        self, mock_sleep, session, sample_doi, monkeypatch
    ):
        """When S2_API_KEY is empty, x-api-key header is not included."""
        monkeypatch.setattr(s2, "S2_API_KEY", "")
        responses.add(responses.GET, _BASE_URL, json=_VALID_RESPONSE_BODY, status=200)
        result = lookup_by_doi(session, sample_doi, rate_interval=0)
        assert result == _EXPECTED_SHAPED
        assert "x-api-key" not in responses.calls[0].request.headers

    # 10. Empty DOI → returns None immediately
    @responses.activate
    @patch("time.sleep")
    def test_empty_doi_returns_none_no_http(self, mock_sleep, session):
        """Empty DOI returns None with no HTTP call."""
        result = lookup_by_doi(session, "", rate_interval=0)
        assert result is None
        assert len(responses.calls) == 0

    # 11. rate_interval parameter → time.sleep called
    @responses.activate
    @patch("time.sleep")
    def test_rate_interval_sleep_called(self, mock_sleep, session, sample_doi):
        """Rate interval sleep is called with the given value."""
        responses.add(responses.GET, _BASE_URL, json=_VALID_RESPONSE_BODY, status=200)
        lookup_by_doi(session, sample_doi, rate_interval=1.0)
        mock_sleep.assert_any_call(1.0)

    # 12. ConnectionError → returns None, logs warning
    @patch("time.sleep")
    def test_connection_error_returns_none_logs_warning(
        self, mock_sleep, session, sample_doi, caplog
    ):
        """ConnectionError returns None and logs a warning."""
        import requests as req

        with patch.object(
            session, "get", side_effect=req.exceptions.ConnectionError("refused")
        ):
            with caplog.at_level(logging.WARNING, logger="providers.s2"):
                result = lookup_by_doi(session, sample_doi, rate_interval=0)
        assert result is None
        assert any("connection error" in msg.lower() for msg in caplog.messages)


# --- match_by_title helpers ---

_MATCH_URL = "https://api.semanticscholar.org/graph/v1/paper/search/match"

_MATCH_RESPONSE_BODY = {
    **_VALID_RESPONSE_BODY,
    "matchScore": 95.7,
}


class TestMatchByTitle:
    """Test matrix for match_by_title() — Semantic Scholar title match endpoint."""

    # 1. Match endpoint returns result with abstract → shaped dict
    @responses.activate
    @patch("time.sleep")
    def test_match_returns_shaped_dict(self, mock_sleep, session, sample_title):
        """200 with abstract returns a shaped dict; matchScore logged, not in output."""
        responses.add(responses.GET, _MATCH_URL, json=_MATCH_RESPONSE_BODY, status=200)
        result = match_by_title(session, sample_title, rate_interval=0)
        assert result == _EXPECTED_SHAPED
        assert "matchScore" not in result

    # 2. Match endpoint returns 404 (no match) → returns None
    @responses.activate
    @patch("time.sleep")
    def test_404_no_match_returns_none(self, mock_sleep, session, sample_title):
        """404 (no match found) returns None."""
        responses.add(responses.GET, _MATCH_URL, status=404)
        result = match_by_title(session, sample_title, rate_interval=0)
        assert result is None
        assert len(responses.calls) == 1

    # 3. Empty title → returns None immediately
    @responses.activate
    @patch("time.sleep")
    def test_empty_title_returns_none_no_http(self, mock_sleep, session):
        """Empty title returns None with no HTTP call."""
        result = match_by_title(session, "", rate_interval=0)
        assert result is None
        assert len(responses.calls) == 0

    # 4. 429 with Retry-After, then 200 → honors header, returns result
    @responses.activate
    @patch("time.sleep")
    def test_429_with_retry_after_then_200(self, mock_sleep, session, sample_title):
        """429 with Retry-After header sleeps that many seconds, then retries."""
        responses.add(
            responses.GET, _MATCH_URL, status=429, headers={"Retry-After": "7"}
        )
        responses.add(responses.GET, _MATCH_URL, json=_MATCH_RESPONSE_BODY, status=200)
        result = match_by_title(session, sample_title, rate_interval=0)
        assert result == _EXPECTED_SHAPED
        sleep_calls = [c.args[0] for c in mock_sleep.call_args_list]
        assert 7.0 in sleep_calls

    # 5. 500 then 200 → retries, returns result
    @responses.activate
    @patch("time.sleep")
    def test_500_then_200_retries_and_returns(self, mock_sleep, session, sample_title):
        """500 then 200 retries and returns the result."""
        responses.add(responses.GET, _MATCH_URL, status=500)
        responses.add(responses.GET, _MATCH_URL, json=_MATCH_RESPONSE_BODY, status=200)
        result = match_by_title(session, sample_title, rate_interval=0)
        assert result == _EXPECTED_SHAPED
        assert len(responses.calls) == 2

    # 6. ConnectionError → returns None, logs warning
    @patch("time.sleep")
    def test_connection_error_returns_none_logs_warning(
        self, mock_sleep, session, sample_title, caplog
    ):
        """ConnectionError returns None and logs a warning."""
        import requests as req

        with patch.object(
            session, "get", side_effect=req.exceptions.ConnectionError("refused")
        ):
            with caplog.at_level(logging.WARNING, logger="providers.s2"):
                result = match_by_title(session, sample_title, rate_interval=0)
        assert result is None
        assert any("connection error" in msg.lower() for msg in caplog.messages)
