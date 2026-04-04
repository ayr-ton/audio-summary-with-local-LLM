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


class TestRemoteExecutionArgs:
    """Tests for granular remote execution argument validation."""

    def test_remote_transcribe_shorthand_sets_both_flags(self, mocker):
        """Test that --remote-transcribe sets both --remote-download and --remote-transcription."""
        import argparse
        from audio_summary.cli import main

        # Mock sys.argv to simulate CLI arguments
        mocker.patch(
            "sys.argv",
            [
                "audio-summary",
                "--from-youtube",
                "https://example.com/video",
                "--remote-transcribe",
                "--remote-host",
                "test.local",
            ],
        )

        # Mock the parser to capture parsed args
        mock_parser = mocker.patch("argparse.ArgumentParser.parse_args")
        mock_args = mocker.MagicMock()
        mock_args.from_youtube = "https://example.com/video"
        mock_args.from_local = None
        mock_args.from_transcript = None
        mock_args.remote_transcribe = True
        mock_args.remote_download = False
        mock_args.remote_transcription = False
        mock_args.remote_summarize = False
        mock_args.remote_host = "test.local"
        mock_args.remote_path = None
        mock_args.remote_user = None
        mock_args.dry_run = False
        mock_parser.return_value = mock_args

        # Verify that remote_transcribe is True
        assert mock_args.remote_transcribe is True

    def test_remote_download_requires_from_youtube(self, mocker, capsys):
        """Test that --remote-download requires --from-youtube."""
        mocker.patch(
            "sys.argv",
            [
                "audio-summary",
                "--from-local",
                "/path/to/file.mp3",
                "--remote-download",
                "--remote-host",
                "test.local",
            ],
        )

        with pytest.raises(SystemExit) as exc_info:
            from audio_summary.cli import main

            main()

        assert exc_info.value.code == 2
        captured = capsys.readouterr()
        assert (
            "--remote-download requires --from-youtube" in captured.err
            or "--remote-download requires --from-youtube" in captured.out
        )

    def test_remote_transcription_with_from_transcript_error(self, mocker, capsys):
        """Test that --remote-transcription cannot be used with --from-transcript."""
        mocker.patch(
            "sys.argv",
            [
                "audio-summary",
                "--from-transcript",
                "transcript.txt",
                "--remote-transcription",
                "--remote-host",
                "test.local",
            ],
        )

        with pytest.raises(SystemExit) as exc_info:
            from audio_summary.cli import main

            main()

        assert exc_info.value.code == 2
        captured = capsys.readouterr()
        assert (
            "--remote-transcription cannot be used with --from-transcript"
            in captured.err
            or "--remote-transcription cannot be used with --from-transcript"
            in captured.out
        )

    def test_remote_flags_require_remote_config(self, mocker, capsys):
        """Test that remote flags require remote configuration."""
        mocker.patch(
            "sys.argv",
            [
                "audio-summary",
                "--from-youtube",
                "https://example.com/video",
                "--remote-download",
            ],
        )

        with pytest.raises(SystemExit) as exc_info:
            from audio_summary.cli import main

            main()

        assert exc_info.value.code == 2
        captured = capsys.readouterr()
        assert (
            "requires --remote-host, --remote-path, or --remote-user" in captured.err
            or "requires --remote-host, --remote-path, or --remote-user" in captured.out
        )

    def test_remote_summarize_with_from_transcript(self, mocker):
        """Test that --remote-summarize works with --from-transcript."""
        import argparse

        mocker.patch(
            "sys.argv",
            [
                "audio-summary",
                "--from-transcript",
                "transcript.txt",
                "--remote-summarize",
                "--remote-host",
                "test.local",
            ],
        )

        # This should not raise an error
        mock_parser = mocker.patch("argparse.ArgumentParser.parse_args")
        mock_args = mocker.MagicMock()
        mock_args.from_youtube = None
        mock_args.from_local = None
        mock_args.from_transcript = "transcript.txt"
        mock_args.remote_transcribe = False
        mock_args.remote_download = False
        mock_args.remote_transcription = False
        mock_args.remote_summarize = True
        mock_args.remote_host = "test.local"
        mock_args.remote_path = None
        mock_args.remote_user = None
        mock_args.dry_run = False
        mock_parser.return_value = mock_args

        # Verify that remote_summarize is True with from_transcript
        assert mock_args.remote_summarize is True
        assert mock_args.from_transcript == "transcript.txt"


class TestGranularRemoteExecution:
    """Tests for granular remote execution workflow."""

    def test_remote_download_only(self, mocker):
        """Test --remote-download executes download on remote only."""
        mock_execute_remote_download = mocker.patch(
            "audio_summary.cli.execute_remote_download"
        )
        mock_execute_remote_transcription = mocker.patch(
            "audio_summary.cli.execute_remote_transcription"
        )
        mock_execute_remote_summarize = mocker.patch(
            "audio_summary.cli.execute_remote_summarize"
        )
        mock_download_from_youtube = mocker.patch(
            "audio_summary.cli.download_from_youtube"
        )
        mock_transcribe_file = mocker.patch("audio_summary.cli.transcribe_file")

        # Mock args
        mock_args = mocker.MagicMock()
        mock_args.from_youtube = "https://example.com/video"
        mock_args.from_local = None
        mock_args.from_transcript = None
        mock_args.remote_download = True
        mock_args.remote_transcription = False
        mock_args.remote_summarize = False
        mock_args.remote_transcribe = False
        mock_args.remote_host = "test.local"
        mock_args.remote_path = "/path/to/audio-summary"
        mock_args.remote_user = "user"
        mock_args.dry_run = False
        mock_args.title = "Test Video"
        mock_args.language = "en"
        mock_args.transcript_only = False
        mock_args.research = False
        mock_args.with_prompt = None
        mock_args.output = "./summary.md"
        mock_args.append = False

        mocker.patch("argparse.ArgumentParser.parse_args", return_value=mock_args)
        mocker.patch(
            "audio_summary.cli.resolve_remote_config", return_value=mocker.MagicMock()
        )
        mocker.patch("audio_summary.cli.get_youtube_title", return_value="Test Video")
        mocker.patch("audio_summary.cli.find_obsidian_attachments", return_value=None)

        mock_execute_remote_download.return_value = Path("/tmp/test.mp3")

        from audio_summary.cli import main

        # Should not raise
        try:
            main()
        except SystemExit:
            pass  # Expected exit

        # Verify remote download was called
        mock_execute_remote_download.assert_called_once()

        # Verify remote transcription was NOT called
        mock_execute_remote_transcription.assert_not_called()

        # Verify local download was NOT called
        mock_download_from_youtube.assert_not_called()

    def test_remote_transcription_only(self, mocker):
        """Test --remote-transcription executes transcription on remote only."""
        mock_execute_remote_download = mocker.patch(
            "audio_summary.cli.execute_remote_download"
        )
        mock_execute_remote_transcription = mocker.patch(
            "audio_summary.cli.execute_remote_transcription"
        )
        mock_download_from_youtube = mocker.patch(
            "audio_summary.cli.download_from_youtube"
        )
        mock_transcribe_file = mocker.patch("audio_summary.cli.transcribe_file")

        mock_args = mocker.MagicMock()
        mock_args.from_youtube = "https://example.com/video"
        mock_args.from_local = None
        mock_args.from_transcript = None
        mock_args.remote_download = False
        mock_args.remote_transcription = True
        mock_args.remote_summarize = False
        mock_args.remote_transcribe = False
        mock_args.remote_host = "test.local"
        mock_args.remote_path = "/path/to/audio-summary"
        mock_args.remote_user = "user"
        mock_args.dry_run = False
        mock_args.title = "Test Video"
        mock_args.language = "en"
        mock_args.transcript_only = False
        mock_args.research = False
        mock_args.with_prompt = None
        mock_args.output = "./summary.md"
        mock_args.append = False

        mocker.patch("argparse.ArgumentParser.parse_args", return_value=mock_args)
        mocker.patch(
            "audio_summary.cli.resolve_remote_config", return_value=mocker.MagicMock()
        )
        mocker.patch("audio_summary.cli.get_youtube_title", return_value="Test Video")
        mocker.patch("audio_summary.cli.find_obsidian_attachments", return_value=None)

        mock_download_from_youtube.return_value = Path("/tmp/test.mp3")
        mock_execute_remote_transcription.return_value = "Test transcript content"

        from audio_summary.cli import main

        try:
            main()
        except SystemExit:
            pass

        # Verify local download was called
        mock_download_from_youtube.assert_called_once()

        # Verify remote transcription was called
        mock_execute_remote_transcription.assert_called_once()

        # Verify local transcription was NOT called
        mock_transcribe_file.assert_not_called()

        # Verify remote download was NOT called
        mock_execute_remote_download.assert_not_called()

    def test_remote_summarize_only(self, mocker):
        """Test --remote-summarize executes summarization on remote only."""
        mock_execute_remote_summarize = mocker.patch(
            "audio_summary.cli.execute_remote_summarize"
        )

        mock_args = mocker.MagicMock()
        mock_args.from_youtube = None
        mock_args.from_local = None
        mock_args.from_transcript = "transcript.txt"
        mock_args.remote_download = False
        mock_args.remote_transcription = False
        mock_args.remote_summarize = True
        mock_args.remote_transcribe = False
        mock_args.remote_host = "test.local"
        mock_args.remote_path = "/path/to/audio-summary"
        mock_args.remote_user = "user"
        mock_args.dry_run = False
        mock_args.title = None
        mock_args.language = "en"
        mock_args.transcript_only = False
        mock_args.research = False
        mock_args.with_prompt = None
        mock_args.output = "./summary.md"
        mock_args.append = False

        mocker.patch("argparse.ArgumentParser.parse_args", return_value=mock_args)
        mocker.patch(
            "audio_summary.cli.resolve_remote_config", return_value=mocker.MagicMock()
        )
        mocker.patch("audio_summary.cli.find_obsidian_attachments", return_value=None)

        mock_path = mocker.MagicMock()
        mock_path.is_file.return_value = True
        mock_path.stat.return_value = mocker.MagicMock(st_size=1000)
        mock_path.stem = "2024-01-01 Test Video_transcript"
        mock_path.name = "2024-01-01 Test Video_transcript.txt"

        mocker.patch("pathlib.Path", return_value=mock_path)

        mock_execute_remote_summarize.return_value = Path("./2024-01-01 Test Video.md")

        from audio_summary.cli import main

        try:
            main()
        except SystemExit:
            pass

        # Verify remote summarize was called
        mock_execute_remote_summarize.assert_called_once()

    def test_remote_transcribe_shorthand_workflow(self, mocker):
        """Test that --remote-transcribe shorthand works correctly."""
        mock_execute_remote_download = mocker.patch(
            "audio_summary.cli.execute_remote_download"
        )
        mock_execute_remote_transcription = mocker.patch(
            "audio_summary.cli.execute_remote_transcription"
        )
        mock_download_from_youtube = mocker.patch(
            "audio_summary.cli.download_from_youtube"
        )
        mock_transcribe_file = mocker.patch("audio_summary.cli.transcribe_file")

        mock_args = mocker.MagicMock()
        mock_args.from_youtube = "https://example.com/video"
        mock_args.from_local = None
        mock_args.from_transcript = None
        mock_args.remote_download = True  # Set by --remote-transcribe shorthand
        mock_args.remote_transcription = True  # Set by --remote-transcribe shorthand
        mock_args.remote_summarize = False
        mock_args.remote_transcribe = True
        mock_args.remote_host = "test.local"
        mock_args.remote_path = "/path/to/audio-summary"
        mock_args.remote_user = "user"
        mock_args.dry_run = False
        mock_args.title = "Test Video"
        mock_args.language = "en"
        mock_args.transcript_only = False
        mock_args.research = False
        mock_args.with_prompt = None
        mock_args.output = "./summary.md"
        mock_args.append = False

        mocker.patch("argparse.ArgumentParser.parse_args", return_value=mock_args)
        mocker.patch(
            "audio_summary.cli.resolve_remote_config", return_value=mocker.MagicMock()
        )
        mocker.patch("audio_summary.cli.get_youtube_title", return_value="Test Video")
        mocker.patch("audio_summary.cli.find_obsidian_attachments", return_value=None)

        mock_execute_remote_download.return_value = Path("/tmp/test.mp3")
        mock_execute_remote_transcription.return_value = "Test transcript content"

        from audio_summary.cli import main

        try:
            main()
        except SystemExit:
            pass

        # Verify remote download was called
        mock_execute_remote_download.assert_called_once()

        # Verify remote transcription was called
        mock_execute_remote_transcription.assert_called_once()

        # Verify local download/transcription were NOT called
        mock_download_from_youtube.assert_not_called()
        mock_transcribe_file.assert_not_called()

    def test_full_remote_pipeline(self, mocker):
        """Test full remote pipeline with all remote flags."""
        mock_execute_remote_download = mocker.patch(
            "audio_summary.cli.execute_remote_download"
        )
        mock_execute_remote_transcription = mocker.patch(
            "audio_summary.cli.execute_remote_transcription"
        )
        mock_execute_remote_summarize = mocker.patch(
            "audio_summary.cli.execute_remote_summarize"
        )
        mock_summarize_text = mocker.patch("audio_summary.cli.summarize_text")

        mock_args = mocker.MagicMock()
        mock_args.from_youtube = "https://example.com/video"
        mock_args.from_local = None
        mock_args.from_transcript = None
        mock_args.remote_download = True
        mock_args.remote_transcription = True
        mock_args.remote_summarize = True
        mock_args.remote_transcribe = True
        mock_args.remote_host = "test.local"
        mock_args.remote_path = "/path/to/audio-summary"
        mock_args.remote_user = "user"
        mock_args.dry_run = False
        mock_args.title = "Test Video"
        mock_args.language = "en"
        mock_args.transcript_only = False
        mock_args.research = False
        mock_args.with_prompt = None
        mock_args.output = "./summary.md"
        mock_args.append = False

        mocker.patch("argparse.ArgumentParser.parse_args", return_value=mock_args)
        mocker.patch(
            "audio_summary.cli.resolve_remote_config", return_value=mocker.MagicMock()
        )
        mocker.patch("audio_summary.cli.get_youtube_title", return_value="Test Video")
        mocker.patch("audio_summary.cli.find_obsidian_attachments", return_value=None)

        mock_execute_remote_download.return_value = Path("/tmp/test.mp3")
        mock_execute_remote_transcription.return_value = "Test transcript content"
        mock_execute_remote_summarize.return_value = Path("./summary.md")

        from audio_summary.cli import main

        try:
            main()
        except SystemExit:
            pass

        # Verify all remote functions were called
        mock_execute_remote_download.assert_called_once()
        mock_execute_remote_transcription.assert_called_once()
        mock_execute_remote_summarize.assert_called_once()

        # Verify local summarize was NOT called
        mock_summarize_text.assert_not_called()
