from io import StringIO
from datetime import datetime, timezone

from rich.console import Console

from analyzer.analysis import (
    aggregate_commit_activity,
    aggregate_contributors,
    analyze_file_structure,
    calculate_complexity,
    inspect_dependencies,
)
from analyzer.report import print_dependency_health


def test_file_structure_counts_files_folders_and_purposes():
    result = analyze_file_structure([
        {"path": "README.md", "type": "blob"},
        {"path": "src/main.py", "type": "blob"},
        {"path": "src/lib/util.py", "type": "blob"},
        {"path": "assets/logo.png", "type": "blob"},
        {"path": "src", "type": "tree"},
    ])
    assert result.file_count == 4
    assert result.folders == [("src", 2), ("(root)", 1), ("assets", 1)]
    assert result.file_types[0] == (".py", 2, "Python source")


def test_complexity_score_uses_only_source_files_and_tree_metadata():
    result = calculate_complexity([
        {"path": "src/main.py", "type": "blob", "size": 1024},
        {"path": "src/nested/util.py", "type": "blob", "size": 2048},
        {"path": "README.md", "type": "blob", "size": 100000},
        {"path": "src", "type": "tree", "size": 0},
    ])
    assert result.source_files == 2
    assert result.source_bytes == 3072
    assert result.max_depth == 2
    assert result.score == 6.8


def test_dependency_health_reports_versions_and_unpinned_evidence():
    result = inspect_dependencies({
        "requirements.txt": "requests==2.31.0\nflask>=2.0\nunknown\n",
        "package.json": '{"dependencies":{"react":"18.2.0","vite":"^5.0.0"}}',
    })
    assert len(result.dependencies) == 5
    assert {(item.name, item.pinned) for item in result.dependencies} == {
        ("requests", True), ("flask", False), ("unknown", False),
        ("react", True), ("vite", False),
    }
    assert {item.name for item in result.unpinned} == {"flask", "vite", "unknown"}
    assert {item.name: item.version_label for item in result.dependencies} == {
        "requests": "Exact pinned version",
        "flask": "Version range",
        "unknown": "Version not specified",
        "react": "Exact pinned version",
        "vite": "Version range",
    }


def test_dependency_health_handles_missing_and_invalid_manifests():
    assert "could not be assessed" in inspect_dependencies({}).notes[0]
    result = inspect_dependencies({"package.json": "broken"})
    assert result.dependencies == []
    assert "Could not assess package.json" in result.notes[0]


def test_dependency_report_uses_neutral_version_labels():
    result = inspect_dependencies({
        "requirements.txt": "pinned==1.2.3\nranged>=2\nunspecified\n",
    })
    output = StringIO()
    print_dependency_health(Console(file=output, width=120), result)
    text = output.getvalue()
    assert "Exact pinned version" in text
    assert "Version range" in text
    assert "Version not specified" in text
    assert "Evidence-based concern" not in text


def test_commit_activity_buckets_last_twelve_months_and_skips_bad_dates():
    activity = aggregate_commit_activity(
        [
            {"date": "2025-03-14T10:00:00Z"},
            {"date": "2025-02-01T10:00:00+00:00"},
            {"date": "2024-03-01T10:00:00Z"},
            {"date": "not a date"},
        ],
        datetime(2025, 3, 15, tzinfo=timezone.utc),
    )
    assert len(activity) == 12
    assert activity[0] == ("2024-04", 0)
    assert activity[-2:] == [("2025-02", 1), ("2025-03", 1)]


def test_aggregate_contributors_sorts_by_commit_count():
    assert aggregate_contributors([
        {"author": "alice"},
        {"author": "bob"},
        {"author": "alice"},
        {"author": None},
    ]) == [("alice", 2), ("bob", 1)]