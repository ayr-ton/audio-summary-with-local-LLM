"""Tests for the audio-summary remote execution functionality."""

import pytest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from audio_summary.config import RemoteConfig, Config, load_config, create_remote_config
from audio_summary.remote import RemoteExecutor


class TestRemoteConfig:
    """Tests for RemoteConfig dataclass."""

    def test_remote_config_creation(self):
        """Test creating a RemoteConfig."""
        config = RemoteConfig(
            name="test", host="test.local", user="tom", path="/home/tom/audio-summary"
        )
        assert config.name == "test"
        assert config.host == "test.local"
        assert config.user == "tom"
        assert config.path == "/home/tom/audio-summary"
        assert config.max_retries == 3

    def test_remote_config_with_ssh_key(self):
        """Test RemoteConfig with SSH key."""
        config = RemoteConfig(
            name="test",
            host="test.local",
            user="tom",
            path="/home/tom/audio-summary",
            ssh_key="~/.ssh/id_ed25519",
        )
        assert config.ssh_key_path == Path.home() / ".ssh" / "id_ed25519"

    def test_remote_config_without_ssh_key(self):
        """Test RemoteConfig without SSH key."""
        config = RemoteConfig(
            name="test", host="test.local", user="tom", path="/home/tom/audio-summary"
        )
        assert config.ssh_key_path is None


class TestConfig:
    """Tests for Config dataclass."""

    def test_get_remote_by_name(self):
        """Test getting remote by name."""
        remote1 = RemoteConfig(
            name="dave", host="dave.local", user="tom", path="/path1"
        )
        remote2 = RemoteConfig(name="gpu", host="gpu.local", user="tom", path="/path2")
        config = Config(remotes={"dave": remote1, "gpu": remote2})

        result = config.get_remote("dave")
        assert result.name == "dave"
        assert result.host == "dave.local"

    def test_get_default_remote(self):
        """Test getting default remote."""
        remote = RemoteConfig(name="dave", host="dave.local", user="tom", path="/path")
        config = Config(remotes={"dave": remote}, default_remote="dave")

        result = config.get_remote()
        assert result.name == "dave"

    def test_get_remote_not_found(self):
        """Test error when remote not found."""
        config = Config(remotes={})
        with pytest.raises(ValueError, match="Remote 'missing' not found"):
            config.get_remote("missing")

    def test_get_remote_no_default(self):
        """Test error when no default and no name provided."""
        remote = RemoteConfig(name="dave", host="dave.local", user="tom", path="/path")
        config = Config(remotes={"dave": remote})
        with pytest.raises(ValueError, match="No remote specified"):
            config.get_remote()


class TestCreateRemoteConfig:
    """Tests for create_remote_config function."""

    def test_create_adhoc_config(self):
        """Test creating ad-hoc remote config."""
        config = create_remote_config(
            host="dave.local", user="tom", path="/home/tom/audio-summary"
        )
        assert config.name == "adhoc"
        assert config.host == "dave.local"
        assert config.user == "tom"
        assert config.path == "/home/tom/audio-summary"
        assert config.max_retries == 3


class TestRemoteExecutor:
    """Tests for RemoteExecutor class."""

    def test_executor_creation(self):
        """Test creating RemoteExecutor."""
        config = RemoteConfig(
            name="test", host="test.local", user="tom", path="/home/tom/audio-summary"
        )
        executor = RemoteExecutor(config)
        assert executor.config == config
        assert executor._ssh is None
        assert executor._sftp is None

    def test_execute_with_retry_success(self, mocker):
        """Test successful execution with retry."""
        config = RemoteConfig(
            name="test",
            host="test.local",
            user="tom",
            path="/home/tom/audio-summary",
            max_retries=3,
        )

        executor = RemoteExecutor(config)

        # Mock the execute method
        mock_execute = mocker.patch.object(executor, "execute")
        mock_execute.return_value = (0, "success", "")

        success, stdout, stderr = executor.execute_with_retry("ls -la")

        assert success is True
        assert stdout == "success"
        mock_execute.assert_called_once()

    def test_execute_with_retry_failure(self, mocker):
        """Test execution failure after retries."""
        config = RemoteConfig(
            name="test",
            host="test.local",
            user="tom",
            path="/home/tom/audio-summary",
            max_retries=3,
        )

        executor = RemoteExecutor(config)

        # Mock the execute method to always fail
        mock_execute = mocker.patch.object(executor, "execute")
        mock_execute.return_value = (1, "", "error")

        success, stdout, stderr = executor.execute_with_retry("ls -la")

        assert success is False
        assert stderr == "error"
        assert mock_execute.call_count == 3  # Retried 3 times

    def test_execute_with_retry_exception(self, mocker):
        """Test execution with exception."""
        config = RemoteConfig(
            name="test",
            host="test.local",
            user="tom",
            path="/home/tom/audio-summary",
            max_retries=3,
        )

        executor = RemoteExecutor(config)

        # Mock the execute method to raise exception
        mock_execute = mocker.patch.object(executor, "execute")
        mock_execute.side_effect = Exception("Connection refused")

        success, stdout, stderr = executor.execute_with_retry("ls -la")

        assert success is False
        assert "Connection refused" in stderr
        assert mock_execute.call_count == 3  # Retried 3 times

    def test_dry_run_execute(self, mocker):
        """Test dry run execution."""
        config = RemoteConfig(
            name="test", host="test.local", user="tom", path="/home/tom/audio-summary"
        )

        executor = RemoteExecutor(config)

        success, stdout, stderr = executor.execute_with_retry("ls -la", dry_run=True)

        assert success is True
        assert "[DRY-RUN]" in stdout or "[DRY-RUN]" not in stderr


class TestConfigLoading:
    """Tests for configuration loading."""

    def test_load_config_nonexistent(self, mocker, tmp_path):
        """Test loading config when file doesn't exist."""
        mocker.patch(
            "audio_summary.config.get_config_path",
            return_value=tmp_path / "nonexistent" / "config.yaml",
        )

        config = load_config()
        assert config.remotes == {}
        assert config.default_remote is None

    def test_load_config_with_remotes(self, mocker, tmp_path):
        """Test loading config with remotes."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
remotes:
  dave:
    host: dave.local
    user: tom
    path: /home/tom/audio-summary
    ssh_key: ~/.ssh/id_ed25519
    max_retries: 3
default_remote: dave
""")

        mocker.patch("audio_summary.config.get_config_path", return_value=config_file)

        config = load_config()
        assert "dave" in config.remotes
        assert config.remotes["dave"].host == "dave.local"
        assert config.default_remote == "dave"

    def test_load_config_empty(self, mocker, tmp_path):
        """Test loading empty config file."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("")

        mocker.patch("audio_summary.config.get_config_path", return_value=config_file)

        config = load_config()
        assert config.remotes == {}
        assert config.default_remote is None


class TestGranularRemoteExecution:
    """Tests for granular remote execution functions."""

    def test_execute_remote_download(self, mocker, tmp_path):
        """Test execute_remote_download function."""
        from audio_summary.cli import execute_remote_download
        from audio_summary.config import RemoteConfig

        config = RemoteConfig(
            name="test",
            host="test.local",
            user="tom",
            path="/home/tom/audio-summary",
        )

        # Create a mock for RemoteExecutor
        mock_executor_class = mocker.patch("audio_summary.cli.RemoteExecutor")
        mock_executor = mocker.MagicMock()
        mock_executor_class.return_value.__enter__.return_value = mock_executor
        mock_executor.check_file_exists.return_value = False
        mock_executor.get_file_size.return_value = 1000

        # Mock args
        mock_args = mocker.MagicMock()
        mock_args.from_youtube = "https://example.com/video"
        mock_args.dry_run = False
        mock_args.title = "Test Video"

        data_directory = tmp_path

        result = execute_remote_download(
            mock_args, config, "Test Video", data_directory
        )

        # Verify RemoteExecutor was created with correct config
        mock_executor_class.assert_called_once_with(config)

        # Verify download was executed on remote
        mock_executor.execute_with_retry.assert_called_once()

        # Verify file was downloaded
        mock_executor.download_file.assert_called_once()

    def test_execute_remote_download_file_exists(self, mocker, tmp_path):
        """Test execute_remote_download when file already exists on remote."""
        from audio_summary.cli import execute_remote_download
        from audio_summary.config import RemoteConfig

        config = RemoteConfig(
            name="test",
            host="test.local",
            user="tom",
            path="/home/tom/audio-summary",
        )

        mock_executor_class = mocker.patch("audio_summary.cli.RemoteExecutor")
        mock_executor = mocker.MagicMock()
        mock_executor_class.return_value.__enter__.return_value = mock_executor
        mock_executor.check_file_exists.return_value = True  # File exists
        mock_executor.get_file_size.return_value = 1000

        mock_args = mocker.MagicMock()
        mock_args.from_youtube = "https://example.com/video"
        mock_args.dry_run = False

        data_directory = tmp_path

        result = execute_remote_download(
            mock_args, config, "Test Video", data_directory
        )

        # Verify download was NOT executed (file exists)
        mock_executor.execute_with_retry.assert_not_called()

        # Verify file was still downloaded
        mock_executor.download_file.assert_called_once()

    def test_execute_remote_download_dry_run(self, mocker, tmp_path):
        """Test execute_remote_download in dry-run mode."""
        from audio_summary.cli import execute_remote_download
        from audio_summary.config import RemoteConfig

        config = RemoteConfig(
            name="test",
            host="test.local",
            user="tom",
            path="/home/tom/audio-summary",
        )

        mock_executor_class = mocker.patch("audio_summary.cli.RemoteExecutor")
        mock_executor = mocker.MagicMock()
        mock_executor_class.return_value.__enter__.return_value = mock_executor

        mock_args = mocker.MagicMock()
        mock_args.from_youtube = "https://example.com/video"
        mock_args.dry_run = True

        data_directory = tmp_path

        result = execute_remote_download(
            mock_args, config, "Test Video", data_directory
        )

        # Verify no actual execution or download happened
        mock_executor.execute_with_retry.assert_not_called()
        mock_executor.download_file.assert_not_called()

    def test_execute_remote_transcription_with_upload(self, mocker, tmp_path):
        """Test execute_remote_transcription uploads file when not on remote."""
        from audio_summary.cli import execute_remote_transcription
        from audio_summary.config import RemoteConfig

        config = RemoteConfig(
            name="test",
            host="test.local",
            user="tom",
            path="/home/tom/audio-summary",
        )

        mock_executor_class = mocker.patch("audio_summary.cli.RemoteExecutor")
        mock_executor = mocker.MagicMock()
        mock_executor_class.return_value.__enter__.return_value = mock_executor
        mock_executor.check_file_exists.side_effect = [
            False,
            False,
        ]  # MP3 doesn't exist, transcript doesn't exist
        mock_executor.get_file_size.return_value = 500

        mock_args = mocker.MagicMock()
        mock_args.dry_run = False

        audio_file_path = tmp_path / "test.mp3"
        audio_file_path.write_text("fake audio content")
        transcript_path = tmp_path / "test_transcript.txt"

        result = execute_remote_transcription(
            mock_args, config, audio_file_path, transcript_path, "Test Video"
        )

        # Verify MP3 was uploaded (didn't exist on remote)
        mock_executor.upload_file.assert_called_once()

        # Verify transcription was executed on remote
        mock_executor.execute_with_retry.assert_called_once()

        # Verify transcript was downloaded
        mock_executor.download_file.assert_called_once()

    def test_execute_remote_transcription_mp3_exists(self, mocker, tmp_path):
        """Test execute_remote_transcription when MP3 already exists on remote."""
        from audio_summary.cli import execute_remote_transcription
        from audio_summary.config import RemoteConfig

        config = RemoteConfig(
            name="test",
            host="test.local",
            user="tom",
            path="/home/tom/audio-summary",
        )

        mock_executor_class = mocker.patch("audio_summary.cli.RemoteExecutor")
        mock_executor = mocker.MagicMock()
        mock_executor_class.return_value.__enter__.return_value = mock_executor
        mock_executor.check_file_exists.side_effect = [
            True,
            False,
        ]  # MP3 exists, transcript doesn't
        mock_executor.get_file_size.return_value = 500

        mock_args = mocker.MagicMock()
        mock_args.dry_run = False

        audio_file_path = tmp_path / "test.mp3"
        audio_file_path.write_text("fake audio content")
        transcript_path = tmp_path / "test_transcript.txt"

        result = execute_remote_transcription(
            mock_args, config, audio_file_path, transcript_path, "Test Video"
        )

        # Verify MP3 was NOT uploaded (already exists)
        mock_executor.upload_file.assert_not_called()

        # Verify transcription was still executed
        mock_executor.execute_with_retry.assert_called_once()

        # Verify transcript was downloaded
        mock_executor.download_file.assert_called_once()

    def test_execute_remote_transcription_transcript_exists(self, mocker, tmp_path):
        """Test execute_remote_transcription when transcript already exists on remote."""
        from audio_summary.cli import execute_remote_transcription
        from audio_summary.config import RemoteConfig

        config = RemoteConfig(
            name="test",
            host="test.local",
            user="tom",
            path="/home/tom/audio-summary",
        )

        mock_executor_class = mocker.patch("audio_summary.cli.RemoteExecutor")
        mock_executor = mocker.MagicMock()
        mock_executor_class.return_value.__enter__.return_value = mock_executor
        mock_executor.check_file_exists.side_effect = [True, True]  # Both exist
        mock_executor.get_file_size.return_value = 500

        mock_args = mocker.MagicMock()
        mock_args.dry_run = False

        audio_file_path = tmp_path / "test.mp3"
        audio_file_path.write_text("fake audio content")
        transcript_path = tmp_path / "test_transcript.txt"

        result = execute_remote_transcription(
            mock_args, config, audio_file_path, transcript_path, "Test Video"
        )

        # Verify no transcription was executed (transcript exists)
        mock_executor.execute_with_retry.assert_not_called()

        # Verify transcript was still downloaded
        mock_executor.download_file.assert_called_once()

    def test_execute_remote_transcription_dry_run(self, mocker, tmp_path):
        """Test execute_remote_transcription in dry-run mode."""
        from audio_summary.cli import execute_remote_transcription
        from audio_summary.config import RemoteConfig

        config = RemoteConfig(
            name="test",
            host="test.local",
            user="tom",
            path="/home/tom/audio-summary",
        )

        mock_executor_class = mocker.patch("audio_summary.cli.RemoteExecutor")
        mock_executor = mocker.MagicMock()
        mock_executor_class.return_value.__enter__.return_value = mock_executor

        mock_args = mocker.MagicMock()
        mock_args.dry_run = True

        audio_file_path = tmp_path / "test.mp3"
        audio_file_path.write_text("fake audio content")
        transcript_path = tmp_path / "test_transcript.txt"

        result = execute_remote_transcription(
            mock_args, config, audio_file_path, transcript_path, "Test Video"
        )

        # Verify no actual operations happened
        mock_executor.upload_file.assert_not_called()
        mock_executor.execute_with_retry.assert_not_called()
        mock_executor.download_file.assert_not_called()

        # Verify empty string returned in dry-run
        assert result == ""
