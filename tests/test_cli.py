"""Tests for the audio-summary CLI utility functions."""

import pytest
from datetime import datetime
from pathlib import Path
import sys

# Add src directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from audio_summary.cli import (
    sanitize_title,
    generate_filename,
    clean_thinking_chunks,
    find_obsidian_attachments,
    OLLAMA_MODEL,
    MAX_TITLE_LENGTH,
)


class TestSanitizeTitle:
    """Tests for the sanitize_title function."""

    def test_removes_special_characters(self):
        """Test that special characters are removed."""
        assert sanitize_title("Hello: World") == "Hello World"
        assert sanitize_title("Test|File") == "TestFile"
        assert sanitize_title("A/B\\C") == "ABC"
        assert sanitize_title('File"Name"') == "FileName"
        assert sanitize_title("Path<To>File") == "PathToFile"
        assert sanitize_title("Name?Yes*No") == "NameYesNo"

    def test_collapses_multiple_spaces(self):
        """Test that multiple spaces are collapsed to single space."""
        assert sanitize_title("Hello    World") == "Hello World"
        assert sanitize_title("A  B   C") == "A B C"
        assert sanitize_title("  Extra  Spaces  ") == "Extra Spaces"

    def test_strips_leading_trailing_whitespace(self):
        """Test that leading/trailing whitespace is stripped."""
        assert sanitize_title("  Hello World  ") == "Hello World"
        assert sanitize_title("\tTest\n") == "Test"

    def test_truncates_to_max_length(self):
        """Test that titles are truncated to MAX_TITLE_LENGTH."""
        long_title = "A" * 100
        result = sanitize_title(long_title)
        assert len(result) <= MAX_TITLE_LENGTH
        assert result == "A" * MAX_TITLE_LENGTH

    def test_keeps_regular_characters(self):
        """Test that regular characters are preserved."""
        assert sanitize_title("Normal Title 123") == "Normal Title 123"
        assert sanitize_title("Video_About_Python") == "Video_About_Python"
        assert sanitize_title("Test-Case") == "Test-Case"


class TestGenerateFilename:
    """Tests for the generate_filename function."""

    def test_generates_filename_with_date_prefix(self):
        """Test that filenames include today's date."""
        today = datetime.now().strftime("%Y-%m-%d")
        result = generate_filename("Test Video", ".md")
        assert result.startswith(f"{today} ")

    def test_creates_transcript_filename(self):
        """Test that transcript filenames include _transcript suffix."""
        result = generate_filename("Test Video", ".txt", is_transcript=True)
        assert "_transcript" in result
        assert result.endswith(".txt")

    def test_creates_regular_filename(self):
        """Test that regular filenames don't have _transcript suffix."""
        result = generate_filename("Test Video", ".md", is_transcript=False)
        assert "_transcript" not in result
        assert result.endswith(".md")

    def test_sanitizes_title_in_filename(self):
        """Test that title is sanitized in filename."""
        result = generate_filename("Test: Video|Name", ".mp3")
        assert ":" not in result
        assert "|" not in result


class TestCleanThinkingChunks:
    """Tests for the clean_thinking_chunks function."""

    def test_removes_thinking_tokens(self):
        """Test that <|thinking|>...<|/thinking|> blocks are removed."""
        text = "Hello <|thinking|>This is thinking<|/thinking|> World"
        result = clean_thinking_chunks(text)
        assert "<|thinking|>" not in result
        assert "<|/thinking|>" not in result
        assert "This is thinking" not in result
        assert "Hello  World" in result

    def test_removes_alternative_thinking_format(self):
        """Test that <thinking>...</thinking> blocks are removed."""
        text = "Start <thinking>thinking content</thinking> End"
        result = clean_thinking_chunks(text)
        assert "<thinking>" not in result
        assert "</thinking>" not in result
        assert "thinking content" not in result
        assert "Start  End" in result

    def test_cleans_multiple_thinking_blocks(self):
        """Test that multiple thinking blocks are removed."""
        text = "A <|thinking|>think1<|/thinking|> B <thinking>think2</thinking> C"
        result = clean_thinking_chunks(text)
        assert "think1" not in result
        assert "think2" not in result
        assert "A  B  C" in result

    def test_handles_nested_thinking(self):
        """Test that nested thinking blocks are handled."""
        text = (
            "Text <|thinking|>outer <thinking>inner</thinking> outer<|/thinking|> more"
        )
        result = clean_thinking_chunks(text)
        assert "outer" not in result and "inner" not in result

    def test_cleans_whitespace(self):
        """Test that excessive whitespace is cleaned up."""
        text = "Hello\n\n\n\nWorld"
        result = clean_thinking_chunks(text)
        assert result.count("\n\n") <= 1

    def test_handles_text_without_thinking(self):
        """Test that text without thinking blocks is unchanged."""
        text = "Just regular text"
        result = clean_thinking_chunks(text)
        assert result == "Just regular text"

    def test_returns_stripped_result(self):
        """Test that result is stripped of leading/trailing whitespace."""
        text = "  Hello World  "
        result = clean_thinking_chunks(text)
        assert result == "Hello World"


class TestFindObsidianAttachments:
    """Tests for the find_obsidian_attachments function."""

    def test_finds_attachments_in_current_dir(self, tmp_path, monkeypatch):
        """Test that Attachments folder is found in current directory."""
        monkeypatch.chdir(tmp_path)
        attachments_dir = tmp_path / "Attachments"
        attachments_dir.mkdir()

        result = find_obsidian_attachments()
        assert result == attachments_dir

    def test_finds_attachments_in_parent_dir(self, tmp_path, monkeypatch):
        """Test that Attachments folder is found in parent directory."""
        parent = tmp_path / "parent"
        parent.mkdir()
        child = parent / "child"
        child.mkdir()
        attachments = parent / "Attachments"
        attachments.mkdir()

        monkeypatch.chdir(child)
        result = find_obsidian_attachments()
        assert result == attachments

    def test_finds_attachments_in_grandparent_dir(self, tmp_path, monkeypatch):
        """Test that Attachments folder is found up to 3 levels up."""
        root = tmp_path / "root"
        root.mkdir()
        level1 = root / "level1"
        level1.mkdir()
        level2 = level1 / "level2"
        level2.mkdir()
        level3 = level2 / "level3"
        level3.mkdir()
        attachments = root / "Attachments"
        attachments.mkdir()

        monkeypatch.chdir(level3)
        result = find_obsidian_attachments()
        assert result == attachments

    def test_returns_none_when_no_attachments(self, tmp_path, monkeypatch):
        """Test that None is returned when no Attachments folder exists."""
        monkeypatch.chdir(tmp_path)
        result = find_obsidian_attachments()
        assert result is None

    def test_returns_none_when_too_deep(self, tmp_path, monkeypatch):
        """Test that None is returned when Attachments is more than 3 levels up."""
        root = tmp_path / "root"
        root.mkdir()
        level1 = root / "level1"
        level1.mkdir()
        level2 = level1 / "level2"
        level2.mkdir()
        level3 = level2 / "level3"
        level3.mkdir()
        level4 = level3 / "level4"
        level4.mkdir()
        attachments = root / "Attachments"
        attachments.mkdir()

        monkeypatch.chdir(level4)
        result = find_obsidian_attachments()
        assert result is None


class TestOllamaModel:
    """Tests for OLLAMA_MODEL constant."""

    def test_model_is_gpt_oss_20b(self):
        """Test that OLLAMA_MODEL is set to gpt-oss:20b."""
        assert OLLAMA_MODEL == "gpt-oss:20b"

    def test_model_is_string(self):
        """Test that OLLAMA_MODEL is a string."""
        assert isinstance(OLLAMA_MODEL, str)
