"""Distributed lock and queue management for audio-summary.

This module provides file-based locking and FIFO queueing to ensure
only one audio-summary instance runs at a time (locally or remotely).
"""

import json
import os
import signal
import socket
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


@dataclass
class JobInfo:
    """Information about a queued or running job."""

    pid: int
    hostname: str
    started_at: str
    command: str
    remote_host: Optional[str]
    stage: str = "starting"
    status: str = "running"
    job_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "pid": self.pid,
            "hostname": self.hostname,
            "started_at": self.started_at,
            "command": self.command,
            "remote_host": self.remote_host,
            "stage": self.stage,
            "status": self.status,
            "job_id": self.job_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "JobInfo":
        """Create JobInfo from dictionary."""
        return cls(
            pid=data["pid"],
            hostname=data["hostname"],
            started_at=data["started_at"],
            command=data["command"],
            remote_host=data.get("remote_host"),
            stage=data.get("stage", "starting"),
            status=data.get("status", "running"),
            job_id=data.get("job_id", str(uuid.uuid4())[:8]),
        )


@dataclass
class QueueStatus:
    """Current status of the lock queue."""

    active: Optional[JobInfo]
    queue_position: int
    queue_length: int
    last_completed: Optional[JobInfo]

    def display(self) -> str:
        """Generate human-readable status report."""
        lines = ["Current Status", "=============="]

        if self.active:
            lines.append(
                f"Active: {self.active.stage} on {self.active.hostname} "
                f"({self.active.started_at})"
            )
        else:
            lines.append("Active: None")

        lines.append(f"\nQueue: {self.queue_length} job(s)")
        if self.queue_position > 0:
            lines.append(f"Your position: {self.queue_position}")

        if self.last_completed:
            lines.append(
                f"\nLast completed: {self.last_completed.stage} "
                f"({self.last_completed.started_at})"
            )

        return "\n".join(lines)


class LockManager:
    """Manage distributed locks and queues using local files.

    Uses atomic file operations for cross-platform safety.
    Lock directory structure:
        ~/.config/audio-summary/locks/
        ├── current.lock          # Symlink to active job file in lock/
        ├── queue/                # FIFO queue directory
        │   └── YYYYMMDD_HHMMSS_uuid.job
        ├── lock/                 # Active lock files
        │   └── YYYYMMDD_HHMMSS_uuid.job
        └── completed/            # Archive of completed jobs
    """

    DEFAULT_TIMEOUT = 7200  # 2 hours
    POLL_INTERVAL = 5  # seconds

    def __init__(self, lock_dir: Optional[Path] = None):
        """Initialize lock manager with lock directory."""
        if lock_dir is None:
            lock_dir = Path.home() / ".config" / "audio-summary" / "locks"
        self.lock_dir = Path(lock_dir)
        self.queue_dir = self.lock_dir / "queue"
        self.lock_files_dir = self.lock_dir / "lock"
        self.completed_dir = self.lock_dir / "completed"
        self.current_lock = self.lock_dir / "current.lock"
        self._cleanup_on_exit = False
        self._job_file: Optional[Path] = None
        self._lock_file: Optional[Path] = None

    def _ensure_directories(self) -> None:
        """Create lock directories if they don't exist."""
        self.lock_dir.mkdir(parents=True, exist_ok=True)
        self.queue_dir.mkdir(exist_ok=True)
        self.lock_files_dir.mkdir(exist_ok=True)
        self.completed_dir.mkdir(exist_ok=True)

    def _get_queue_files(self) -> list[Path]:
        """Get all queue files sorted by creation time (FIFO)."""
        if not self.queue_dir.exists():
            return []
        files = [f for f in self.queue_dir.iterdir() if f.suffix == ".job"]
        return sorted(files, key=lambda f: f.stat().st_mtime)

    def _is_process_running(self, pid: int) -> bool:
        """Check if a process is still running."""
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False

    def _read_job_info(self, job_file: Path) -> Optional[JobInfo]:
        """Read job info from a job file."""
        try:
            with open(job_file) as f:
                data = json.load(f)
            return JobInfo.from_dict(data)
        except (json.JSONDecodeError, KeyError, FileNotFoundError):
            return None

    def _write_job_info(self, job_file: Path, job_info: JobInfo) -> None:
        """Write job info to a job file atomically."""
        temp_file = job_file.with_suffix(".tmp")
        with open(temp_file, "w") as f:
            json.dump(job_info.to_dict(), f, indent=2)
        temp_file.rename(job_file)

    def _cleanup_stale_locks(self) -> None:
        """Remove stale locks from crashed processes."""
        # Check current lock
        if self.current_lock.exists() and self.current_lock.is_symlink():
            try:
                target = self.current_lock.readlink()
                job_info = self._read_job_info(target)
                if job_info and not self._is_process_running(job_info.pid):
                    print(f"Cleaning up stale lock from PID {job_info.pid}")
                    self.current_lock.unlink()
                    # Move job file to completed with failed status
                    if target.exists():
                        job_info.status = "failed"
                        job_info.stage = "crashed"
                        completed_file = self.completed_dir / target.name
                        self._write_job_info(completed_file, job_info)
                        target.unlink()
            except (OSError, FileNotFoundError):
                pass

        # Clean up orphaned queue files from crashed processes
        for job_file in self._get_queue_files():
            job_info = self._read_job_info(job_file)
            if job_info and not self._is_process_running(job_info.pid):
                print(f"Removing orphaned queue file from PID {job_info.pid}")
                job_file.unlink()

    def _acquire_lock_atomically(self, job_file: Path) -> bool:
        """Try to acquire the lock atomically.

        Moves the job file from queue/ to lock/ and creates symlink.
        """
        try:
            # Create target path in lock directory
            lock_file = self.lock_files_dir / job_file.name

            # Move job file from queue to lock (atomic on same filesystem)
            job_file.rename(lock_file)

            # Create symlink pointing to the lock file
            self.current_lock.symlink_to(lock_file)
            return True
        except FileExistsError:
            return False

    def _wait_for_lock(
        self,
        job_file: Path,
        timeout: int,
        no_wait: bool,
    ) -> bool:
        """Wait for the lock to become available."""
        if no_wait:
            return False

        start_time = time.time()
        last_position = -1

        while True:
            # Check for timeout
            elapsed = time.time() - start_time
            if elapsed >= timeout:
                print(f"\nTimeout exceeded ({timeout}s). Exiting.")
                # Clean up our queue file
                if job_file.exists():
                    job_file.unlink()
                return False

            # Check if we can acquire the lock
            if self._acquire_lock_atomically(job_file):
                return True

            # Show queue position
            queue_files = self._get_queue_files()
            try:
                position = queue_files.index(job_file) + 1
            except ValueError:
                position = len(queue_files) + 1

            if position != last_position:
                if last_position == -1:
                    print(f"Job queued: {datetime.now(timezone.utc).isoformat()}")
                print(f"↓ Position {position}")
                last_position = position

            # Wait before trying again
            time.sleep(self.POLL_INTERVAL)

            # Clean up any stale locks periodically
            if int(elapsed) % 60 == 0:
                self._cleanup_stale_locks()

    def acquire_lock(
        self,
        command: str,
        remote_host: Optional[str] = None,
        timeout: int = DEFAULT_TIMEOUT,
        no_wait: bool = False,
    ) -> Optional["LockContext"]:
        """Acquire the lock, waiting if necessary.

        Args:
            command: The command being executed
            remote_host: Remote host if using remote execution
            timeout: Maximum seconds to wait (default 2 hours)
            no_wait: If True, fail immediately if busy

        Returns:
            LockContext if lock acquired, None otherwise
        """
        self._ensure_directories()
        self._cleanup_stale_locks()

        # Check if there's already a lock
        if self.current_lock.exists():
            if no_wait:
                active_job = self.get_active_job()
                if active_job:
                    print(
                        f"Error: Another instance is running "
                        f"({active_job.stage} on {active_job.hostname})"
                    )
                else:
                    print("Error: Another instance is running")
                print("Use --queue-status to view queue.")
                return None

        # Create our job file
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        job_id = str(uuid.uuid4())[:8]
        job_filename = f"{timestamp}_{job_id}.job"
        job_file = self.queue_dir / job_filename

        job_info = JobInfo(
            pid=os.getpid(),
            hostname=socket.gethostname(),
            started_at=datetime.now(timezone.utc).isoformat(),
            command=command,
            remote_host=remote_host,
        )

        self._write_job_info(job_file, job_info)
        self._job_file = job_file
        self._cleanup_on_exit = True

        # Try to acquire immediately
        if self._acquire_lock_atomically(job_file):
            self._lock_file = self.lock_files_dir / job_filename
            print(f"→ Running: {command}")
            return LockContext(self, self._lock_file, job_info)

        # Need to wait
        if not self._wait_for_lock(job_file, timeout, no_wait):
            return None

        # Lock acquired
        self._lock_file = self.lock_files_dir / job_filename
        print(f"→ Running: {command}")
        return LockContext(self, self._lock_file, job_info)

    def get_active_job(self) -> Optional[JobInfo]:
        """Get information about the currently active job."""
        if not self.current_lock.exists() or not self.current_lock.is_symlink():
            return None

        try:
            target = self.current_lock.readlink()
            return self._read_job_info(target)
        except (OSError, FileNotFoundError):
            return None

    def get_queue_status(self) -> QueueStatus:
        """Get current queue status."""
        active = self.get_active_job()
        queue_files = self._get_queue_files()

        # Get last completed job
        last_completed = None
        if self.completed_dir.exists():
            completed_files = sorted(
                self.completed_dir.iterdir(),
                key=lambda f: f.stat().st_mtime,
                reverse=True,
            )
            if completed_files:
                last_completed = self._read_job_info(completed_files[0])

        return QueueStatus(
            active=active,
            queue_position=0,
            queue_length=len(queue_files),
            last_completed=last_completed,
        )

    def update_stage(self, stage: str) -> None:
        """Update the current stage of the active job."""
        if not self.current_lock.exists() or not self.current_lock.is_symlink():
            return

        try:
            target = self.current_lock.readlink()
            job_info = self._read_job_info(target)
            if job_info:
                job_info.stage = stage
                self._write_job_info(target, job_info)
        except (OSError, FileNotFoundError):
            pass

    def release_lock(self, lock_file: Path, job_info: JobInfo) -> None:
        """Release the lock and move job to completed."""
        if not self.current_lock.exists():
            return

        try:
            # Verify this is our lock
            target = self.current_lock.readlink()
            current_info = self._read_job_info(target)
            if current_info and current_info.job_id == job_info.job_id:
                # Update status
                job_info.status = "completed"
                job_info.stage = "finished"

                # Move to completed
                completed_file = self.completed_dir / target.name
                self._write_job_info(completed_file, job_info)

                # Remove lock
                self.current_lock.unlink()
                target.unlink()
        except (OSError, FileNotFoundError):
            pass

        self._cleanup_on_exit = False

        # Promote next job in queue
        self._promote_next_job()

    def _promote_next_job(self) -> None:
        """Promote the next job in queue to active."""
        queue_files = self._get_queue_files()
        if not queue_files:
            return

        next_job_file = queue_files[0]
        try:
            self._acquire_lock_atomically(next_job_file)
        except (OSError, FileNotFoundError):
            pass

    def cleanup(self) -> None:
        """Clean up our job file on exit."""
        if self._cleanup_on_exit and self._job_file and self._job_file.exists():
            self._job_file.unlink()


class LockContext:
    """Context manager for lock lifecycle."""

    def __init__(self, manager: LockManager, lock_file: Path, job_info: JobInfo):
        self.manager = manager
        self.lock_file = lock_file
        self.job_info = job_info
        self._released = False

        # Set up signal handlers for cleanup
        self._original_sigint = signal.signal(signal.SIGINT, self._signal_handler)
        self._original_sigterm = signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame) -> None:
        """Handle signals by releasing lock before exiting."""
        self.release()
        # Restore original handler and re-raise
        signal.signal(
            signum,
            self._original_sigint
            if signum == signal.SIGINT
            else self._original_sigterm,
        )
        os.kill(os.getpid(), signum)

    def update_stage(self, stage: str) -> None:
        """Update the current processing stage."""
        self.manager.update_stage(stage)

    def release(self) -> None:
        """Release the lock."""
        if not self._released:
            self.manager.release_lock(self.lock_file, self.job_info)
            self._released = True

            # Restore original signal handlers
            signal.signal(signal.SIGINT, self._original_sigint)
            signal.signal(signal.SIGTERM, self._original_sigterm)

    def __enter__(self) -> "LockContext":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.release()
        self.manager.cleanup()


def get_queue_status() -> str:
    """Get queue status as a formatted string."""
    manager = LockManager()
    status = manager.get_queue_status()
    return status.display()
