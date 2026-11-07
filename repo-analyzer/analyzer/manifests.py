"""Reads dependency files: requirements.txt, package.json, pyproject.toml.

This file only understands the *text* of these files. It never uses the
internet, so it is easy to test.
"""

import json
import re
from dataclasses import dataclass

try:
    import tomllib  # built into Python 3.11 and newer
except ImportError:  # older Python
    tomllib = None


class ManifestError(ValueError):
    """A dependency file could not be read or is not supported."""


@dataclass(frozen=True)
class Dependency:
    name: str   # package name (Python names are normalised to lower-case with "-")
    spec: str   # version text exactly as written in the file ("" if none)
    group: str  # where it was listed, e.g. "dependencies" or "requirements"


def normalize_python_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


# name, optional [extras], then the rest (version rules, markers...)
_PEP508 = re.compile(
    r"^\s*([A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)\s*(?:\[[^\]]*\])?\s*(.*)$"
)
_ALLOWED_AFTER_NAME = "<>=!~@;(,"


def _parse_python_requirement(text: str, group: str) -> Dependency | None:
    match = _PEP508.match(text)
    if not match:
        return None
    name, rest = match.group(1), match.group(2).strip()
    if rest and rest[0] not in _ALLOWED_AFTER_NAME:
        return None  # e.g. "git+https://..." is a link, not a package name
    spec = rest.split(";")[0].strip().rstrip("\\").strip()
    return Dependency(normalize_python_name(name), spec, group)


def parse_requirements_txt(text: str) -> list[Dependency]:
    dependencies = []
    for raw_line in text.splitlines():
        line = raw_line.split(" #")[0].strip()
        if not line or line.startswith(("#", "-")):
            continue  # blank, comment, or an option like "-r other.txt"
        dependency = _parse_python_requirement(line, "requirements")
        if dependency:
            dependencies.append(dependency)
    return dependencies


def parse_package_json(text: str) -> list[Dependency]:
    try:
        data = json.loads(text)
    except ValueError:
        raise ManifestError("package.json is not valid JSON")
    if not isinstance(data, dict):
        raise ManifestError("package.json does not contain a JSON object")

    dependencies = []
    for section in (
        "dependencies",
        "devDependencies",
        "peerDependencies",
        "optionalDependencies",
    ):
        block = data.get(section)
        if not isinstance(block, dict):
            continue
        for name, spec in block.items():
            dependencies.append(Dependency(str(name), str(spec), section))
    return dependencies


def parse_pyproject(text: str) -> list[Dependency]:
    if tomllib is None:
        raise ManifestError("reading pyproject.toml needs Python 3.11 or newer")
    try:
        data = tomllib.loads(text)
    except ValueError:
        raise ManifestError("pyproject.toml is not valid TOML")

    dependencies = []

    def add_list(items, group):
        if isinstance(items, list):
            for item in items:
                if isinstance(item, str):
                    dep = _parse_python_requirement(item, group)
                    if dep:
                        dependencies.append(dep)

    project = data.get("project") if isinstance(data.get("project"), dict) else {}
    add_list(project.get("dependencies"), "project.dependencies")
    optional = project.get("optional-dependencies")
    if isinstance(optional, dict):
        for extra, items in optional.items():
            add_list(items, f"optional-dependencies.{extra}")

    groups = data.get("dependency-groups")
    if isinstance(groups, dict):
        for group_name, items in groups.items():
            add_list(items, f"dependency-groups.{group_name}")

    def add_poetry(table, group):
        if not isinstance(table, dict):
            return
        for name, value in table.items():
            if str(name).lower() == "python":
                continue
            if isinstance(value, str):
                spec = value
            elif isinstance(value, dict):
                spec = str(value.get("version", ""))
            else:
                spec = ""
            dependencies.append(Dependency(normalize_python_name(str(name)), spec, group))

    tool = data.get("tool") if isinstance(data.get("tool"), dict) else {}
    poetry = tool.get("poetry") if isinstance(tool.get("poetry"), dict) else {}
    add_poetry(poetry.get("dependencies"), "poetry.dependencies")
    poetry_groups = poetry.get("group")
    if isinstance(poetry_groups, dict):
        for group_name, group_data in poetry_groups.items():
            if isinstance(group_data, dict):
                add_poetry(group_data.get("dependencies"), f"poetry.group.{group_name}")

    return dependencies


def is_requirements_file(path: str) -> bool:
    parts = path.lower().split("/")
    base = parts[-1]
    if re.match(r"^requirements.*\.txt$", base):
        return True
    return base.endswith(".txt") and len(parts) >= 2 and parts[-2] == "requirements"


def parse_manifest(path: str, text: str) -> tuple[str, list[Dependency]]:
    """Return (ecosystem, dependencies). Ecosystem is "pypi" or "npm"."""
    base = path.lower().split("/")[-1]
    if base == "package.json":
        return "npm", parse_package_json(text)
    if base == "pyproject.toml":
        return "pypi", parse_pyproject(text)
    if is_requirements_file(path):
        return "pypi", parse_requirements_txt(text)
    raise ManifestError(f"{path} is not a supported dependency file")