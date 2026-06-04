"""Tests for providers.harvester — title_matches() fuzzy comparison."""

from providers.harvester import title_matches


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
