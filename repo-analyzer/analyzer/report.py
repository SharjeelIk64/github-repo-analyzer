"""Everything that prints to the screen lives here."""

from rich.console import Console
from rich.markup import escape
from rich.table import Table

from analyzer.analysis import ComplexityMetrics, DependencyHealth, FileStructure
from analyzer.detector import MAX_LANGUAGES_SHOWN

MAX_EVIDENCE_SHOWN = 3


def _show(value, empty_text="Not provided"):
    """Safe text for printing. Missing values are shown honestly."""
    if value is None or value == "":
        return f"[dim]{empty_text}[/dim]"
    return escape(str(value))


def print_repo_summary(console: Console, info: dict) -> None:
    table = Table(title="Repository Summary", show_header=False, title_style="bold")
    table.add_column("Field", style="cyan", no_wrap=True)
    table.add_column("Value")

    table.add_row("Name", _show(info["full_name"]))
    table.add_row("Description", _show(info["description"], "No description"))
    table.add_row("URL", _show(info["html_url"]))
    table.add_row("Stars", _show(info["stars"]))
    table.add_row("Forks", _show(info["forks"]))
    table.add_row("Open issues + PRs", _show(info["open_issues"]))
    table.add_row("Default branch", _show(info["default_branch"]))
    table.add_row("License", _show(info["license"], "No license detected"))
    table.add_row("Archived", _show(info["archived"]))
    table.add_row("Is a fork", _show(info["is_fork"]))
    table.add_row("Created", _show(info["created_at"]))
    table.add_row("Last push", _show(info["pushed_at"]))
    console.print(table)


def print_rate_limit(console: Console, client) -> None:
    if client.rate_remaining is None or client.rate_limit is None:
        return
    mode = "using GITHUB_TOKEN" if client.uses_token else "no token"
    console.print(
        f"[dim]GitHub API requests left: {client.rate_remaining}/{client.rate_limit} ({mode})[/dim]"
    )


def _evidence_text(evidence: list[str]) -> str:
    lines = [escape(item) for item in evidence[:MAX_EVIDENCE_SHOWN]]
    extra = len(evidence) - MAX_EVIDENCE_SHOWN
    if extra > 0:
        lines.append(f"[dim](+{extra} more)[/dim]")
    return "\n".join(lines)


def _print_findings(console: Console, title: str, findings, kind_title: str) -> None:
    table = Table(title=title, title_style="bold")
    table.add_column("Name", style="cyan", no_wrap=True)
    table.add_column(kind_title, no_wrap=True)
    table.add_column("Evidence")
    for finding in findings:
        table.add_row(escape(finding.name), escape(finding.kind), _evidence_text(finding.evidence))
    console.print(table)


def print_technologies(console: Console, result) -> None:
    if result.languages:
        shown = result.languages[:MAX_LANGUAGES_SHOWN]
        _print_findings(console, "Languages", shown, "Type")
        hidden = len(result.languages) - len(shown)
        if hidden > 0:
            console.print(f"[dim](+{hidden} smaller languages not shown)[/dim]")

    if result.frameworks:
        _print_findings(console, "Frameworks & Libraries", result.frameworks, "Type")
    else:
        console.print("[dim]No known frameworks or libraries found in the dependency files we read.[/dim]")

    if result.tools:
        _print_findings(console, "Tools (found by file names)", result.tools, "Type")
    else:
        console.print("[dim]No known tool files found.[/dim]")

    for note in result.notes:
        console.print(f"[yellow]Note:[/yellow] {escape(note)}")

    print_dependency_health(console, result.dependency_health)


def print_file_structure(console: Console, structure: FileStructure, truncated: bool = False) -> None:
    console.print(f"\n[bold]File Structure[/bold]  {structure.file_count} files")
    folders = Table(title="Major folders (file counts)", title_style="bold")
    folders.add_column("Folder", style="cyan")
    folders.add_column("Files", justify="right")
    for folder, count in structure.folders[:8]:
        folders.add_row(escape(folder), str(count))
    console.print(folders)

    types = Table(title="File types and likely purpose", title_style="bold")
    types.add_column("Type", style="cyan")
    types.add_column("Files", justify="right")
    types.add_column("Purpose")
    for extension, count, purpose in structure.file_types[:10]:
        types.add_row(escape(extension), str(count), escape(purpose))
    console.print(types)
    if len(structure.folders) > 8 or len(structure.file_types) > 10:
        console.print("[dim]Additional folder or file-type rows omitted.[/dim]")
    if truncated:
        console.print("[yellow]Note:[/yellow] GitHub truncated the repository tree; counts may be incomplete.")


def print_complexity(console: Console, metrics: ComplexityMetrics) -> None:
    table = Table(title="Structural Complexity Proxy (0-100)", title_style="bold")
    table.add_column("Score", style="cyan")
    table.add_column("Source files")
    table.add_column("Source bytes")
    table.add_column("Max source depth")
    table.add_row(
        f"{metrics.score:.1f}",
        str(metrics.source_files),
        f"{metrics.source_bytes:,}",
        str(metrics.max_depth),
    )
    console.print(table)
    console.print("[dim]This structural proxy is not a measure of code quality or algorithmic complexity.[/dim]")


def print_dependency_health(console: Console, health: DependencyHealth) -> None:
    if health.dependencies:
        table = Table(title="Dependencies and Version Pinning", title_style="bold")
        table.add_column("Name", style="cyan")
        table.add_column("Ecosystem")
        table.add_column("Declared version")
        table.add_column("Version status")
        table.add_column("Manifest evidence")
        shown = health.dependencies[:30]
        for dependency in shown:
            spec = dependency.spec or "not specified"
            table.add_row(
                escape(dependency.name),
                escape(dependency.ecosystem),
                escape(spec),
                dependency.version_label,
                escape(dependency.source),
            )
        console.print(table)
        if len(health.dependencies) > len(shown):
            console.print(f"[dim](+{len(health.dependencies) - len(shown)} dependencies not shown)[/dim]")
    for note in health.notes:
        console.print(f"[yellow]Dependency note:[/yellow] {escape(note)}")


def print_commit_activity(console: Console, activity: list[tuple[str, int]]) -> None:
    console.print("\n[bold]Commit Activity by Month (last 12 months)[/bold]")
    peak = max((count for _, count in activity), default=0)
    for month, count in activity:
        width = round(count / peak * 30) if peak else 0
        console.print(f"{month}  {'#' * width} {count}")


def print_contributor_summary(console: Console, contributors: list[tuple[str, int]]) -> None:
    if not contributors:
        console.print("[dim]No identifiable contributors in the fetched commit history.[/dim]")
        return
    table = Table(title="Top Contributors (fetched commits)", title_style="bold")
    table.add_column("Contributor", style="cyan")
    table.add_column("Commits", justify="right")
    for name, count in contributors:
        table.add_row(escape(name), str(count))
    console.print(table)