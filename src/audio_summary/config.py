"""Configuration management for audio-summary."""

from pathlib import Path
from dataclasses import dataclass
from typing import Optional

import yaml


@dataclass
class RemoteConfig:
    """Configuration for a remote host."""

    name: str
    host: str
    user: str
    path: str
    ssh_key: Optional[str] = None
    max_retries: int = 3

    @property
    def ssh_key_path(self) -> Optional[Path]:
        """Get the SSH key path, expanded."""
        if self.ssh_key:
            return Path(self.ssh_key).expanduser()
        return None


@dataclass
class Config:
    """Main configuration container."""

    remotes: dict[str, RemoteConfig]
    default_remote: Optional[str] = None

    def get_remote(self, name: Optional[str] = None) -> RemoteConfig:
        """Get remote configuration by name or default."""
        if name is None:
            name = self.default_remote

        if name is None:
            raise ValueError("No remote specified and no default configured")

        if name not in self.remotes:
            raise ValueError(f"Remote '{name}' not found in config")

        return self.remotes[name]


def get_config_path() -> Path:
    """Get the configuration file path."""
    return Path.home() / ".config" / "audio-summary" / "config.yaml"


def load_config() -> Config:
    """Load configuration from ~/.config/audio-summary/config.yaml."""
    config_path = get_config_path()

    if not config_path.exists():
        return Config(remotes={}, default_remote=None)

    with open(config_path) as f:
        data = yaml.safe_load(f) or {}

    remotes = {}
    for name, remote_data in data.get("remotes", {}).items():
        remotes[name] = RemoteConfig(name=name, **remote_data)

    return Config(remotes=remotes, default_remote=data.get("default_remote"))


def create_remote_config(
    host: str, user: str, path: str, ssh_key: Optional[str] = None, max_retries: int = 3
) -> RemoteConfig:
    """Create a RemoteConfig from ad-hoc parameters."""
    return RemoteConfig(
        name="adhoc",
        host=host,
        user=user,
        path=path,
        ssh_key=ssh_key,
        max_retries=max_retries,
    )
