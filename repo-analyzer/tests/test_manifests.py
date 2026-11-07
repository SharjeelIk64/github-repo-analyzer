import pytest

from analyzer.manifests import (
    ManifestError,
    is_requirements_file,
    parse_manifest,
    parse_package_json,
    parse_pyproject,
    parse_requirements_txt,
    tomllib,
)

needs_toml = pytest.mark.skipif(tomllib is None, reason="needs Python 3.11+")


def names(deps):
    return [d.name for d in deps]


def test_requirements_basic():
    text = """
# a comment
Django>=4.2,<5   # inline comment
requests==2.31.0
Flask_Login
numpy
"""
    deps = parse_requirements_txt(text)
    assert names(deps) == ["django", "requests", "flask-login", "numpy"]
    assert deps[0].spec == ">=4.2,<5"
    assert deps[2].spec == ""


def test_requirements_skips_options_and_links():
    text = """
-r other.txt
-e .
--index-url https://example.com/simple
git+https://github.com/x/y.git#egg=y
https://example.com/pkg.whl
./local/folder
"""
    assert parse_requirements_txt(text) == []


def test_requirements_extras_and_markers():
    deps = parse_requirements_txt('uvicorn[standard]>=0.20 ; python_version >= "3.9"')
    assert names(deps) == ["uvicorn"]
    assert deps[0].spec == ">=0.20"


def test_requirements_direct_reference_keeps_name():
    deps = parse_requirements_txt("mypkg @ https://example.com/mypkg.zip")
    assert names(deps) == ["mypkg"]


def test_package_json_sections():
    text = """{"dependencies": {"react": "^18.2.0"},
               "devDependencies": {"jest": "^29"},
               "scripts": {"test": "jest"}}"""
    deps = parse_package_json(text)
    assert [(d.name, d.spec, d.group) for d in deps] == [
        ("react", "^18.2.0", "dependencies"),
        ("jest", "^29", "devDependencies"),
    ]


def test_package_json_without_dependencies_is_empty_not_error():
    assert parse_package_json('{"name": "x"}') == []


@pytest.mark.parametrize("bad", ["not json", "[1, 2]", ""])
def test_package_json_bad_input(bad):
    with pytest.raises(ManifestError):
        parse_package_json(bad)


@needs_toml
def test_pyproject_pep621():
    text = """
[project]
dependencies = ["Django>=4.2", "requests"]
[project.optional-dependencies]
dev = ["pytest>=7"]
"""
    deps = {(d.name, d.group) for d in parse_pyproject(text)}
    assert ("django", "project.dependencies") in deps
    assert ("requests", "project.dependencies") in deps
    assert ("pytest", "optional-dependencies.dev") in deps


@needs_toml
def test_pyproject_poetry_ignores_python():
    text = """
[tool.poetry.dependencies]
python = "^3.10"
fastapi = "^0.110"
httpx = { version = "^0.27", optional = true }
[tool.poetry.group.dev.dependencies]
pytest = "^8"
"""
    deps = parse_pyproject(text)
    assert "python" not in names(deps)
    assert {"fastapi", "httpx", "pytest"} <= set(names(deps))


@needs_toml
def test_pyproject_without_dependency_sections_is_empty():
    assert parse_pyproject("[build-system]\nrequires = []") == []


@needs_toml
def test_pyproject_invalid_toml():
    with pytest.raises(ManifestError):
        parse_pyproject("this is = = not toml [")


@pytest.mark.parametrize(
    "path,expected",
    [
        ("requirements.txt", True),
        ("requirements-dev.txt", True),
        ("sub/Requirements_test.txt", True),
        ("requirements/base.txt", True),
        ("notes.txt", False),
        ("requirements.md", False),
    ],
)
def test_is_requirements_file(path, expected):
    assert is_requirements_file(path) is expected


def test_parse_manifest_dispatch():
    assert parse_manifest("package.json", "{}") == ("npm", [])
    assert parse_manifest("requirements.txt", "flask")[0] == "pypi"


def test_parse_manifest_unsupported():
    with pytest.raises(ManifestError):
        parse_manifest("README.md", "hello")