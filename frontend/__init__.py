"""Browser-facing web service: the sole OpenCode HTTP client and SSE relay."""
from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("notes-frontend")  # from git tags via setuptools-scm
except PackageNotFoundError:  # running from source without an install
    __version__ = "0+unknown"
