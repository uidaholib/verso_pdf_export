"""Tests for providers.openalex — reconstruct_abstract() function."""

from providers.openalex import reconstruct_abstract


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
