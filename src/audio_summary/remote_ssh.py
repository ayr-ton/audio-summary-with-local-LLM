import subprocess
import time
from pathlib import Path
from typing import Optional, Callable
from tqdm import tqdm
import shlex

from .config import RemoteConfig


class RemoteExecutorSSH:
    """Execute commands and transfer files via SSH using subprocess."""

    def __init__(self, config: RemoteConfig):
        self.config = config
        self.ssh_base_cmd = self._build_ssh_command()

    def _build_ssh_command(self) -> list[str]:
        """Build the base SSH command."""
        cmd = [
            "ssh",
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-o",
            "BatchMode=no",  # Allow interactive auth (for hardware keys)
        ]

        if self.config.ssh_key_path:
            cmd.extend(["-i", str(self.config.ssh_key_path)])

        cmd.append(f"{self.config.user}@{self.config.host}")
        return cmd

    def _build_scp_command(
        self, local_path: Path, remote_path: str, upload: bool = True
    ) -> list[str]:
        """Build SCP command for file transfer."""
        cmd = [
            "scp",
            "-o",
            "StrictHostKeyChecking=accept-new",
        ]

        if self.config.ssh_key_path:
            cmd.extend(["-i", str(self.config.ssh_key_path)])

        if upload:
            cmd.extend(
                [
                    str(local_path),
                    f"{self.config.user}@{self.config.host}:{remote_path}",
                ]
            )
        else:
            cmd.extend(
                [
                    f"{self.config.user}@{self.config.host}:{remote_path}",
                    str(local_path),
                ]
            )

        return cmd

    def execute(
        self,
        command: str,
        cwd: Optional[str] = None,
        progress_callback: Optional[Callable[[str], None]] = None,
        dry_run: bool = False,
    ) -> tuple[int, str, str]:
        """Execute command on remote via SSH."""
        if dry_run:
            full_cmd = f"cd {cwd} && {command}" if cwd else command
            print(f"[DRY-RUN] Would execute: {full_cmd}")
            return 0, "", ""

        # Build full command
        if cwd:
            command = f"cd {cwd} && {command}"

        ssh_cmd = self.ssh_base_cmd.copy()
        ssh_cmd.append(command)

        if dry_run:
            print(f"[DRY-RUN] Would execute: {' '.join(ssh_cmd)}")
            return 0, "", ""

        # Execute via subprocess
        result = subprocess.run(
            ssh_cmd,
            capture_output=True,
            text=True,
            timeout=3600,  # 1 hour timeout
        )

        return result.returncode, result.stdout, result.stderr

    def check_file_exists(self, remote_path: str) -> bool:
        """Check if a file exists on remote."""
        ssh_cmd = self.ssh_base_cmd.copy()
        # Properly escape the path for shell execution
        escaped_path = shlex.quote(remote_path)
        ssh_cmd.append(f"test -f {escaped_path} && echo 'EXISTS' || echo 'NOT_FOUND'")

        result = subprocess.run(
            ssh_cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )

        return "EXISTS" in result.stdout

    def get_file_size(self, remote_path: str) -> int:
        """Get file size from remote."""
        # First check if file exists and is a regular file (not directory)
        ssh_cmd = self.ssh_base_cmd.copy()
        escaped_path = shlex.quote(remote_path)
        ssh_cmd.append(
            f"test -f {escaped_path} && stat -c %s {escaped_path} || echo -1"
        )

        result = subprocess.run(
            ssh_cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )

        try:
            size = int(result.stdout.strip())
            return size if size >= 0 else 0
        except ValueError:
            return 0

    def upload_file(
        self,
        local_path: Path,
        remote_path: str,
        progress_bar: Optional[tqdm] = None,
        dry_run: bool = False,
    ) -> None:
        """Upload file via SCP."""
        if dry_run:
            print(f"[DRY-RUN] Would upload: {local_path} -> {remote_path}")
            return

        # Ensure remote directory exists
        remote_dir = str(Path(remote_path).parent)
        self.execute(f"mkdir -p {remote_dir}", dry_run=dry_run)

        scp_cmd = self._build_scp_command(local_path, remote_path, upload=True)

        if progress_bar:
            # SCP doesn't have progress callback, so we simulate it
            progress_bar.set_description(f"Uploading {local_path.name}")
            file_size = local_path.stat().st_size
            progress_bar.total = file_size
            progress_bar.n = 0
            progress_bar.refresh()

        result = subprocess.run(scp_cmd, capture_output=True, text=True, timeout=3600)

        if result.returncode != 0:
            raise Exception(f"SCP upload failed: {result.stderr}")

        if progress_bar:
            progress_bar.n = progress_bar.total
            progress_bar.refresh()
            progress_bar.close()

    def download_file(
        self,
        remote_path: str,
        local_path: Path,
        progress_bar: Optional[tqdm] = None,
        dry_run: bool = False,
    ) -> None:
        """Download file via SCP."""
        if dry_run:
            print(f"[DRY-RUN] Would download: {remote_path} -> {local_path}")
            return

        # Ensure local directory exists
        local_path.parent.mkdir(parents=True, exist_ok=True)

        scp_cmd = self._build_scp_command(local_path, remote_path, upload=False)

        if progress_bar:
            progress_bar.set_description(f"Downloading {local_path.name}")
            # Get file size first
            file_size = self.get_file_size(remote_path)
            if file_size > 0:
                progress_bar.total = file_size
            progress_bar.n = 0
            progress_bar.refresh()

        result = subprocess.run(scp_cmd, capture_output=True, text=True, timeout=3600)

        if result.returncode != 0:
            raise Exception(f"SCP download failed: {result.stderr}")

        if progress_bar:
            progress_bar.n = progress_bar.total
            progress_bar.refresh()
            progress_bar.close()

    def execute_with_retry(
        self,
        command: str,
        cwd: Optional[str] = None,
        max_retries: Optional[int] = None,
        dry_run: bool = False,
    ) -> tuple[bool, str, str]:
        """Execute with automatic retry."""

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

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # Nothing to close with subprocess approach
        return False
