"""Tests for the remote_lock module."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from audio_summary.remote_lock import (
    RemoteLockManager,
    check_and_wait_for_remote,
    check_local_and_remote_locks,
)


class TestRemoteLockManager:
    """Tests for RemoteLockManager class."""

    @pytest.fixture
    def mock_remote_config(self):
        """Create a mock RemoteConfig."""
        config = MagicMock()
        config.host = "test.example.com"
        config.path = "/home/user/audio-summary"
        config.user = "user"
        config.max_retries = 3
        return config

    @pytest.fixture
    def mock_executor(self):
        """Create a mock RemoteExecutor."""
        executor = MagicMock()
        return executor

    def test_check_remote_lock_not_locked(self, mock_remote_config, mock_executor):
        """Test check_remote_lock when remote is not locked."""
        # Setup mock to return NO_LOCK
        mock_executor.execute.return_value = (0, "NO_LOCK", "")

        manager = RemoteLockManager(mock_remote_config)
        result = manager.check_remote_lock(mock_executor)

        assert result is False
        mock_executor.execute.assert_called_once()

    def test_check_remote_lock_is_locked(self, mock_remote_config, mock_executor):
        """Test check_remote_lock when remote is locked."""
        # Setup mock to return a lock file path
        mock_executor.execute.return_value = (
            0,
            "/home/user/.config/audio-summary/locks/current.lock",
            "",
        )

        manager = RemoteLockManager(mock_remote_config)
        result = manager.check_remote_lock(mock_executor)

        assert result is True

    def test_check_remote_lock_command_failure(self, mock_remote_config, mock_executor):
        """Test check_remote_lock handles command failure."""
        # Setup mock to return error
        mock_executor.execute.return_value = (1, "", "Permission denied")

        manager = RemoteLockManager(mock_remote_config)
        result = manager.check_remote_lock(mock_executor)

        # Should return False (not locked) when command fails
        assert result is False

    def test_get_remote_lock_info_success(self, mock_remote_config, mock_executor):
        """Test getting remote lock info successfully."""
        # Setup mocks for the sequence of commands
        job_info = {
            "pid": 12345,
            "hostname": "remote-host",
            "started_at": "2026-01-15T14:30:52Z",
            "command": "audio-summary --from-youtube test",
            "remote_host": None,
            "stage": "transcribing",
            "status": "running",
            "job_id": "abc123",
        }

        # Sequence of command responses (readlink then cat)
        mock_executor.execute.side_effect = [
            (0, "/path/to/job.job", ""),  # readlink response
            (0, json.dumps(job_info), ""),  # cat job file response
        ]

        manager = RemoteLockManager(mock_remote_config)
        result = manager.get_remote_lock_info(mock_executor)

        assert result is not None
        assert result["pid"] == 12345
        assert result["stage"] == "transcribing"

    def test_get_remote_lock_info_no_lock(self, mock_remote_config, mock_executor):
        """Test getting remote lock info when no lock exists."""
        # Setup mock to return NO_LOCK
        mock_executor.execute.return_value = (0, "NO_LOCK", "")

        manager = RemoteLockManager(mock_remote_config)
        result = manager.get_remote_lock_info(mock_executor)

        assert result is None

    def test_get_remote_lock_info_invalid_json(self, mock_remote_config, mock_executor):
        """Test getting remote lock info with invalid JSON."""
        # Setup mocks for the sequence of commands
        mock_executor.execute.side_effect = [
            (0, "/path/to/job.job", ""),  # readlink response
            (0, "not valid json", ""),  # cat job file returns invalid JSON
        ]

        manager = RemoteLockManager(mock_remote_config)
        result = manager.get_remote_lock_info(mock_executor)

        assert result is None

    def test_wait_for_remote_lock_available(self, mock_remote_config, mock_executor):
        """Test waiting for remote lock when available immediately."""
        # Setup mock to return not locked
        mock_executor.execute.return_value = (0, "NO_LOCK", "")

        manager = RemoteLockManager(mock_remote_config)
        result = manager.wait_for_remote_lock(mock_executor, timeout=5, no_wait=False)

        assert result is True

    def test_wait_for_remote_lock_no_wait(self, mock_remote_config, mock_executor):
        """Test no_wait option for remote lock."""
        # Setup mock to return locked
        mock_executor.execute.return_value = (
            0,
            "/home/user/.config/audio-summary/locks/current.lock",
            "",
        )

        manager = RemoteLockManager(mock_remote_config)
        result = manager.wait_for_remote_lock(mock_executor, timeout=5, no_wait=True)

        assert result is False

    @patch("audio_summary.remote_lock.time.sleep")
    @patch("audio_summary.remote_lock.time.time")
    def test_wait_for_remote_lock_timeout(
        self, mock_time, mock_sleep, mock_remote_config, mock_executor
    ):
        """Test timeout behavior for remote lock."""
        # Setup time to simulate timeout
        mock_time.side_effect = [0, 0, 7201]  # Start, check, timeout

        # Always return locked
        mock_executor.execute.return_value = (
            0,
            "/home/user/.config/audio-summary/locks/current.lock",
            "",
        )

        manager = RemoteLockManager(mock_remote_config)
        result = manager.wait_for_remote_lock(
            mock_executor, timeout=7200, no_wait=False
        )

        assert result is False


class TestCheckAndWaitForRemote:
    """Tests for check_and_wait_for_remote function."""

    def test_check_and_wait_available(self):
        """Test check_and_wait_for_remote when remote is available."""
        mock_executor = MagicMock()
        mock_config = MagicMock()
        mock_config.host = "test.example.com"

        # Setup mock to return not locked
        mock_executor.execute.return_value = (0, "NO_LOCK", "")

        result = check_and_wait_for_remote(mock_executor, mock_config, timeout=5)
        assert result is True

    def test_check_and_wait_not_available(self):
        """Test check_and_wait_for_remote when remote is busy."""
        mock_executor = MagicMock()
        mock_config = MagicMock()
        mock_config.host = "test.example.com"

        # Setup mock to return locked
        mock_executor.execute.return_value = (
            0,
            "/home/user/.config/audio-summary/locks/current.lock",
            "",
        )

        result = check_and_wait_for_remote(
            mock_executor, mock_config, timeout=5, no_wait=True
        )
        assert result is False


class TestCheckLocalAndRemoteLocks:
    """Tests for check_local_and_remote_locks function."""

    def test_local_lock_only_no_wait(self):
        """Test check_local_and_remote_locks with local lock only."""
        mock_local_manager = MagicMock()
        mock_local_manager.current_lock.exists.return_value = True

        mock_active_job = MagicMock()
        mock_active_job.stage = "transcribing"
        mock_active_job.hostname = "local-host"
        mock_local_manager.get_active_job.return_value = mock_active_job

        result = check_local_and_remote_locks(
            mock_local_manager, None, None, timeout=5, no_wait=True
        )

        assert result is False

    def test_local_lock_only_wait(self):
        """Test check_local_and_remote_locks with local lock waiting."""
        mock_local_manager = MagicMock()
        mock_local_manager.current_lock.exists.return_value = False

        result = check_local_and_remote_locks(
            mock_local_manager, None, None, timeout=5, no_wait=False
        )

        assert result is True

    def test_with_remote_lock_available(self):
        """Test check_local_and_remote_locks with available remote."""
        mock_local_manager = MagicMock()
        mock_local_manager.current_lock.exists.return_value = False

        mock_executor = MagicMock()
        mock_remote_config = MagicMock()

        # Setup mock to return not locked
        mock_executor.execute.return_value = (0, "NO_LOCK", "")

        result = check_local_and_remote_locks(
            mock_local_manager,
            mock_executor,
            mock_remote_config,
            timeout=5,
            no_wait=True,
        )

        assert result is True

    def test_with_remote_lock_busy(self):
        """Test check_local_and_remote_locks with busy remote."""
        mock_local_manager = MagicMock()
        mock_local_manager.current_lock.exists.return_value = False

        mock_executor = MagicMock()
        mock_remote_config = MagicMock()
        mock_remote_config.host = "remote.example.com"

        # Setup mock to return locked
        mock_executor.execute.return_value = (
            0,
            "/home/user/.config/audio-summary/locks/current.lock",
            "",
        )

        result = check_local_and_remote_locks(
            mock_local_manager,
            mock_executor,
            mock_remote_config,
            timeout=5,
            no_wait=True,
        )

        assert result is False
