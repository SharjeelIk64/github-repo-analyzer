"""Finds languages, frameworks and tools - always together with evidence.

Rule of this file: we only report something when we can point to the exact
place where we saw it (a GitHub statistic, a file name, or a line in a
dependency file). If there is no proof, we say nothing.
"""

from dataclasses import dataclass, field

from analyzer.analysis import DependencyHealth, inspect_dependencies
from analyzer.errors import AnalyzerError, RateLimitError
from analyzer.manifests import (
    ManifestError,
    is_requirements_file,
    parse_manifest,
)

MANIFEST_LIMIT = 6        # most dependency files we will download
MANIFEST_MAX_DEPTH = 2    # how many folders deep we look for them
MAX_LANGUAGES_SHOWN = 10

# Folders we ignore when looking for dependency files and tools,
# because their content belongs to somebody else or is only sample data.
IGNORED_FOLDERS = {
    "node_modules", "vendor", "third_party", "site-packages",
    "test", "tests", "fixtures", "testdata", "example", "examples", "samples",
}

# package name -> (display name, what kind of thing it is)
PYPI_PACKAGES = {
    "django": ("Django", "Web framework"),
    "flask": ("Flask", "Web framework"),
    "fastapi": ("FastAPI", "Web framework"),
    "streamlit": ("Streamlit", "App framework"),
    "pytest": ("pytest", "Testing"),
    "numpy": ("NumPy", "Data / ML library"),
    "pandas": ("pandas", "Data / ML library"),
    "scikit-learn": ("scikit-learn", "Data / ML library"),
    "torch": ("PyTorch", "ML framework"),
    "tensorflow": ("TensorFlow", "ML framework"),
    "transformers": ("Hugging Face Transformers", "ML library"),
    "langchain": ("LangChain", "LLM framework"),
    "sqlalchemy": ("SQLAlchemy", "Database / ORM"),
    "celery": ("Celery", "Task queue"),
    "requests": ("Requests", "HTTP library"),
    "sphinx": ("Sphinx", "Documentation"),
    "ruff": ("Ruff", "Linting / formatting"),
    "black": ("Black", "Linting / formatting"),
    "flake8": ("Flake8", "Linting / formatting"),
    "mypy": ("mypy", "Type checking"),
}

NPM_PACKAGES = {
    "react": ("React", "UI library"),
    "next": ("Next.js", "Web framework"),
    "vue": ("Vue", "UI framework"),
    "nuxt": ("Nuxt", "Web framework"),
    "@angular/core": ("Angular", "Web framework"),
    "svelte": ("Svelte", "UI framework"),
    "express": ("Express", "Web framework"),
    "fastify": ("Fastify", "Web framework"),
    "@nestjs/core": ("NestJS", "Web framework"),
    "tailwindcss": ("Tailwind CSS", "CSS framework"),
    "jest": ("Jest", "Testing"),
    "mocha": ("Mocha", "Testing"),
    "vitest": ("Vitest", "Testing"),
    "cypress": ("Cypress", "Testing"),
    "vite": ("Vite", "Build tool"),
    "webpack": ("Webpack", "Build tool"),
    "rollup": ("Rollup", "Build tool"),
    "eslint": ("ESLint", "Linting / formatting"),
    "prettier": ("Prettier", "Linting / formatting"),
}

# (tool name, kind, test). The test gets the lower-case full path and file name.
TOOL_RULES = [
    ("Docker", "Containers",
     lambda p, b: b == "dockerfile" or b.startswith("dockerfile.") or b.endswith(".dockerfile")),
    ("Docker Compose", "Containers",
     lambda p, b: b in {"docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"}),
    ("GitHub Actions", "CI/CD",
     lambda p, b: p.startswith(".github/workflows/") and b.endswith((".yml", ".yaml"))),
    ("GitLab CI", "CI/CD", lambda p, b: b == ".gitlab-ci.yml"),
    ("Travis CI", "CI/CD", lambda p, b: b == ".travis.yml"),
    ("CircleCI", "CI/CD", lambda p, b: p == ".circleci/config.yml"),
    ("Dependabot", "Dependency updates",
     lambda p, b: p in {".github/dependabot.yml", ".github/dependabot.yaml"}),
    ("Make", "Build tool", lambda p, b: b == "makefile"),
    ("tox", "Testing", lambda p, b: b == "tox.ini"),
    ("pre-commit", "Code quality", lambda p, b: b == ".pre-commit-config.yaml"),
    ("Poetry", "Package manager", lambda p, b: b == "poetry.lock"),
    ("Pipenv", "Package manager", lambda p, b: b == "pipfile"),
    ("npm", "Package manager", lambda p, b: b == "package-lock.json"),
    ("Yarn", "Package manager", lambda p, b: b == "yarn.lock"),
    ("pnpm", "Package manager", lambda p, b: b == "pnpm-lock.yaml"),
    ("TypeScript config", "Language tooling", lambda p, b: b == "tsconfig.json"),
    ("ESLint config", "Linting / formatting",
     lambda p, b: b.startswith(".eslintrc") or b.startswith("eslint.config.")),
    ("Prettier config", "Linting / formatting",
     lambda p, b: b.startswith(".prettierrc") or b.startswith("prettier.config.")),
    ("Terraform", "Infrastructure", lambda p, b: b.endswith(".tf")),
    ("Read the Docs", "Documentation", lambda p, b: b in {".readthedocs.yaml", ".readthedocs.yml"}),
    ("EditorConfig", "Code quality", lambda p, b: b == ".editorconfig"),
]


@dataclass
class Finding:
    name: str
    kind: str
    evidence: list[str] = field(default_factory=list)


@dataclass
class DetectionResult:
    languages: list[Finding] = field(default_factory=list)
    frameworks: list[Finding] = field(default_factory=list)
    tools: list[Finding] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    dependency_health: DependencyHealth = field(default_factory=DependencyHealth)


def _in_ignored_folder(path: str) -> bool:
    folders = path.lower().split("/")[:-1]
    return any(folder in IGNORED_FOLDERS for folder in folders)


def select_manifest_paths(paths: list[str]) -> tuple[list[str], int]:
    """Pick dependency files worth reading. Returns (chosen, how many skipped)."""
    candidates = []
    for path in paths:
        base = path.lower().split("/")[-1]
        depth = path.count("/")
        is_manifest = base in {"package.json", "pyproject.toml"} or is_requirements_file(path)
        if is_manifest and depth <= MANIFEST_MAX_DEPTH and not _in_ignored_folder(path):
            candidates.append((depth, path))
    candidates.sort()
    ordered = [path for _, path in candidates]
    return ordered[:MANIFEST_LIMIT], max(0, len(ordered) - MANIFEST_LIMIT)


def detect_languages(languages: dict[str, int]) -> list[Finding]:
    total = sum(languages.values())
    if total <= 0:
        return []
    findings = []
    for name, size in sorted(languages.items(), key=lambda item: -item[1]):
        percent = size / total * 100
        findings.append(
            Finding(
                name,
                "Language",
                [f"GitHub language statistics: {size:,} bytes ({percent:.1f}% of detected code)"],
            )
        )
    return findings


def detect_tools(paths: list[str]) -> list[Finding]:
    found: dict[str, Finding] = {}
    for path in paths:
        if _in_ignored_folder(path):
            continue
        lower = path.lower()
        base = lower.split("/")[-1]
        for name, kind, test in TOOL_RULES:
            if test(lower, base):
                finding = found.setdefault(name, Finding(name, kind))
                finding.evidence.append(f"file found: {path}")
    return sorted(found.values(), key=lambda f: (f.kind, f.name))


def detect_frameworks(manifests: dict[str, str]) -> tuple[list[Finding], list[str]]:
    found: dict[str, Finding] = {}
    notes = []
    for path in sorted(manifests):
        try:
            ecosystem, dependencies = parse_manifest(path, manifests[path])
        except ManifestError as error:
            notes.append(f"Could not read {path}: {error}")
            continue
        known = PYPI_PACKAGES if ecosystem == "pypi" else NPM_PACKAGES
        for dep in dependencies:
            entry = known.get(dep.name.lower())
            if not entry:
                continue
            display, kind = entry
            finding = found.setdefault(display, Finding(display, kind))
            version = f" {dep.spec}" if dep.spec else ""
            line = f"{dep.name}{version} in {path} ({dep.group})"
            if line not in finding.evidence:
                finding.evidence.append(line)
    return sorted(found.values(), key=lambda f: (f.kind, f.name)), notes


def detect_technologies(languages, paths, manifests) -> DetectionResult:
    """Pure function: facts in, findings out. No internet here."""
    result = DetectionResult()
    result.languages = detect_languages(languages)
    if not result.languages:
        result.notes.append("GitHub did not report any programming languages for this repository.")
    result.tools = detect_tools(paths)
    result.frameworks, notes = detect_frameworks(manifests)
    result.notes.extend(notes)
    result.dependency_health = inspect_dependencies(manifests)
    if not manifests:
        result.notes.append(
            "No supported dependency files found (requirements*.txt, pyproject.toml, "
            "package.json), so frameworks could not be detected from dependencies."
        )
    return result


def analyze_technologies(client, owner: str, repo: str, branch: str) -> DetectionResult:
    """Collect facts from GitHub, then detect. Uses 2 API requests plus raw downloads."""
    languages = client.get_languages(owner, repo)
    entries, truncated = client.get_file_tree(owner, repo, branch)
    paths = [entry["path"] for entry in entries if entry["type"] == "blob"]

    chosen, skipped = select_manifest_paths(paths)
    manifests = {}
    notes = []
    for path in chosen:
        try:
            manifests[path] = client.get_file_text(owner, repo, branch, path)
        except RateLimitError:
            raise
        except AnalyzerError as error:
            notes.append(f"Could not download {path}: {error}")

    result = detect_technologies(languages, paths, manifests)
    result.notes = notes + result.notes
    if skipped:
        result.notes.append(
            f"Read the {len(chosen)} closest dependency files and skipped {skipped} more."
        )
    if truncated:
        result.notes.append(
            "GitHub cut the file list because the repository is very large, "
            "so some files and tools may be missing from this analysis."
        )
    return result