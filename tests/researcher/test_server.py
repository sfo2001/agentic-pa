import json
import pytest
import httpx
from unittest.mock import patch, MagicMock
from researcher.server import query as research_query_fn


def _good_envelope(q: str = "test") -> str:
    return json.dumps({
        "schema_version": "1.0", "query": q,
        "findings": [{"claim": "Finding.", "source_url": "https://example.com/1",
                      "source_title": "Example", "retrieved_at": "2026-06-20T10:00:00Z"}],
        "sources": [{"url": "https://example.com/1", "title": "Example", "fetched_at": "2026-06-20T10:00:00Z"}],
    })


def _mock_post(text: str, status: int = 200):
    resp = MagicMock()
    resp.status_code = status
    resp.text = text
    if status >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "err", request=MagicMock(), response=resp
        )
    else:
        resp.raise_for_status = MagicMock()
    return resp


def test_returns_formatted_findings():
    with patch("httpx.post", return_value=_mock_post(_good_envelope("opencode"))):
        result = research_query_fn("opencode")
    assert "Finding." in result
    assert "https://example.com/1" in result


def test_handles_airlock_rejection():
    bad = json.dumps({"schema_version": "99.0", "query": "x", "findings": [], "sources": []})
    with patch("httpx.post", return_value=_mock_post(bad)):
        result = research_query_fn("test")
    assert "ERROR" in result


def test_handles_researcher_unreachable():
    with patch("httpx.post", side_effect=httpx.ConnectError("refused")):
        result = research_query_fn("test")
    assert "ERROR" in result or "unavailable" in result.lower()


def test_no_findings_message():
    empty = json.dumps({"schema_version": "1.0", "query": "x", "findings": [], "sources": []})
    with patch("httpx.post", return_value=_mock_post(empty)):
        result = research_query_fn("x")
    assert "No findings" in result
