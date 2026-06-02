"""Contract tests for the `python -m <module>` MCP spawn mechanism.

The generated opencode.json runs the MCP servers as ``<python> -m <module>``
rather than via their console-script executables. That only works if each module
is importable AND exposes a ``main`` callable behind an ``if __name__ ==
"__main__"`` guard (so ``python -m`` runs it). These tests lock that contract —
if a future refactor moves ``main`` out of ``<pkg>.server``, the generated
command would silently break at launch; this fails fast instead.
"""
import importlib

import pytest

from frontend.config import AGENDA_SERVER_MODULE, PRESENT_SERVER_MODULE


@pytest.mark.parametrize("module", [AGENDA_SERVER_MODULE, PRESENT_SERVER_MODULE])
def test_mcp_module_importable_with_callable_main(module):
    mod = importlib.import_module(module)
    assert callable(getattr(mod, "main", None)), f"{module} must expose a callable main()"
