"""Tests for the lock_manager module."""

import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from audio_summary.lock_manager import (
    JobInfo,
    LockContext,
    LockManager,
    QueueStatus,
    get_queue_status,
)


class TestJobInfo:
    """Tests for JobInfo dataclass."""

    def test_to_dict(self):
        """Test converting JobInfo to dictionary."""
        job = JobInfo(
            pid=12345,
            hostname="test-host",
            started_at="2026-01-15T14:30:52Z",
            command="audio-summary --test",
            remote_host="remote.example.com",
            stage="downloading",
            status="running",
            job_id="abc123",
        )

        data = job.to_dict()
        assert data["pid"] == 12345
        assert data["hostname"] == "test-host"
        assert data["command"] == "audio-summary --test"
        assert data["remote_host"] == "remote.example.com"
        assert data["stage"] == "downloading"
        assert data["status"] == "running"
        assert data["job_id"] == "abc123"

    def test_from_dict(self):
        """Test creating JobInfo from dictionary."""
        data = {
            "pid": 12345,
            "hostname": "test-host",
            "started_at": "2026-01-15T14:30:52Z",
            "command": "audio-summary --test",
            "remote_host": "remote.example.com",
            "stage": "downloading",
            "status": "running",
            "job_id": "abc123",
        }

        job = JobInfo.from_dict(data)
        assert job.pid == 12345
        assert job.hostname == "test-host"
        assert job.command == "audio-summary --test"
        assert job.remote_host == "remote.example.com"
        assert job.stage == "downloading"
        assert job.status == "running"
        assert job.job_id == "abc123"

    def test_from_dict_with_defaults(self):
        """Test JobInfo.from_dict with missing optional fields."""
        data = {
            "pid": 12345,
            "hostname": "test-host",
            "started_at": "2026-01-15T14:30:52Z",
            "command": "audio-summary --test",
            "remote_host": None,
        }

        job = JobInfo.from_dict(data)
        assert job.stage == "starting"  # Default value
        assert job.status == "running"  # Default value
        assert job.job_id is not None  # Should be generated


class TestQueueStatus:
    """Tests for QueueStatus dataclass."""

    def test_display_with_active_job(self):
        """Test display with an active job."""
        active_job = JobInfo(
            pid=12345,
            hostname="test-host",
            started_at="2026-01-15T14:30:52Z",
            command="audio-summary --test",
            remote_host=None,
            stage="transcribing",
        )

        status = QueueStatus(
            active=active_job,
            queue_position=0,
            queue_length=2,
            last_completed=None,
        )

        display = status.display()
        assert "Active: transcribing on test-host" in display
        assert "Queue: 2 job(s)" in display

    def test_display_without_active_job(self):
        """Test display without an active job."""
        status = QueueStatus(
            active=None,
            queue_position=1,
            queue_length=3,
            last_completed=None,
        )

        display = status.display()
        assert "Active: None" in display
        assert "Queue: 3 job(s)" in display
        assert "Your position: 1" in display


class TestLockManager:
    """Tests for LockManager class."""

    @pytest.fixture
    def temp_lock_dir(self):
        """Create a temporary lock directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def lock_manager(self, temp_lock_dir):
        """Create a LockManager with temp directory."""
        return LockManager(temp_lock_dir)

    def test_ensure_directories_creates_structure(self, lock_manager):
        """Test that _ensure_directories creates the correct structure."""
        lock_manager._ensure_directories()

        assert lock_manager.lock_dir.exists()
        assert lock_manager.queue_dir.exists()
        assert lock_manager.lock_files_dir.exists()
        assert lock_manager.completed_dir.exists()

    def test_is_process_running_with_running_process(self, lock_manager):
        """Test _is_process_running with actual running process (self)."""
        assert lock_manager._is_process_running(os.getpid()) is True

    def test_is_process_running_with_dead_process(self, lock_manager):
        """Test _is_process_running with non-existent PID."""
        # Use a very high PID that's unlikely to exist
        assert lock_manager._is_process_running(999999) is False

    def test_read_job_info_valid(self, lock_manager, temp_lock_dir):
        """Test reading valid job info from file."""
        lock_manager._ensure_directories()
        job_file = temp_lock_dir / "queue" / "test.job"

        job_info = JobInfo(
            pid=12345,
            hostname="test-host",
            started_at="2026-01-15T14:30:52Z",
            command="test command",
            remote_host=None,
        )

        lock_manager._write_job_info(job_file, job_info)
        read_info = lock_manager._read_job_info(job_file)

        assert read_info is not None
        assert read_info.pid == 12345
        assert read_info.hostname == "test-host"

    def test_read_job_info_invalid(self, lock_manager, temp_lock_dir):
        """Test reading invalid job info returns None."""
        lock_manager._ensure_directories()
        job_file = temp_lock_dir / "queue" / "test.job"

        job_file.write_text("not valid json")
        read_info = lock_manager._read_job_info(job_file)

        assert read_info is None

    def test_read_job_info_missing(self, lock_manager, temp_lock_dir):
        """Test reading missing job info returns None."""
        job_file = temp_lock_dir / "queue" / "nonexistent.job"
        read_info = lock_manager._read_job_info(job_file)

        assert read_info is None

    def test_get_queue_files_empty(self, lock_manager, temp_lock_dir):
        """Test getting queue files from empty queue."""
        lock_manager._ensure_directories()
        files = lock_manager._get_queue_files()

        assert files == []

    def test_get_queue_files_sorted(self, lock_manager, temp_lock_dir):
        """Test that queue files are returned in sorted order."""
        lock_manager._ensure_directories()
        import time

        # Create files with different timestamps (by creation order)
        file1 = lock_manager.queue_dir / "20260115_143000_abc.job"
        file2 = lock_manager.queue_dir / "20260115_143100_def.job"
        file3 = lock_manager.queue_dir / "20260115_143200_ghi.job"

        file1.touch()
        time.sleep(0.01)  # Small delay to ensure different mtimes
        file2.touch()
        time.sleep(0.01)
        file3.touch()

        files = lock_manager._get_queue_files()
        assert len(files) == 3
        # Files should be sorted by mtime (oldest first)
        assert files[0].name == "20260115_143000_abc.job"
        assert files[1].name == "20260115_143100_def.job"
        assert files[2].name == "20260115_143200_ghi.job"

    def test_acquire_lock_immediate_success(self, lock_manager, temp_lock_dir):
        """Test acquiring lock when no other lock exists."""
        lock_manager._ensure_directories()

        lock = lock_manager.acquire_lock(
            command="test command",
            remote_host=None,
            timeout=5,
            no_wait=False,
        )

        assert lock is not None
        assert lock_manager.current_lock.exists()
        # The lock should point to a file in the lock directory
        assert lock_manager.current_lock.is_symlink()
        target = lock_manager.current_lock.readlink()
        assert target.exists()
        assert target.parent == lock_manager.lock_files_dir

        # Clean up
        lock.release()

    def test_acquire_lock_no_wait_when_busy(self, lock_manager, temp_lock_dir):
        """Test that no_wait fails when another instance has lock."""
        lock_manager._ensure_directories()

        # Create an existing lock
        lock_manager.current_lock.symlink_to(temp_lock_dir / "queue" / "existing.job")

        # Create the job file that the lock points to
        existing_job = temp_lock_dir / "queue" / "existing.job"
        existing_job.parent.mkdir(parents=True, exist_ok=True)
        existing_job_info = JobInfo(
            pid=os.getpid(),
            hostname="test-host",
            started_at=datetime.now(timezone.utc).isoformat(),
            command="existing command",
            remote_host=None,
        )
        lock_manager._write_job_info(existing_job, existing_job_info)

        lock = lock_manager.acquire_lock(
            command="test command",
            remote_host=None,
            timeout=5,
            no_wait=True,
        )

        assert lock is None

    def test_acquire_lock_creates_job_file(self, lock_manager, temp_lock_dir):
        """Test that acquiring lock creates a job file."""
        lock_manager._ensure_directories()

        lock = lock_manager.acquire_lock(
            command="test command",
            remote_host=None,
            timeout=5,
            no_wait=False,
        )

        assert lock is not None
        # Lock should be created and point to a file in lock directory
        assert lock_manager.current_lock.exists()
        target = lock_manager.current_lock.readlink()
        assert target.exists()
        assert target.parent == lock_manager.lock_files_dir

        lock.release()

    def test_get_active_job_with_lock(self, lock_manager, temp_lock_dir):
        """Test getting active job when lock exists."""
        lock_manager._ensure_directories()

        # Create job file
        job_file = temp_lock_dir / "queue" / "active.job"
        job_info = JobInfo(
            pid=os.getpid(),
            hostname="test-host",
            started_at=datetime.now(timezone.utc).isoformat(),
            command="active command",
            remote_host=None,
        )
        lock_manager._write_job_info(job_file, job_info)

        # Create lock symlink
        lock_manager.current_lock.symlink_to(job_file)

        active = lock_manager.get_active_job()
        assert active is not None
        assert active.command == "active command"

    def test_get_active_job_no_lock(self, lock_manager, temp_lock_dir):
        """Test getting active job when no lock exists."""
        lock_manager._ensure_directories()

        active = lock_manager.get_active_job()
        assert active is None

    def test_cleanup_stale_locks_removes_dead(self, lock_manager, temp_lock_dir):
        """Test cleanup of stale locks from dead processes."""
        lock_manager._ensure_directories()

        # Create a job file pointing to a dead PID
        job_file = temp_lock_dir / "queue" / "stale.job"
        job_info = JobInfo(
            pid=999999,  # Non-existent PID
            hostname="test-host",
            started_at=datetime.now(timezone.utc).isoformat(),
            command="stale command",
            remote_host=None,
        )
        lock_manager._write_job_info(job_file, job_info)
        lock_manager.current_lock.symlink_to(job_file)

        # Cleanup should remove the stale lock
        lock_manager._cleanup_stale_locks()

        assert not lock_manager.current_lock.exists()

    def test_get_queue_status_empty(self, lock_manager, temp_lock_dir):
        """Test getting queue status with empty queue."""
        lock_manager._ensure_directories()

        status = lock_manager.get_queue_status()
        assert status.active is None
        assert status.queue_length == 0
        assert status.last_completed is None

    def test_get_queue_status_with_jobs(self, lock_manager, temp_lock_dir):
        """Test getting queue status with jobs in queue."""
        lock_manager._ensure_directories()

        # Create some queue files
        for i in range(3):
            job_file = lock_manager.queue_dir / f"20260115_14300{i}_test{i}.job"
            job_info = JobInfo(
                pid=10000 + i,
                hostname="test-host",
                started_at=datetime.now(timezone.utc).isoformat(),
                command=f"command {i}",
                remote_host=None,
            )
            lock_manager._write_job_info(job_file, job_info)

        status = lock_manager.get_queue_status()
        assert status.queue_length == 3
        assert status.active is None


class TestLockContext:
    """Tests for LockContext class."""

    @pytest.fixture
    def temp_lock_dir(self):
        """Create a temporary lock directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def lock_context(self, temp_lock_dir):
        """Create a LockContext for testing."""
        manager = LockManager(temp_lock_dir)
        manager._ensure_directories()

        # Acquire lock to create a proper lock file
        lock = manager.acquire_lock(
            command="test command",
            remote_host=None,
            timeout=5,
            no_wait=False,
        )
        return lock

    def test_lock_context_as_context_manager(self, temp_lock_dir):
        """Test LockContext as context manager."""
        manager = LockManager(temp_lock_dir)
        manager._ensure_directories()

        # Acquire lock - this returns a LockContext
        lock = manager.acquire_lock(
            command="test command",
            remote_host=None,
            timeout=5,
            no_wait=False,
        )

        assert lock is not None
        assert manager.current_lock.exists()
        # Verify the lock points to the lock_files_dir
        assert manager.current_lock.is_symlink()
        target = manager.current_lock.readlink()
        assert target.parent == manager.lock_files_dir

        # Exit context
        with lock:
            pass

        # Lock should be released
        assert not manager.current_lock.exists()

    def test_update_stage(self, temp_lock_dir):
        """Test updating job stage."""
        manager = LockManager(temp_lock_dir)
        manager._ensure_directories()

        lock = manager.acquire_lock(
            command="test command",
            remote_host=None,
            timeout=5,
            no_wait=False,
        )

        assert lock is not None

        lock.update_stage("transcribing")

        # Check that stage was updated
        active = manager.get_active_job()
        assert active is not None
        assert active.stage == "transcribing"

        lock.release()


class TestGetQueueStatus:
    """Tests for get_queue_status function."""

    @pytest.fixture
    def temp_lock_dir(self):
        """Create a temporary lock directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @patch("audio_summary.lock_manager.LockManager")
    def test_get_queue_status_returns_string(self, mock_manager_class):
        """Test that get_queue_status returns a formatted string."""
        mock_manager = MagicMock()
        mock_manager_class.return_value = mock_manager

        mock_status = MagicMock()
        mock_status.display.return_value = "Test status output"
        mock_manager.get_queue_status.return_value = mock_status

        result = get_queue_status()
        assert result == "Test status output"
