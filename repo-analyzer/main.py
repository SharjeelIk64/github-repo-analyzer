"""GitHub Repository Analyzer - command line entry point."""

import argparse
import sys
from datetime import datetime, timezone

from rich.console import Console
from rich.markup import escape

from analyzer.analysis import (
    aggregate_commit_activity,
    aggregate_contributors,
    analyze_file_structure,
    calculate_complexity,
)
from analyzer.detector import analyze_technologies
from analyzer.errors import AnalyzerError, RateLimitError
from analyzer.github_client import GitHubClient
from analyzer.report import (
    print_commit_activity,
    print_complexity,
    print_contributor_summary,
    print_file_structure,
    print_rate_limit,
    print_repo_summary,
    print_technologies,
)
from analyzer.url_parser import parse_github_url

console = Console()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Analyze a public GitHub repository."
    )
    parser.add_argument(
        "url",
        help="Public GitHub repository URL, e.g. https://github.com/psf/requests",
    )
    return parser


def show_technologies(client, owner, repo, info) -> None:
    branch = info["default_branch"]
    if not branch:
        raise AnalyzerError("GitHub did not tell us the default branch of this repository.")
    result = analyze_technologies(client, owner, repo, branch)
    print_technologies(console, result)


def show_file_structure(client, owner, repo, info) -> None:
    branch = info["default_branch"]
    entries, truncated = client.get_file_tree(owner, repo, branch)
    print_file_structure(console, analyze_file_structure(entries), truncated)


def show_complexity(client, owner, repo, info) -> None:
    entries, _ = client.get_file_tree(owner, repo, info["default_branch"])
    print_complexity(console, calculate_complexity(entries))


def show_commit_activity(client, owner, repo) -> None:
    now = datetime.now(timezone.utc)
    first_month_index = now.year * 12 + now.month - 1 - 11
    since = datetime(
        first_month_index // 12,
        first_month_index % 12 + 1,
        1,
        tzinfo=timezone.utc,
    ).isoformat().replace("+00:00", "Z")
    commits = client.get_commits(owner, repo, since)
    print_commit_activity(console, aggregate_commit_activity(commits, now))
    print_contributor_summary(console, aggregate_contributors(commits))
    if len(commits) >= 1000:
        console.print("[yellow]Note:[/yellow] Activity is based on the first 1,000 commits returned.")


def run_sections(sections) -> None:
    """Run each part of the report. One failing part never kills the others."""
    for title, action in sections:
        try:
            action()
        except RateLimitError as error:
            console.print(f"[red]Stopped at '{title}':[/red] {escape(str(error))}")
            return  # the limit is shared, so the next parts would fail too
        except AnalyzerError as error:
            console.print(f"[yellow]Could not complete '{title}':[/yellow] {escape(str(error))}")
        except Exception as error:  # a bug of ours: report it, do not crash
            console.print(
                f"[red]Unexpected problem in '{title}':[/red] "
                f"{type(error).__name__}: {escape(str(error))}"
            )


def main() -> int:
    args = build_parser().parse_args()
    client = GitHubClient()
    try:
        owner, repo = parse_github_url(args.url)
        info = client.get_repo_info(owner, repo)
    except AnalyzerError as error:
        console.print(f"[red]Error:[/red] {escape(str(error))}")
        return 1

    print_repo_summary(console, info)
    run_sections(
        [
            ("Technologies", lambda: show_technologies(client, owner, repo, info)),
            ("File structure", lambda: show_file_structure(client, owner, repo, info)),
            ("Complexity", lambda: show_complexity(client, owner, repo, info)),
            ("Contribution activity", lambda: show_commit_activity(client, owner, repo)),
        ]
    )
    print_rate_limit(console, client)
    return 0


if __name__ == "__main__":
    sys.exit(main())