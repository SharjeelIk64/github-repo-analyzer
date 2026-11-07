import pytest

from analyzer.errors import InvalidURLError
from analyzer.url_parser import parse_github_url


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/psf/requests",
        "http://github.com/psf/requests",
        "https://www.github.com/psf/requests",
        "github.com/psf/requests",
        "https://github.com/psf/requests/",
        "https://github.com/psf/requests.git",
        "https://github.com/psf/requests/tree/main/src",
        "  https://github.com/psf/requests  ",
    ],
)
def test_valid_urls(url):
    assert parse_github_url(url) == ("psf", "requests")


def test_repo_with_dots_and_dashes():
    assert parse_github_url("https://github.com/vercel/next.js") == ("vercel", "next.js")


@pytest.mark.parametrize(
    "url",
    [
        "",
        "   ",
        None,
        "hello world",
        "https://google.com/psf/requests",
        "https://gitlab.com/psf/requests",
        "https://github.com",
        "https://github.com/onlyowner",
        "https://github.com/-bad-/repo",
        "https://github.com/owner/..",
        "ftp://github.com/psf/requests",
        "https://github.com/ow ner/repo",
    ],
)
def test_invalid_urls(url):
    with pytest.raises(InvalidURLError):
        parse_github_url(url)
