"""Progress bar management for remote operations."""

from typing import Optional

from tqdm import tqdm


def create_file_progress_bar(filename: str, size: int) -> tqdm:
    """Create a progress bar for file transfer."""
    return tqdm(
        total=size,
        desc=f"Transferring {filename}",
        unit="B",
        unit_scale=True,
        bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]",
    )


class RemoteProgress:
    """Manages progress bars for remote operations."""

    def __init__(self, desc: str, total: Optional[int] = None):
        self.desc = desc
        self.total = total
        self._bar: Optional[tqdm] = None

    def start(self) -> tqdm:
        """Start progress bar."""
        self._bar = tqdm(total=self.total, desc=self.desc, unit="steps")
        return self._bar

    def update(self, n: int = 1) -> None:
        """Update progress."""
        if self._bar:
            self._bar.update(n)

    def finish(self) -> None:
        """Close progress bar."""
        if self._bar:
            self._bar.close()

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.finish()
        return False
