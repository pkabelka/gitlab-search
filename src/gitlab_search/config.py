"""Configuration management for gitlab-search."""

import json
import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_API_URL = "https://gitlab.com/api/v4"
DEFAULT_MAX_REQUESTS = 15
DEFAULT_ARCHIVED_FILTER = "all"
CONFIG_FILENAME = ".gitlab-search-config.json"

@dataclass
class Config:
    """GitLab search configuration."""
    api_url: str = DEFAULT_API_URL
    token: str | None = None
    ignore_cert: bool = False
    max_requests: int = DEFAULT_MAX_REQUESTS
    config_path: str = ""

def find_config_file() -> Path | None:
    """Search for config file in standard locations.

    Searches in order:
    1. Current working directory
    2. User config directory (XDG_CONFIG_HOME)
    3. /etc/

    Returns:
        Path to config file if found, None otherwise
    """
    search_paths = [
        Path.cwd() / CONFIG_FILENAME,
        Path(os.getenv('XDG_CONFIG_HOME', '')) / CONFIG_FILENAME,
        Path(os.getenv('HOME', '')) / '.config' / CONFIG_FILENAME,
        Path("/etc") / CONFIG_FILENAME,
    ]

    for path in search_paths:
        if path.is_file():
            return path

    return None

def load_config(config_file: str | None = None) -> Config:
    """Load configuration from config file.

    Args:
        config_file: Optional explicit config file path. If provided,
                     uses this path directly instead of searching.

    Returns:
        Loaded Config object
    """
    if config_file is not None:
        config_path = Path(config_file)
    else:
        config_path = find_config_file()

    data = {}
    if config_path is not None and config_path.is_file():
        with open(config_path) as f:
            data = json.load(f)

    return Config(
        api_url=data.get("api-url", DEFAULT_API_URL),
        token=None,
        ignore_cert=data.get("ignore-cert", False),
        max_requests=data.get("max-requests", DEFAULT_MAX_REQUESTS),
        config_path=str(config_path),
    )

def write_config(
    file_path: str | None = None,
    api_url: str = DEFAULT_API_URL,
    ignore_cert: bool = False,
    max_requests: int = DEFAULT_MAX_REQUESTS,
) -> str:
    """Write configuration to file.

    Args:
        file_path: Path to save config file. If None, uses default
                   location (./CONFIG_FILENAME)
        api_url: Full GitLab API base URL (e.g., https://gitlab.com/api/v4)
        ignore_cert: Whether to ignore certificate errors
        max_requests: Maximum concurrent requests

    Returns:
        Path to the written config file
    """
    if file_path is not None:
        output_path = Path(file_path)
    else:
        output_path = Path(".") / CONFIG_FILENAME

    config_data: dict[str, str | bool | int] = {}

    # Only write non-default values
    if api_url != DEFAULT_API_URL:
        config_data["api-url"] = api_url

    if ignore_cert:
        config_data["ignore-cert"] = True

    if max_requests != DEFAULT_MAX_REQUESTS:
        config_data["max-requests"] = max_requests

    with open(output_path, "w") as f:
        json.dump(config_data, f, indent=4)

    return str(output_path)


def resolve_token(token: str | None, token_file: str | None) -> str | None:
    """Resolve GitLab token from various sources.

    Priority (highest to lowest):
    1. Direct token argument (--token) or token file (--token-file)
    2. GITLAB_SEARCH_TOKEN environment variable

    Args:
        token: Direct token value from CLI
        token_file: Path to file containing token

    Returns:
        Resolved token or None if not found
    """
    if token:
        return token
    if token_file:
        with open(token_file) as f:
            return f.read().strip()
    return os.getenv("GITLAB_SEARCH_TOKEN")
