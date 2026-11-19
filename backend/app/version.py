"""The backend's release version, bumped by release-please (see `extra-files`).

The image never installs the project into its venv (`--no-install-project`) and
ships without `pyproject.toml`, so `importlib.metadata` has nothing to read.
"""

__version__ = "0.9.28"  # x-release-please-version
