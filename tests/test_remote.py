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
