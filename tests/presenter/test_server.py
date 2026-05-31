from presenter import server


def test_present_returns_ok_and_echoes_path():
    assert server.present("meetings/2026-05-31/atlas.md") == {
        "ok": True,
        "presented": "meetings/2026-05-31/atlas.md",
    }


def test_tool_names_are_bare():
    # OpenCode namespaces MCP tools as <serverkey>_<name>; the server registers the
    # bare name 'present' so the agent sees 'present' under the 'present' server key.
    assert server.TOOL_NAMES == ("present",)
