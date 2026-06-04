"""Tests for providers.harvester — title_matches() and try_providers()."""

from providers.harvester import try_providers, title_matches


class TestTitleMatches:
    """Test matrix for fuzzy title comparison."""

    def test_identical_titles(self):
        assert title_matches("Hello World", "Hello World", 90) is True

    def test_case_difference(self):
        assert title_matches("HELLO", "hello", 90) is True

    def test_unrelated_titles(self):
        assert title_matches("Quantum Physics", "Cooking Tips", 90) is False

    def test_empty_local_returns_false(self):
        assert title_matches("", "anything", 90) is False

    def test_empty_candidate_returns_false(self):
        assert title_matches("anything", "", 90) is False

    def test_score_exactly_at_threshold_returns_true(self):
        # "machine learning approach" vs "machine learning methods" scores 80.0
        assert (
            title_matches(
                "machine learning approach", "machine learning methods", threshold=80
            )
            is True
        )

    def test_score_below_threshold_returns_false(self):
        # Same pair scores 80.0, so threshold=81 should fail
        assert (
            title_matches(
                "machine learning approach", "machine learning methods", threshold=81
            )
            is False
        )


def _make_result(source="openalex", title="A Sample Research Paper Title"):
    """Helper to build a provider result dict."""
    return {
        "abstract": "Some abstract text.",
        "matched_title": title,
        "external_id": f"id-{source}",
        "source": source,
    }


class TestTryProviders:
    """Test matrix for try_providers() cascade orchestrator."""

    def test_oa_doi_hit_high_confidence(
        self, session, sample_doi, sample_title, monkeypatch
    ):
        """Test 1: OA DOI hits — returns result with reason 'ok'."""
        result = _make_result("openalex", sample_title)
        monkeypatch.setattr("providers.openalex.lookup_by_doi", lambda s, d, r: result)
        monkeypatch.setattr("providers.openalex.search_by_title", lambda s, t, r: None)
        monkeypatch.setattr("providers.s2.lookup_by_doi", lambda s, d, r: None)
        monkeypatch.setattr("providers.s2.match_by_title", lambda s, t, r: None)

        got, reason, trace = try_providers(session, sample_doi, sample_title, 0.0, 0.0)
        assert got == result
        assert reason == "ok"
        assert "oa_doi=hit" in trace

    def test_oa_doi_miss_s2_doi_hit(
        self, session, sample_doi, sample_title, monkeypatch
    ):
        """Test 2: OA DOI miss, S2 DOI hits — trace shows both."""
        s2_result = _make_result("semantic_scholar", sample_title)
        monkeypatch.setattr("providers.openalex.lookup_by_doi", lambda s, d, r: None)
        monkeypatch.setattr("providers.s2.lookup_by_doi", lambda s, d, r: s2_result)
        monkeypatch.setattr("providers.openalex.search_by_title", lambda s, t, r: None)
        monkeypatch.setattr("providers.s2.match_by_title", lambda s, t, r: None)

        got, reason, trace = try_providers(session, sample_doi, sample_title, 0.0, 0.0)
        assert got == s2_result
        assert reason == "ok"
        assert "oa_doi=miss" in trace
        assert "s2_doi=hit" in trace

    def test_both_doi_miss_oa_title_high_confidence(
        self, session, sample_doi, sample_title, monkeypatch
    ):
        """Test 3: Both DOI miss, OA title match score >= 95 — reason 'ok'."""
        # matched_title identical to sample_title → score 100
        oa_result = _make_result("openalex", sample_title)
        monkeypatch.setattr("providers.openalex.lookup_by_doi", lambda s, d, r: None)
        monkeypatch.setattr("providers.s2.lookup_by_doi", lambda s, d, r: None)
        monkeypatch.setattr(
            "providers.openalex.search_by_title", lambda s, t, r: oa_result
        )
        monkeypatch.setattr("providers.s2.match_by_title", lambda s, t, r: None)

        got, reason, trace = try_providers(session, sample_doi, sample_title, 0.0, 0.0)
        assert got == oa_result
        assert reason == "ok"

    def test_both_doi_miss_oa_title_low_confidence(
        self, session, sample_doi, monkeypatch
    ):
        """Test 4: Both DOI miss, OA title match score >= 90 but < 95 — reason 'low_confidence'."""
        # "A comprehensive study of machine learning" vs
        # "A comprehensive study of deep learning" scores 93.0 — in [90, 95)
        local_title = "A comprehensive study of machine learning"
        matched_title = "A comprehensive study of deep learning"
        oa_result = _make_result("openalex", matched_title)
        monkeypatch.setattr("providers.openalex.lookup_by_doi", lambda s, d, r: None)
        monkeypatch.setattr("providers.s2.lookup_by_doi", lambda s, d, r: None)
        monkeypatch.setattr(
            "providers.openalex.search_by_title", lambda s, t, r: oa_result
        )
        monkeypatch.setattr("providers.s2.match_by_title", lambda s, t, r: None)

        got, reason, trace = try_providers(session, sample_doi, local_title, 0.0, 0.0)
        assert got == oa_result
        assert reason == "low_confidence"

    def test_oa_title_below_threshold_s2_title_high_confidence(
        self, session, sample_doi, monkeypatch
    ):
        """Test 5: OA title below threshold, S2 title match >= 95 — reason 'ok'."""
        local_title = "A Sample Research Paper Title"
        oa_result = _make_result("openalex", "Completely Different Title")
        s2_result = _make_result("semantic_scholar", local_title)

        monkeypatch.setattr("providers.openalex.lookup_by_doi", lambda s, d, r: None)
        monkeypatch.setattr("providers.s2.lookup_by_doi", lambda s, d, r: None)
        monkeypatch.setattr(
            "providers.openalex.search_by_title", lambda s, t, r: oa_result
        )
        monkeypatch.setattr("providers.s2.match_by_title", lambda s, t, r: s2_result)

        # OA title will fail fuzzy match (unrelated title), S2 will match perfectly
        got, reason, trace = try_providers(session, sample_doi, local_title, 0.0, 0.0)
        assert got == s2_result
        assert reason == "ok"

    def test_oa_title_below_threshold_s2_title_low_confidence(
        self, session, sample_doi, monkeypatch
    ):
        """Test 6: OA title below threshold, S2 title match >= 90 but < 95 — reason 'low_confidence'."""
        # OA returns unrelated title (will fail fuzzy match),
        # S2 returns title scoring 93.0 against local (in [90, 95))
        local_title = "A comprehensive study of machine learning"
        oa_result = _make_result("openalex", "Completely Different Title")
        s2_result = _make_result(
            "semantic_scholar", "A comprehensive study of deep learning"
        )

        monkeypatch.setattr("providers.openalex.lookup_by_doi", lambda s, d, r: None)
        monkeypatch.setattr("providers.s2.lookup_by_doi", lambda s, d, r: None)
        monkeypatch.setattr(
            "providers.openalex.search_by_title", lambda s, t, r: oa_result
        )
        monkeypatch.setattr("providers.s2.match_by_title", lambda s, t, r: s2_result)

        got, reason, trace = try_providers(session, sample_doi, local_title, 0.0, 0.0)
        assert got == s2_result
        assert reason == "low_confidence"

    def test_all_four_providers_miss(
        self, session, sample_doi, sample_title, monkeypatch
    ):
        """Test 7: All four providers miss — returns (None, 'no_match', trace)."""
        monkeypatch.setattr("providers.openalex.lookup_by_doi", lambda s, d, r: None)
        monkeypatch.setattr("providers.s2.lookup_by_doi", lambda s, d, r: None)
        monkeypatch.setattr("providers.openalex.search_by_title", lambda s, t, r: None)
        monkeypatch.setattr("providers.s2.match_by_title", lambda s, t, r: None)

        got, reason, trace = try_providers(session, sample_doi, sample_title, 0.0, 0.0)
        assert got is None
        assert reason == "no_match"
        assert len(trace) == 4  # all four steps recorded

    def test_no_doi_skips_doi_lookups(self, session, sample_title, monkeypatch):
        """Test 8: No DOI provided — skips DOI lookups, goes straight to title search."""
        oa_doi_called = []
        s2_doi_called = []
        oa_result = _make_result("openalex", sample_title)

        monkeypatch.setattr(
            "providers.openalex.lookup_by_doi",
            lambda s, d, r: oa_doi_called.append(1) or None,
        )
        monkeypatch.setattr(
            "providers.s2.lookup_by_doi",
            lambda s, d, r: s2_doi_called.append(1) or None,
        )
        monkeypatch.setattr(
            "providers.openalex.search_by_title", lambda s, t, r: oa_result
        )
        monkeypatch.setattr("providers.s2.match_by_title", lambda s, t, r: None)

        got, reason, trace = try_providers(session, "", sample_title, 0.0, 0.0)
        assert got == oa_result
        assert reason == "ok"
        assert len(oa_doi_called) == 0
        assert len(s2_doi_called) == 0

    def test_no_doi_no_title_returns_immediately(self, session):
        """Test 9: No DOI and no title — returns (None, 'no_match', []) immediately."""
        got, reason, trace = try_providers(session, "", "", 0.0, 0.0)
        assert got is None
        assert reason == "no_match"
        assert trace == []

    def test_oa_doi_raises_exception_falls_through(
        self, session, sample_doi, sample_title, monkeypatch
    ):
        """Test 10: OA DOI raises exception — logs warning, falls through."""
        s2_result = _make_result("semantic_scholar", sample_title)

        def oa_doi_explode(s, d, r):
            raise ConnectionError("network down")

        monkeypatch.setattr("providers.openalex.lookup_by_doi", oa_doi_explode)
        monkeypatch.setattr("providers.s2.lookup_by_doi", lambda s, d, r: s2_result)
        monkeypatch.setattr("providers.openalex.search_by_title", lambda s, t, r: None)
        monkeypatch.setattr("providers.s2.match_by_title", lambda s, t, r: None)

        got, reason, trace = try_providers(session, sample_doi, sample_title, 0.0, 0.0)
        assert got == s2_result
        assert reason == "ok"
        assert "oa_doi=error" in trace

    def test_all_providers_raise_exceptions(
        self, session, sample_doi, sample_title, monkeypatch
    ):
        """Test 11: All providers raise exceptions — returns (None, 'no_match', trace)."""

        def explode(s, *args):
            raise RuntimeError("boom")

        monkeypatch.setattr("providers.openalex.lookup_by_doi", explode)
        monkeypatch.setattr("providers.s2.lookup_by_doi", explode)
        monkeypatch.setattr("providers.openalex.search_by_title", explode)
        monkeypatch.setattr("providers.s2.match_by_title", explode)

        got, reason, trace = try_providers(session, sample_doi, sample_title, 0.0, 0.0)
        assert got is None
        assert reason == "no_match"
        assert len(trace) == 4

    def test_doi_hit_always_ok_no_title_matching(
        self, session, sample_doi, monkeypatch
    ):
        """Test 12: DOI-based hit — reason is always 'ok' regardless of title."""
        # DOI hit with a completely different matched_title — still 'ok'
        result = _make_result("openalex", "Completely Different Title")
        monkeypatch.setattr("providers.openalex.lookup_by_doi", lambda s, d, r: result)
        monkeypatch.setattr("providers.s2.lookup_by_doi", lambda s, d, r: None)
        monkeypatch.setattr("providers.openalex.search_by_title", lambda s, t, r: None)
        monkeypatch.setattr("providers.s2.match_by_title", lambda s, t, r: None)

        got, reason, trace = try_providers(
            session, sample_doi, "Some Local Title", 0.0, 0.0
        )
        assert got == result
        assert reason == "ok"
