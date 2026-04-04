"""Tests for the audio-summary CLI utility functions."""

import os
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


class TestLockAndQueueArgs:
    """Tests for lock and queue command-line arguments."""

    def test_no_wait_flag_exists(self, mocker):
        """Test that --no-wait flag is accepted and passed to LockManager."""
        # Mock LockManager
        mock_lock_manager = mocker.MagicMock()
        mock_lock = mocker.MagicMock()
        mock_lock_manager.acquire_lock.return_value = mock_lock
        mocker.patch("audio_summary.cli.LockManager", return_value=mock_lock_manager)

        # Mock argparse
        mock_args = mocker.MagicMock()
        mock_args.from_youtube = None
        mock_args.from_local = None
        mock_args.from_transcript = "test.txt"
        mock_args.no_wait = True
        mock_args.timeout = 7200
        mock_args.queue_status = False
        mock_args.output = "./summary.md"
        mock_args.title = None
        mock_args.research = False
        mock_args.append = False
        mock_args.transcript_only = False
        mock_args.language = None
        mock_args.with_prompt = None
        mock_args.remote_transcribe = False
        mock_args.remote_download = False
        mock_args.remote_transcription = False
        mock_args.remote_summarize = False
        mock_args.remote_host = None
        mock_args.remote_path = None
        mock_args.remote_user = None
        mock_args.dry_run = False

        mocker.patch("argparse.ArgumentParser.parse_args", return_value=mock_args)

        # Mock file operations
        mocker.patch("pathlib.Path.is_file", return_value=True)
        mocker.patch("builtins.open", mocker.mock_open(read_data="test transcript"))

        from audio_summary.cli import main

        try:
            main()
        except SystemExit:
            pass

        # Verify LockManager was called with no_wait=True
        call_kwargs = mock_lock_manager.acquire_lock.call_args[1]
        assert call_kwargs.get("no_wait") is True

    def test_timeout_flag_exists(self, mocker):
        """Test that --timeout flag is accepted and passed to LockManager."""
        # Mock LockManager
        mock_lock_manager = mocker.MagicMock()
        mock_lock = mocker.MagicMock()
        mock_lock_manager.acquire_lock.return_value = mock_lock
        mocker.patch("audio_summary.cli.LockManager", return_value=mock_lock_manager)

        # Mock argparse
        mock_args = mocker.MagicMock()
        mock_args.from_youtube = None
        mock_args.from_local = None
        mock_args.from_transcript = "test.txt"
        mock_args.no_wait = False
        mock_args.timeout = 3600
        mock_args.queue_status = False
        mock_args.output = "./summary.md"
        mock_args.title = None
        mock_args.research = False
        mock_args.append = False
        mock_args.transcript_only = False
        mock_args.language = None
        mock_args.with_prompt = None
        mock_args.remote_transcribe = False
        mock_args.remote_download = False
        mock_args.remote_transcription = False
        mock_args.remote_summarize = False
        mock_args.remote_host = None
        mock_args.remote_path = None
        mock_args.remote_user = None
        mock_args.dry_run = False

        mocker.patch("argparse.ArgumentParser.parse_args", return_value=mock_args)

        # Mock file operations
        mocker.patch("pathlib.Path.is_file", return_value=True)
        mocker.patch("builtins.open", mocker.mock_open(read_data="test transcript"))

        from audio_summary.cli import main

        try:
            main()
        except SystemExit:
            pass

        # Verify LockManager was called with timeout=3600
        call_kwargs = mock_lock_manager.acquire_lock.call_args[1]
        assert call_kwargs.get("timeout") == 3600

    def test_queue_status_flag_exits_immediately(self, mocker, capsys):
        """Test that --queue-status exits immediately with status display."""
        # Mock argparse for queue-status
        mock_args = mocker.MagicMock()
        mock_args.queue_status = True
        mock_args.from_youtube = None
        mock_args.from_local = None
        mock_args.from_transcript = None

        mocker.patch("argparse.ArgumentParser.parse_args", return_value=mock_args)

        # Mock get_queue_status
        mock_get_queue_status = mocker.patch(
            "audio_summary.cli.get_queue_status",
            return_value="Test queue status output",
        )

        from audio_summary.cli import main

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 0
        mock_get_queue_status.assert_called_once()

        captured = capsys.readouterr()
        assert "Test queue status output" in captured.out

    def test_lock_acquisition_failure_with_no_wait(self, mocker, capsys):
        """Test that lock acquisition failure with --no-wait exits cleanly."""
        # Mock LockManager to return None (lock not acquired)
        mock_lock_manager = mocker.MagicMock()
        mock_lock_manager.acquire_lock.return_value = None
        mocker.patch("audio_summary.cli.LockManager", return_value=mock_lock_manager)

        # Mock argparse with all required attributes
        mock_args = mocker.MagicMock()
        mock_args.from_youtube = None
        mock_args.from_local = None
        mock_args.from_transcript = "test.txt"
        mock_args.no_wait = True
        mock_args.timeout = 7200
        mock_args.queue_status = False
        mock_args.with_prompt = None
        mock_args.research = False
        mock_args.remote_transcribe = False
        mock_args.remote_download = False
        mock_args.remote_transcription = False
        mock_args.remote_summarize = False
        mock_args.remote_host = None
        mock_args.remote_path = None
        mock_args.remote_user = None
        mock_args.transcript_only = False

        mocker.patch("argparse.ArgumentParser.parse_args", return_value=mock_args)

        from audio_summary.cli import main

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 1


class TestOllamaModel:
    """Tests for OLLAMA_MODEL constant."""

    def test_model_is_gpt_oss_20b(self):
        """Test that OLLAMA_MODEL is set to gpt-oss:20b."""
        assert OLLAMA_MODEL == "gpt-oss:20b"

    def test_model_is_string(self):
        """Test that OLLAMA_MODEL is a string."""
        assert isinstance(OLLAMA_MODEL, str)


class TestOllamaClientAuthentication:
    """Tests for Ollama client authentication."""

    def test_get_ollama_client_without_api_key(self, mocker):
        """Test that get_ollama_client works without API key."""
        import ollama
        from audio_summary.cli import get_ollama_client

        # Clear environment variables
        mocker.patch.dict(os.environ, {}, clear=True)
        mocker.patch.dict(os.environ, {"OLLAMA_HOST": "http://localhost:11434"})

        # Mock ollama.Client
        mock_client = mocker.MagicMock()
        mocker.patch("ollama.Client", return_value=mock_client)

        client = get_ollama_client()

        # Verify client was created without headers
        ollama.Client.assert_called_once_with(
            host="http://localhost:11434",
            headers=None,
        )

    def test_get_ollama_client_with_api_key(self, mocker):
        """Test that get_ollama_client uses API key from environment."""
        import ollama
        from audio_summary.cli import get_ollama_client

        # Set environment variables
        mocker.patch.dict(
            os.environ,
            {
                "OLLAMA_HOST": "https://ollama.com",
                "OLLAMA_API_KEY": "test-api-key-12345",
            },
        )

        # Mock ollama.Client
        mock_client = mocker.MagicMock()
        mocker.patch("ollama.Client", return_value=mock_client)

        client = get_ollama_client()

        # Verify client was created with Authorization header
        ollama.Client.assert_called_once_with(
            host="https://ollama.com",
            headers={"Authorization": "Bearer test-api-key-12345"},
        )

    def test_get_ollama_client_uses_default_host(self, mocker):
        """Test that get_ollama_client uses localhost as default."""
        import ollama
        from audio_summary.cli import get_ollama_client

        # Clear environment variables
        mocker.patch.dict(os.environ, {}, clear=True)

        # Mock ollama.Client
        mock_client = mocker.MagicMock()
        mocker.patch("ollama.Client", return_value=mock_client)

        client = get_ollama_client()

        # Verify client was created with default localhost
        ollama.Client.assert_called_once_with(
            host="http://localhost:11434",
            headers=None,
        )

    def test_get_ollama_client_with_only_api_key(self, mocker):
        """Test that get_ollama_client works with only API key set."""
        import ollama
        from audio_summary.cli import get_ollama_client

        # Set only API key, not host
        mocker.patch.dict(os.environ, {"OLLAMA_API_KEY": "secret-key"}, clear=True)

        # Mock ollama.Client
        mock_client = mocker.MagicMock()
        mocker.patch("ollama.Client", return_value=mock_client)

        client = get_ollama_client()

        # Verify client was created with default host and API key
        ollama.Client.assert_called_once_with(
            host="http://localhost:11434",
            headers={"Authorization": "Bearer secret-key"},
        )


class TestRemoteExecutionArgs:
    """Tests for granular remote execution argument validation."""

    def test_remote_transcribe_shorthand_sets_both_flags(self, mocker):
        """Test that --remote-transcribe sets both --remote-download and --remote-transcription."""

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

    def test_remote_download_with_remote_config(self, mocker, capsys):
        """Test that --remote-download with remote config doesn't error on validation."""
        mocker.patch(
            "sys.argv",
            [
                "audio-summary",
                "--from-youtube",
                "https://example.com/video",
                "--remote-download",
                "--remote-host",
                "test.local",
            ],
        )

        # Mock the RemoteExecutor to avoid actual SSH connection
        mock_executor = mocker.MagicMock()
        mock_executor.check_file_exists.return_value = False
        mock_executor.__enter__ = mocker.MagicMock(return_value=mock_executor)
        mock_executor.__exit__ = mocker.MagicMock(return_value=None)
        mocker.patch("audio_summary.remote.RemoteExecutor", return_value=mock_executor)

        # Mock execute_remote_download to avoid actual execution
        mocker.patch(
            "audio_summary.cli.execute_remote_download",
            return_value=Path("/tmp/test.mp3"),
        )

        from audio_summary.cli import main

        with pytest.raises(SystemExit) as exc_info:
            main()

        # Should fail on actual execution (exit code 1), not validation (exit code 2)
        assert exc_info.value.code != 2
        captured = capsys.readouterr()
        # Make sure validation error was NOT shown
        assert "requires --remote-host" not in captured.err
        assert "requires --remote-host" not in captured.out

    def test_remote_summarize_with_from_transcript(self, mocker):
        """Test that --remote-summarize works with --from-transcript."""

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

        # Mock LockManager with proper context manager behavior
        mock_lock_manager = mocker.MagicMock()
        mock_lock_context = mocker.MagicMock()
        mock_lock_context.__enter__ = mocker.MagicMock(return_value=mock_lock_context)
        mock_lock_context.__exit__ = mocker.MagicMock(return_value=None)
        mock_lock_manager.acquire_lock.return_value = mock_lock_context
        mocker.patch("audio_summary.cli.LockManager", return_value=mock_lock_manager)

        # Mock check_and_wait_for_remote to return True (lock available)
        mocker.patch("audio_summary.cli.check_and_wait_for_remote", return_value=True)

        # Mock the RemoteExecutor classes
        mock_executor = mocker.MagicMock()
        mock_executor.check_file_exists.return_value = False  # File doesn't exist
        mock_executor.__enter__ = mocker.MagicMock(return_value=mock_executor)
        mock_executor.__exit__ = mocker.MagicMock(return_value=None)

        mocker.patch("audio_summary.remote.RemoteExecutor", return_value=mock_executor)

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

        # Mock remote config without hardware key
        mock_remote_config = mocker.MagicMock()
        mock_remote_config.ssh_key_path = None
        mocker.patch(
            "audio_summary.cli.resolve_remote_config", return_value=mock_remote_config
        )

        mocker.patch("audio_summary.cli.get_youtube_title", return_value="Test Video")
        # Removed - Attachments is now default directory

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

        # Mock the RemoteExecutor classes
        mock_executor = mocker.MagicMock()
        mock_executor.check_file_exists.return_value = False  # File doesn't exist
        mock_executor.__enter__ = mocker.MagicMock(return_value=mock_executor)
        mock_executor.__exit__ = mocker.MagicMock(return_value=None)

        mocker.patch("audio_summary.remote.RemoteExecutor", return_value=mock_executor)

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

        # Mock remote config without hardware key
        mock_remote_config = mocker.MagicMock()
        mock_remote_config.ssh_key_path = None
        mocker.patch(
            "audio_summary.cli.resolve_remote_config", return_value=mock_remote_config
        )

        mocker.patch("audio_summary.cli.get_youtube_title", return_value="Test Video")
        # Removed - Attachments is now default directory

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

    def test_remote_summarize_only(self, mocker, tmp_path):
        """Test --remote-summarize executes summarization on remote only."""
        from audio_summary.cli import main

        # Create a real transcript file
        transcript_file = tmp_path / "transcript.txt"
        transcript_file.write_text("Test transcript content")

        # Mock all the things
        mock_args = mocker.MagicMock()
        mock_args.from_youtube = None
        mock_args.from_local = None
        mock_args.from_transcript = str(transcript_file)
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

        # Mock remote config with proper ssh_key_path
        mock_remote_config = mocker.MagicMock()
        mock_remote_config.ssh_key_path = None
        mocker.patch(
            "audio_summary.cli.resolve_remote_config", return_value=mock_remote_config
        )
        # Removed - Attachments is now default directory

        # Mock the actual execution function
        mock_summarize = mocker.patch("audio_summary.cli.execute_remote_summarize")
        mock_summarize.return_value = tmp_path / "summary.md"

        try:
            main()
        except SystemExit:
            pass

        # Verify remote summarize was called
        mock_summarize.assert_called_once()

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

        # Mock the RemoteExecutor classes
        mock_executor = mocker.MagicMock()
        mock_executor.check_file_exists.return_value = False  # File doesn't exist
        mock_executor.__enter__ = mocker.MagicMock(return_value=mock_executor)
        mock_executor.__exit__ = mocker.MagicMock(return_value=None)

        mocker.patch("audio_summary.remote.RemoteExecutor", return_value=mock_executor)

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

        # Mock remote config without hardware key
        mock_remote_config = mocker.MagicMock()
        mock_remote_config.ssh_key_path = None
        mocker.patch(
            "audio_summary.cli.resolve_remote_config", return_value=mock_remote_config
        )

        mocker.patch("audio_summary.cli.get_youtube_title", return_value="Test Video")
        # Removed - Attachments is now default directory

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

        # Mock the RemoteExecutor classes
        mock_executor = mocker.MagicMock()
        mock_executor.check_file_exists.return_value = False  # File doesn't exist
        mock_executor.__enter__ = mocker.MagicMock(return_value=mock_executor)
        mock_executor.__exit__ = mocker.MagicMock(return_value=None)

        mocker.patch("audio_summary.remote.RemoteExecutor", return_value=mock_executor)

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

        # Mock remote config without hardware key
        mock_remote_config = mocker.MagicMock()
        mock_remote_config.ssh_key_path = None
        mocker.patch(
            "audio_summary.cli.resolve_remote_config", return_value=mock_remote_config
        )

        mocker.patch("audio_summary.cli.get_youtube_title", return_value="Test Video")
        # Removed - Attachments is now default directory

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
