"""All communication with GitHub lives in this file.

Other files never call GitHub directly. They ask this client, so every
network problem is handled in one single place.
"""

import os
from datetime import datetime
from urllib.parse import quote

import requests

from analyzer.errors import (
    EmptyRepositoryError,
    GitHubAPIError,
    NetworkError,
    NotFoundError,
    RateLimitError,
    RepositoryNotFoundError,
)

API_BASE = "https://api.github.com"
RAW_BASE = "https://raw.githubusercontent.com"
TIMEOUT_SECONDS = 15
TREE_TIMEOUT_SECONDS = 30
MAX_FILE_BYTES = 500_000


class GitHubClient:
    def __init__(self, token: str | None = None):
        # The token is read from the environment, never written in code.
        if token is None:
            token = os.environ.get("GITHUB_TOKEN")
        self.token = token.strip() if token and token.strip() else None

        # Session for the GitHub API (carries the token, if there is one).
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/vnd.github+json",
                "User-Agent": "repo-analyzer-cli",
                "X-GitHub-Api-Version": "2022-11-28",
            }
        )
        if self.token:
            self.session.headers["Authorization"] = f"Bearer {self.token}"

        # Separate session for downloading raw file text. It never gets the
        # token, because public files do not need it.
        self.raw_session = requests.Session()
        self.raw_session.headers.update({"User-Agent": "repo-analyzer-cli"})

        # Filled in after each API request, from GitHub's response headers.
        self.rate_limit: int | None = None
        self.rate_remaining: int | None = None

        self._tree_cache: dict = {}

    @property
    def uses_token(self) -> bool:
        return self.token is not None

    # ---------- low-level requests ----------

    def _send(self, session, url, params=None, timeout=TIMEOUT_SECONDS):
        try:
            return session.get(url, params=params, timeout=timeout)
        except requests.exceptions.Timeout:
            raise NetworkError("GitHub took too long to answer. Please try again.")
        except requests.exceptions.ConnectionError:
            raise NetworkError(
                "Could not connect to GitHub. Check your internet connection."
            )
        except requests.exceptions.RequestException as error:
            raise NetworkError(
                f"Network problem while contacting GitHub ({type(error).__name__})."
            )

    def request(self, path: str, params=None, timeout=TIMEOUT_SECONDS):
        """GET from the GitHub API. Returns the response, or raises a clear error."""
        response = self._send(self.session, API_BASE + path, params, timeout)
        self._remember_rate_limit(response)
        self._check_status(response)
        return response

    def get_json(self, path: str, params=None, timeout=TIMEOUT_SECONDS):
        """Like request(), but returns the decoded JSON."""
        response = self.request(path, params, timeout)
        try:
            return response.json()
        except ValueError:
            raise GitHubAPIError("GitHub sent an answer we could not read.")

    # ---------- helpers ----------

    def _remember_rate_limit(self, response) -> None:
        for header, attribute in (
            ("X-RateLimit-Limit", "rate_limit"),
            ("X-RateLimit-Remaining", "rate_remaining"),
        ):
            value = response.headers.get(header)
            if value is not None and value.isdigit():
                setattr(self, attribute, int(value))

    def _check_status(self, response) -> None:
        code = response.status_code
        if 200 <= code < 300:
            return

        if code == 401:
            raise GitHubAPIError(
                "GitHub rejected your GITHUB_TOKEN. It may be wrong or expired."
            )

        if code == 404:
            raise NotFoundError("GitHub could not find that resource.")

        if code == 409:
            raise EmptyRepositoryError("The repository is empty (it has no files yet).")

        if code in (403, 429):
            remaining = response.headers.get("X-RateLimit-Remaining")
            looks_like_rate_limit = (
                code == 429
                or remaining == "0"
                or "rate limit" in (response.text or "").lower()
            )
            if looks_like_rate_limit:
                raise RateLimitError(self._rate_limit_message(response))
            raise GitHubAPIError(
                "GitHub refused access (HTTP 403). The repository may be restricted."
            )

        raise GitHubAPIError(f"GitHub returned an unexpected answer (HTTP {code}).")

    def _rate_limit_message(self, response) -> str:
        message = "GitHub API rate limit reached."
        reset = response.headers.get("X-RateLimit-Reset")
        if reset and reset.isdigit():
            reset_time = datetime.fromtimestamp(int(reset)).strftime("%H:%M")
            message += f" You can try again after {reset_time}."
        if not self.uses_token:
            message += (
                " Without a token the limit is low (about 60 requests per hour)."
                " Set a GITHUB_TOKEN environment variable to get a much higher limit."
            )
        return message

    # ---------- high-level calls ----------

    def get_repo_info(self, owner: str, repo: str) -> dict:
        """Basic facts about a repository. Only fields GitHub really returned."""
        data = self._get_repo_json(owner, repo, "")
        license_info = data.get("license") or {}
        return {
            "full_name": data.get("full_name"),
            "description": data.get("description"),
            "html_url": data.get("html_url"),
            "stars": data.get("stargazers_count"),
            "forks": data.get("forks_count"),
            "open_issues": data.get("open_issues_count"),
            "default_branch": data.get("default_branch"),
            "license": license_info.get("spdx_id") or license_info.get("name"),
            "archived": data.get("archived"),
            "is_fork": data.get("fork"),
            "created_at": data.get("created_at"),
            "pushed_at": data.get("pushed_at"),
        }

    def _get_repo_json(self, owner, repo, suffix, params=None, timeout=TIMEOUT_SECONDS):
        """GET /repos/owner/repo<suffix>. A 404 here means the repo is missing."""
        try:
            return self.get_json(f"/repos/{owner}/{repo}{suffix}", params, timeout)
        except NotFoundError:
            raise RepositoryNotFoundError(
                f"Repository '{owner}/{repo}' was not found. "
                "It may not exist, or it may be private."
            )

    def get_languages(self, owner: str, repo: str) -> dict[str, int]:
        """Bytes of code per language, as measured by GitHub."""
        data = self._get_repo_json(owner, repo, "/languages")
        if not isinstance(data, dict):
            raise GitHubAPIError("GitHub sent language data in an unexpected shape.")
        return {
            name: size
            for name, size in data.items()
            if isinstance(size, int) and not isinstance(size, bool)
        }

    def get_file_tree(self, owner: str, repo: str, branch: str):
        """All files and folders of a branch.

        Returns (entries, truncated). Each entry is a dict with "path",
        "type" ("blob" = file, "tree" = folder) and "size" (files only).
        truncated is True when GitHub cut the list because it was too big.
        """
        key = (owner, repo, branch)
        if key in self._tree_cache:
            return self._tree_cache[key]

        data = self._get_repo_json(
            owner,
            repo,
            f"/git/trees/{quote(branch, safe='/')}",
            params={"recursive": "1"},
            timeout=TREE_TIMEOUT_SECONDS,
        )
        if not isinstance(data, dict) or not isinstance(data.get("tree"), list):
            raise GitHubAPIError("GitHub sent the file list in an unexpected shape.")

        entries = []
        for item in data["tree"]:
            if not isinstance(item, dict):
                continue
            if item.get("type") in ("blob", "tree") and isinstance(item.get("path"), str):
                entries.append(
                    {
                        "path": item["path"],
                        "type": item["type"],
                        "size": item.get("size"),
                    }
                )
        result = (entries, bool(data.get("truncated")))
        self._tree_cache[key] = result
        return result

    def get_file_text(self, owner: str, repo: str, ref: str, path: str) -> str:
        """Download one text file. Raw downloads do not use up API requests."""
        url = f"{RAW_BASE}/{owner}/{repo}/{quote(ref, safe='/')}/{quote(path, safe='/')}"
        response = self._send(self.raw_session, url)
        self._check_status(response)
        content = response.content
        if len(content) > MAX_FILE_BYTES:
            raise GitHubAPIError(
                f"{path} is too large to analyze (over {MAX_FILE_BYTES // 1000} KB)."
            )
        return content.decode("utf-8", errors="replace")
    