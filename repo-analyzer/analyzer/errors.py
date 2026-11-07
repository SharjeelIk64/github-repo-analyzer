"""Our own error types. Each one carries a clear message for the user."""


class AnalyzerError(Exception):
    """Base class for all expected problems. main.py catches this one."""


class InvalidURLError(AnalyzerError):
    """The text given is not a usable GitHub repository URL."""


class NetworkError(AnalyzerError):
    """We could not reach GitHub (no internet, timeout, DNS problem)."""


class NotFoundError(AnalyzerError):
    """GitHub says a requested thing does not exist (HTTP 404)."""


class RepositoryNotFoundError(AnalyzerError):
    """The repository does not exist or is not public."""


class RateLimitError(AnalyzerError):
    """GitHub's API request limit has been reached."""


class GitHubAPIError(AnalyzerError):
    """Any other unexpected answer from GitHub (bad token, server error...)."""


class EmptyRepositoryError(AnalyzerError):
    """The repository exists but has no files yet."""