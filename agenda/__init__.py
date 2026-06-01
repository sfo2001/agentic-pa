"""Deterministic, read-only Agenda service for the Chief-of-Staff Notes MVP."""
from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("agenda-service")  # from git tags via setuptools-scm
except PackageNotFoundError:  # running from source without an install
    __version__ = "0+unknown"
