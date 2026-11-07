"""Small, evidence-based repository metrics derived from GitHub data."""

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from analyzer.manifests import ManifestError, parse_manifest

FILE_PURPOSES = {
    ".py": "Python source",
    ".js": "JavaScript source",
    ".jsx": "JavaScript UI source",
    ".ts": "TypeScript source",
    ".tsx": "TypeScript UI source",
    ".go": "Go source",
    ".rs": "Rust source",
    ".java": "Java source",
    ".c": "C source",
    ".h": "C/C++ header",
    ".cpp": "C++ source",
    ".cs": "C# source",
    ".rb": "Ruby source",
    ".php": "PHP source",
    ".swift": "Swift source",
    ".kt": "Kotlin source",
    ".html": "Web markup",
    ".css": "Stylesheet",
    ".scss": "Stylesheet",
    ".md": "Documentation",
    ".rst": "Documentation",
    ".json": "Configuration / data",
    ".toml": "Configuration",
    ".yaml": "Configuration",
    ".yml": "Configuration",
    ".xml": "Configuration / markup",
    ".sh": "Shell script",
    ".sql": "SQL source",
    ".ipynb": "Jupyter notebook",
}

CODE_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java",
    ".c", ".h", ".cpp", ".cs", ".rb", ".php", ".swift", ".kt",
    ".sh", ".sql",
}


@dataclass
class FileStructure:
    file_count: int = 0
    folders: list[tuple[str, int]] = field(default_factory=list)
    file_types: list[tuple[str, int, str]] = field(default_factory=list)


@dataclass
class ComplexityMetrics:
    score: float
    source_files: int
    source_bytes: int
    max_depth: int


@dataclass
class DependencyFinding:
    name: str
    ecosystem: str
    spec: str
    source: str
    pinned: bool

    @property
    def version_label(self) -> str:
        if not self.spec.strip():
            return "Version not specified"
        if self.pinned:
            return "Exact pinned version"
        return "Version range"


@dataclass
class DependencyHealth:
    dependencies: list[DependencyFinding] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def unpinned(self) -> list[DependencyFinding]:
        return [dependency for dependency in self.dependencies if not dependency.pinned]


def analyze_file_structure(entries: list[dict]) -> FileStructure:
    """Count tracked files, their top-level folders, and extensions."""
    folder_counts: dict[str, int] = {}
    type_counts: dict[str, int] = {}
    files = [entry for entry in entries if entry.get("type") == "blob"]

    for entry in files:
        path = entry["path"]
        parts = path.split("/")
        folder = parts[0] if len(parts) > 1 else "(root)"
        folder_counts[folder] = folder_counts.get(folder, 0) + 1
        base = parts[-1].lower()
        extension = "." + base.rsplit(".", 1)[-1] if "." in base else "[no extension]"
        type_counts[extension] = type_counts.get(extension, 0) + 1

    folders = sorted(folder_counts.items(), key=lambda item: (-item[1], item[0]))
    file_types = [
        (extension, count, FILE_PURPOSES.get(extension, "Other / undetermined"))
        for extension, count in sorted(type_counts.items(), key=lambda item: (-item[1], item[0]))
    ]
    return FileStructure(len(files), folders, file_types)


def calculate_complexity(entries: list[dict]) -> ComplexityMetrics:
    """Calculate a 0-100 structural proxy from source count, size, and depth."""
    source_files = [
        entry for entry in entries
        if entry.get("type") == "blob"
        and "." + entry["path"].rsplit("/", 1)[-1].lower().rsplit(".", 1)[-1]
        in CODE_EXTENSIONS
    ]
    source_bytes = sum(
        size for entry in source_files
        if isinstance((size := entry.get("size")), int) and not isinstance(size, bool)
    )
    max_depth = max((entry["path"].count("/") for entry in source_files), default=0)
    score = (
        40 * min(len(source_files) / 100, 1)
        + 30 * min(source_bytes / (10 * 1024 * 1024), 1)
        + 30 * min(max_depth / 10, 1)
    )
    return ComplexityMetrics(round(score, 1), len(source_files), source_bytes, max_depth)


def _is_pinned(ecosystem: str, spec: str) -> bool:
    if ecosystem == "pypi":
        return bool(re.match(r"^\s*={2,3}\s*[^,;\s]+\s*$", spec))
    return bool(re.fullmatch(
        r"v?\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?",
        spec.strip(),
    ))


def inspect_dependencies(manifests: dict[str, str]) -> DependencyHealth:
    result = DependencyHealth()
    for path, text in sorted(manifests.items()):
        try:
            ecosystem, dependencies = parse_manifest(path, text)
        except ManifestError as error:
            result.notes.append(f"Could not assess {path}: {error}")
            continue
        for dependency in dependencies:
            result.dependencies.append(
                DependencyFinding(
                    dependency.name,
                    ecosystem,
                    dependency.spec,
                    f"{path} ({dependency.group})",
                    _is_pinned(ecosystem, dependency.spec),
                )
            )
    if not manifests:
        result.notes.append("No supported dependency files found; dependency health could not be assessed.")
    return result


def aggregate_commit_activity(commits: list[dict], now: datetime | None = None) -> list[tuple[str, int]]:
    """Count commits by month over the current and preceding 11 calendar months."""
    now = now or datetime.now(timezone.utc)
    month_keys = []
    year, month = now.year, now.month
    for _ in range(12):
        month_keys.append(f"{year:04d}-{month:02d}")
        year, month = (year - 1, 12) if month == 1 else (year, month - 1)
    month_keys.reverse()
    counts = dict.fromkeys(month_keys, 0)

    for commit in commits:
        value = commit.get("date")
        if not isinstance(value, str):
            continue
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            continue
        key = f"{parsed.year:04d}-{parsed.month:02d}"
        if key in counts:
            counts[key] += 1
    return list(counts.items())


def aggregate_contributors(commits: list[dict], limit: int = 10) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for commit in commits:
        author = commit.get("author")
        if isinstance(author, str) and author.strip():
            name = author.strip()
            counts[name] = counts.get(name, 0) + 1
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0].lower()))
    return ordered[:max(0, limit)]