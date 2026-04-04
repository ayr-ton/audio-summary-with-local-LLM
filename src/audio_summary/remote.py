"""Remote execution using paramiko."""

import os
import time
from pathlib import Path
from typing import Optional, Callable

import paramiko
from tqdm import tqdm

from .config import RemoteConfig


class RemoteExecutor:
    """Execute commands and transfer files via SSH/SFTP."""

    def __init__(self, config: RemoteConfig):
        self.config = config
        self._ssh: Optional[paramiko.SSHClient] = None
        self._sftp: Optional[paramiko.SFTPClient] = None

    def connect(self) -> None:
        """Establish SSH connection."""
        self._ssh = paramiko.SSHClient()
        self._ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        connect_kwargs = {
            "hostname": self.config.host,
            "username": self.config.user,
            "allow_agent": False,  # Disable SSH agent to avoid public_blob errors
            "look_for_keys": False,  # Don't look for keys in default locations
        }

        if self.config.ssh_key_path:
            connect_kwargs["key_filename"] = str(self.config.ssh_key_path)
        else:
            # If no key specified, try to use SSH agent but catch errors
            connect_kwargs["allow_agent"] = True
            connect_kwargs["look_for_keys"] = True

        try:
            self._ssh.connect(**connect_kwargs)
        except AttributeError as e:
            if "public_blob" in str(e):
                # Retry without agent if public_blob error occurs
                print(
                    "Retrying connection without SSH agent due to key compatibility issue..."
                )
                connect_kwargs["allow_agent"] = False
                connect_kwargs["look_for_keys"] = False
                # Try to find a key file
                for key_file in [
                    "~/.ssh/id_ed25519",
                    "~/.ssh/id_rsa",
                    "~/.ssh/id_ecdsa",
                ]:
                    key_path = Path(key_file).expanduser()
                    if key_path.exists():
                        connect_kwargs["key_filename"] = str(key_path)
                        break
                self._ssh.connect(**connect_kwargs)
            else:
                raise

        self._sftp = self._ssh.open_sftp()

    def disconnect(self) -> None:
        """Close SSH connection."""
        if self._sftp:
            self._sftp.close()
        if self._ssh:
            self._ssh.close()

    def check_file_exists(self, remote_path: str) -> bool:
        """Check if a file exists on remote."""
        try:
            self._sftp.stat(remote_path)
            return True
        except FileNotFoundError:
            return False

    def execute(
        self,
        command: str,
        cwd: Optional[str] = None,
        progress_callback: Optional[Callable[[str], None]] = None,
        dry_run: bool = False,
    ) -> tuple[int, str, str]:
        """
        Execute command on remote.

        Returns: (exit_code, stdout, stderr)
        """
        if dry_run:
            full_cmd = f"cd {cwd} && {command}" if cwd else command
            print(f"[DRY-RUN] Would execute: {full_cmd}")
            return 0, "", ""

        if cwd:
            command = f"cd {cwd} && {command}"

        stdin, stdout, stderr = self._ssh.exec_command(command)

        # Read output with progress indication
        exit_code = stdout.channel.recv_exit_status()
        out = stdout.read().decode("utf-8")
        err = stderr.read().decode("utf-8")

        return exit_code, out, err

    def upload_file(
        self,
        local_path: Path,
        remote_path: str,
        progress_bar: Optional[tqdm] = None,
        dry_run: bool = False,
    ) -> None:
        """Upload file via SFTP."""
        if dry_run:
            print(f"[DRY-RUN] Would upload: {local_path} -> {remote_path}")
            return

        if progress_bar:
            # SFTP with progress callback
            def callback(sent: int, total: int) -> None:
                progress_bar.update(sent - progress_bar.n)

            self._sftp.put(str(local_path), remote_path, callback=callback)
            progress_bar.close()
        else:
            self._sftp.put(str(local_path), remote_path)

    def download_file(
        self,
        remote_path: str,
        local_path: Path,
        progress_bar: Optional[tqdm] = None,
        dry_run: bool = False,
    ) -> None:
        """Download file via SFTP."""
        if dry_run:
            print(f"[DRY-RUN] Would download: {remote_path} -> {local_path}")
            return

        if progress_bar:

            def callback(received: int, total: int) -> None:
                progress_bar.update(received - progress_bar.n)

            self._sftp.get(remote_path, str(local_path), callback=callback)
            progress_bar.close()
        else:
            self._sftp.get(remote_path, str(local_path))

    def execute_with_retry(
        self,
        command: str,
        cwd: Optional[str] = None,
        max_retries: Optional[int] = None,
        dry_run: bool = False,
    ) -> tuple[bool, str, str]:
        """
        Execute with automatic retry.

        Returns: (success, stdout, stderr)
        """
        if max_retries is None:
            max_retries = self.config.max_retries

        last_stdout = ""
        last_stderr = ""

        for attempt in range(max_retries):
            try:
                exit_code, stdout, stderr = self.execute(command, cwd, dry_run=dry_run)

                last_stdout = stdout
                last_stderr = stderr

                if exit_code == 0:
                    return True, stdout, stderr

                # Command failed but no exception
                if attempt < max_retries - 1:
                    print(
                        f"Attempt {attempt + 1} failed (exit {exit_code}), retrying..."
                    )
                    time.sleep(2**attempt)  # Exponential backoff

            except Exception as e:
                last_stderr = str(e)
                if attempt < max_retries - 1:
                    print(f"Attempt {attempt + 1} error: {e}, retrying...")
                    time.sleep(2**attempt)
                else:
                    return False, "", str(e)

        return False, last_stdout, last_stderr

    def get_file_size(self, remote_path: str) -> int:
        """Get file size for progress tracking."""
        try:
            stat = self._sftp.stat(remote_path)
            return stat.st_size
        except FileNotFoundError:
            return 0

    def list_files(self, remote_dir: str, pattern: str = "*") -> list[str]:
        """List files in remote directory matching pattern."""
        try:
            files = self._sftp.listdir(remote_dir)
            if pattern != "*":
                import fnmatch

                files = [f for f in files if fnmatch.fnmatch(f, pattern)]
            return files
        except FileNotFoundError:
            return []

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
        return False
