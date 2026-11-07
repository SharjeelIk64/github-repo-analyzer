"""Checks a GitHub URL and extracts the owner and repository name."""

import re
from urllib.parse import urlparse

from analyzer.errors import InvalidURLError

# GitHub rules (simplified): owner = letters, digits, hyphens (max 39 chars).
# Repo names may also contain dots and underscores.
OWNER_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
REPO_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
ALLOWED_HOSTS = {"github.com", "www.github.com"}


def parse_github_url(url: str) -> tuple[str, str]:
    """Return (owner, repo) from a GitHub repository URL.

    Accepts: https://github.com/owner/repo, github.com/owner/repo,
    trailing slash, .git ending, and extra parts like /tree/main.
    Raises InvalidURLError with a clear message for anything else.
    """
    if url is None or not url.strip():
        raise InvalidURLError("No URL given. Example: https://github.com/psf/requests")

    text = url.strip()

    # Allow "github.com/owner/repo" without the https:// part.
    if "://" not in text:
        text = "https://" + text

    parsed = urlparse(text)

    if parsed.scheme not in ("http", "https"):
        raise InvalidURLError(
            f"Unsupported URL type '{parsed.scheme}'. Use an https://github.com/... link."
        )

    host = (parsed.hostname or "").lower()
    if host not in ALLOWED_HOSTS:
        raise InvalidURLError(
            f"'{host or url}' is not GitHub. Only github.com repositories are supported."
        )

    # Path looks like /owner/repo/maybe/more
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 2:
        raise InvalidURLError(
            "The URL must include both owner and repository, "
            "like https://github.com/owner/repo"
        )

    owner, repo = parts[0], parts[1]

    if repo.endswith(".git"):
        repo = repo[: -len(".git")]

    if not OWNER_PATTERN.match(owner):
        raise InvalidURLError(f"'{owner}' is not a valid GitHub owner name.")
    if repo in ("", ".", "..") or not REPO_PATTERN.match(repo):
        raise InvalidURLError(f"'{repo}' is not a valid GitHub repository name.")

    return owner, repo
