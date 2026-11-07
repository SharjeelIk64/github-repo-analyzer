"""Tests for the file-related client calls, using fake GitHub answers."""

import pytest

from analyzer.errors import (
    EmptyRepositoryError,
    GitHubAPIError,
    NotFoundError,
    RateLimitError,
    RepositoryNotFoundError,
)
from analyzer.github_client import MAX_FILE_BYTES, GitHubClient


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, content=b"", headers=None):
        self.status_code = status_code
        self._json = json_data
        self.content = content
        self.headers = headers or {}
        self.text = ""

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json


def client_with(monkeypatch, api=None, raw=None):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    client = GitHubClient()
    calls = {"api": 0, "raw": 0, "urls": []}

    def fake_api(url, params=None, timeout=None):
        calls["api"] += 1
        calls["urls"].append(url)
        return api

    def fake_raw(url, params=None, timeout=None):
        calls["raw"] += 1
        calls["urls"].append(url)
        return raw

    monkeypatch.setattr(client.session, "get", fake_api)
    monkeypatch.setattr(client.raw_session, "get", fake_raw)
    return client, calls


def test_languages(monkeypatch):
    client, _ = client_with(monkeypatch, FakeResponse(200, {"Python": 100, "Shell": 5, "Bad": "x"}))
    assert client.get_languages("o", "r") == {"Python": 100, "Shell": 5}


def test_languages_wrong_shape(monkeypatch):
    client, _ = client_with(monkeypatch, FakeResponse(200, ["x"]))
    with pytest.raises(GitHubAPIError):
        client.get_languages("o", "r")


def test_languages_missing_repo(monkeypatch):
    client, _ = client_with(monkeypatch, FakeResponse(404, {}))
    with pytest.raises(RepositoryNotFoundError):
        client.get_languages("o", "r")


def test_file_tree_parsing_and_cache(monkeypatch):
    data = {
        "tree": [
            {"path": "src", "type": "tree"},
            {"path": "src/app.py", "type": "blob", "size": 12},
            {"path": "lib", "type": "commit"},  # submodule: ignored
            "garbage",
        ],
        "truncated": False,
    }
    client, calls = client_with(monkeypatch, FakeResponse(200, data))
    entries, truncated = client.get_file_tree("o", "r", "main")
    assert [e["path"] for e in entries] == ["src", "src/app.py"]
    assert entries[1]["size"] == 12
    assert truncated is False
    client.get_file_tree("o", "r", "main")
    assert calls["api"] == 1  # second call came from the cache


def test_file_tree_truncated_flag(monkeypatch):
    client, _ = client_with(monkeypatch, FakeResponse(200, {"tree": [], "truncated": True}))
    assert client.get_file_tree("o", "r", "main")[1] is True


def test_get_commits_extracts_dates_and_paginates(monkeypatch):
    responses = [
        [
            {
                "author": {"login": "octocat"},
                "commit": {"author": {"name": "Octo Cat", "date": "2025-01-02T03:04:05Z"}},
            },
            {"commit": {"committer": {"name": "Contributor", "date": "2024-12-01T00:00:00Z"}}},
        ]
    ]
    client, calls = client_with(monkeypatch, FakeResponse(200, responses[0]))
    commits = client.get_commits("o", "r", "2024-01-01T00:00:00Z")
    assert commits == [
        {"date": "2025-01-02T03:04:05Z", "author": "octocat"},
        {"date": "2024-12-01T00:00:00Z", "author": "Contributor"},
    ]
    assert calls["api"] == 1


def test_get_commits_with_zero_limit_does_not_call_github(monkeypatch):
    client, calls = client_with(monkeypatch)
    assert client.get_commits("o", "r", "2024-01-01T00:00:00Z", max_commits=0) == []
    assert calls["api"] == 0


@pytest.mark.parametrize(
    "response,error",
    [
        (FakeResponse(401), GitHubAPIError),
        (FakeResponse(403), GitHubAPIError),
        (FakeResponse(403, headers={"X-RateLimit-Remaining": "0"}), RateLimitError),
        (FakeResponse(429), RateLimitError),
        (FakeResponse(500), GitHubAPIError),
    ],
)
def test_api_errors_are_reported_by_status(response, error):
    client = GitHubClient()
    with pytest.raises(error):
        client._check_status(response)


def test_file_tree_empty_repository(monkeypatch):
    client, _ = client_with(monkeypatch, FakeResponse(409, {}))
    with pytest.raises(EmptyRepositoryError):
        client.get_file_tree("o", "r", "main")


def test_file_tree_wrong_shape(monkeypatch):
    client, _ = client_with(monkeypatch, FakeResponse(200, {"nothing": 1}))
    with pytest.raises(GitHubAPIError):
        client.get_file_tree("o", "r", "main")


def test_file_text_success_and_url(monkeypatch):
    client, calls = client_with(monkeypatch, raw=FakeResponse(200, content="héllo".encode()))
    assert client.get_file_text("o", "r", "main", "dir/my file.txt") == "héllo"
    assert calls["raw"] == 1 and calls["api"] == 0
    assert calls["urls"][0].endswith("/o/r/main/dir/my%20file.txt")


def test_file_text_bad_bytes_do_not_crash(monkeypatch):
    client, _ = client_with(monkeypatch, raw=FakeResponse(200, content=b"abc\xff\xfe"))
    assert client.get_file_text("o", "r", "main", "x.txt").startswith("abc")


def test_file_text_not_found(monkeypatch):
    client, _ = client_with(monkeypatch, raw=FakeResponse(404))
    with pytest.raises(NotFoundError):
        client.get_file_text("o", "r", "main", "x.txt")


def test_file_text_too_large(monkeypatch):
    client, _ = client_with(monkeypatch, raw=FakeResponse(200, content=b"a" * (MAX_FILE_BYTES + 1)))
    with pytest.raises(GitHubAPIError):
        client.get_file_text("o", "r", "main", "big.txt")


def test_raw_downloads_never_carry_the_token(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "secret123")
    client = GitHubClient()
    assert "Authorization" in client.session.headers
    assert "Authorization" not in client.raw_session.headers