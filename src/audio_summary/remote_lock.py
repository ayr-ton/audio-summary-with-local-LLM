"""Remote lock checking for distributed audio-summary execution.

This module provides functionality to check and wait for locks on remote
machines to prevent overloading remote resources.
"""

import json
import time
from typing import Optional

from .config import RemoteConfig
from .lock_manager import LockManager


class RemoteLockManager:
    """Manage locks on remote hosts via SSH.

    Uses SSH commands to check and wait for remote lock status.
    This is simpler than SFTP operations and works well for lock checking.
    """

    DEFAULT_TIMEOUT = 7200  # 2 hours
    POLL_INTERVAL = 5  # seconds

    def __init__(self, remote_config: RemoteConfig):
        """Initialize with remote configuration."""
        self.remote_config = remote_config

    def _get_remote_lock_command(self) -> str:
        """Get the command to check remote lock status."""
        return f"cat {self.remote_config.path}/.config/audio-summary/locks/current.lock 2>/dev/null || echo 'NO_LOCK'"

    def check_remote_lock(self, executor) -> bool:
        """Check if remote has an active lock.

        Args:
            executor: RemoteExecutor instance with active connection

        Returns:
            True if remote is locked (busy), False otherwise
        """
        try:
            cmd = self._get_remote_lock_command()
            exit_code, stdout, stderr = executor.execute(cmd, dry_run=False)

            if exit_code != 0:
                # Command failed, assume not locked
                return False

            result = stdout.strip()
            return result != "NO_LOCK" and bool(result)
        except Exception:
            # If we can't check, assume not locked to avoid blocking
            return False

    def get_remote_lock_info(self, executor) -> Optional[dict]:
        """Get information about the remote active lock.

        Args:
            executor: RemoteExecutor instance with active connection

        Returns:
            Dictionary with lock info or None if no lock
        """
        try:
            # First check if there's a lock by reading the symlink
            readlink_cmd = f"readlink {self.remote_config.path}/.config/audio-summary/locks/current.lock 2>/dev/null || echo 'NO_LOCK'"
            exit_code, stdout, stderr = executor.execute(readlink_cmd, dry_run=False)

            if exit_code != 0 or stdout.strip() == "NO_LOCK":
                return None

            target = stdout.strip()
            read_job_cmd = f"cat '{target}' 2>/dev/null || echo 'NO_JOB'"
            exit_code, stdout, stderr = executor.execute(read_job_cmd, dry_run=False)

            if exit_code != 0 or stdout.strip() == "NO_JOB":
                return None

            try:
                return json.loads(stdout)
            except json.JSONDecodeError:
                return None
        except Exception:
            return None

    def wait_for_remote_lock(
        self,
        executor,
        timeout: int = DEFAULT_TIMEOUT,
        no_wait: bool = False,
    ) -> bool:
        """Wait for remote lock to be released.

        Args:
            executor: RemoteExecutor instance with active connection
            timeout: Maximum seconds to wait
            no_wait: If True, fail immediately if remote is busy

        Returns:
            True if lock is available, False if timeout/no_wait
        """
        if no_wait:
            if self.check_remote_lock(executor):
                lock_info = self.get_remote_lock_info(executor)
                if lock_info:
                    print(
                        f"Error: Remote host {self.remote_config.host} is busy "
                        f"({lock_info.get('stage', 'unknown')} by {lock_info.get('hostname', 'unknown')})"
                    )
                else:
                    print(f"Error: Remote host {self.remote_config.host} is busy")
                return False
            return True

        start_time = time.time()
        last_message = ""

        while True:
            # Check for timeout
            elapsed = time.time() - start_time
            if elapsed >= timeout:
                print(f"\nTimeout exceeded ({timeout}s) waiting for remote. Exiting.")
                return False

            # Check remote lock
            if not self.check_remote_lock(executor):
                return True

            # Show status
            lock_info = self.get_remote_lock_info(executor)
            if lock_info:
                current = (
                    f"Waiting for remote {self.remote_config.host}: "
                    f"{lock_info.get('stage', 'unknown')} "
                    f"on {lock_info.get('hostname', 'unknown')}"
                )
            else:
                current = f"Waiting for remote {self.remote_config.host}..."

            if current != last_message:
                print(current)
                last_message = current

            # Wait before trying again
            time.sleep(self.POLL_INTERVAL)


def check_and_wait_for_remote(
    executor,
    remote_config: RemoteConfig,
    timeout: int = 7200,
    no_wait: bool = False,
) -> bool:
    """Check and wait for remote lock if needed.

    This is a convenience function that wraps RemoteLockManager.

    Args:
        executor: RemoteExecutor instance
        remote_config: Remote configuration
        timeout: Maximum seconds to wait
        no_wait: If True, fail immediately if busy

    Returns:
        True if remote is available, False otherwise
    """
    manager = RemoteLockManager(remote_config)
    return manager.wait_for_remote_lock(executor, timeout, no_wait)


def check_local_and_remote_locks(
    local_manager: LockManager,
    executor,
    remote_config: Optional[RemoteConfig],
    timeout: int = 7200,
    no_wait: bool = False,
) -> bool:
    """Check both local and remote locks.

    Args:
        local_manager: Local LockManager instance
        executor: RemoteExecutor instance (if remote_config is provided)
        remote_config: Remote configuration or None
        timeout: Maximum seconds to wait
        no_wait: If True, fail immediately if busy

    Returns:
        True if all locks are available, False otherwise
    """
    # Check local lock first
    if local_manager.current_lock.exists():
        if no_wait:
            active_job = local_manager.get_active_job()
            if active_job:
                print(
                    f"Error: Local instance is running "
                    f"({active_job.stage} on {active_job.hostname})"
                )
            else:
                print("Error: Local instance is running")
            return False
        # Local is busy and we're not no_wait, the acquire_lock will handle waiting
        pass

    # Check remote lock if applicable
    if remote_config and executor:
        return check_and_wait_for_remote(executor, remote_config, timeout, no_wait)

    return True
