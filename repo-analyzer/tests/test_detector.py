from analyzer.detector import (
    analyze_technologies,
    detect_languages,
    detect_technologies,
    detect_tools,
    select_manifest_paths,
)
from analyzer.errors import NotFoundError, RateLimitError


def by_name(findings):
    return {f.name: f for f in findings}


# ---------- languages ----------

def test_languages_percent_and_order():
    found = detect_languages({"Python": 750, "Shell": 250})
    assert [f.name for f in found] == ["Python", "Shell"]
    assert "750 bytes" in found[0].evidence[0]
    assert "75.0%" in found[0].evidence[0]


def test_languages_empty():
    assert detect_languages({}) == []
    assert detect_languages({"Python": 0}) == []


# ---------- frameworks ----------

def test_frameworks_from_requirements_with_evidence():
    result = detect_technologies({}, [], {"requirements.txt": "Django>=4.2\npytest\n"})
    found = by_name(result.frameworks)
    assert set(found) == {"Django", "pytest"}
    assert found["Django"].evidence == ["django >=4.2 in requirements.txt (requirements)"]


def test_frameworks_from_package_json():
    text = '{"dependencies": {"react": "^18", "react-dom": "^18"}, "devDependencies": {"jest": "1"}}'
    found = by_name(detect_technologies({}, [], {"package.json": text}).frameworks)
    assert set(found) == {"React", "Jest"}  # react-dom is NOT mistaken for react


def test_similar_names_are_not_confused():
    text = "django-extensions\nflask-login\ntorchvision\n"
    result = detect_technologies({}, [], {"requirements.txt": text})
    assert result.frameworks == []


def test_same_framework_in_two_files_collects_both_evidences():
    manifests = {"requirements.txt": "flask", "api/requirements.txt": "flask==3.0"}
    found = by_name(detect_technologies({}, [], manifests).frameworks)
    assert len(found["Flask"].evidence) == 2


def test_unreadable_manifest_becomes_a_note():
    result = detect_technologies({}, [], {"package.json": "{broken"})
    assert any("package.json" in note for note in result.notes)
    assert result.frameworks == []


def test_no_manifests_gives_honest_note():
    result = detect_technologies({"Go": 10}, ["main.go"], {})
    assert any("No supported dependency files" in n for n in result.notes)
    assert result.frameworks == []


# ---------- tools ----------

def test_tools_detected_by_filename():
    paths = [
        "Dockerfile",
        ".github/workflows/ci.yml",
        ".github/workflows/release.yaml",
        "Makefile",
        "src/app.py",
        "package-lock.json",
    ]
    found = by_name(detect_tools(paths))
    assert set(found) == {"Docker", "GitHub Actions", "Make", "npm"}
    assert len(found["GitHub Actions"].evidence) == 2
    assert found["Docker"].evidence == ["file found: Dockerfile"]


def test_tools_in_vendor_or_test_folders_are_ignored():
    paths = ["vendor/lib/Dockerfile", "tests/fixtures/Makefile", "node_modules/x/yarn.lock"]
    assert detect_tools(paths) == []


def test_no_tool_without_proof():
    assert detect_tools(["README.md", "src/main.py"]) == []


# ---------- picking dependency files ----------

def test_select_manifest_paths_rules():
    paths = [
        "package.json",
        "requirements.txt",
        "requirements-dev.txt",
        "docs/requirements.txt",
        "a/b/c/requirements.txt",       # too deep
        "node_modules/x/package.json",  # ignored folder
        "tests/fixtures/package.json",  # ignored folder
        "src/main.py",
    ]
    chosen, skipped = select_manifest_paths(paths)
    assert chosen == ["package.json", "requirements-dev.txt", "requirements.txt", "docs/requirements.txt"]
    assert skipped == 0


def test_select_manifest_paths_limit():
    paths = [f"app{i}/package.json" for i in range(10)]
    chosen, skipped = select_manifest_paths(paths)
    assert len(chosen) == 6
    assert skipped == 4


# ---------- full flow with a fake client ----------

class FakeClient:
    def __init__(self, languages, entries, files, truncated=False):
        self._languages = languages
        self._entries = entries
        self._files = files
        self._truncated = truncated

    def get_languages(self, owner, repo):
        return self._languages

    def get_file_tree(self, owner, repo, branch):
        return self._entries, self._truncated

    def get_file_text(self, owner, repo, ref, path):
        if path not in self._files:
            raise NotFoundError("missing")
        value = self._files[path]
        if isinstance(value, Exception):
            raise value
        return value


def blobs(*paths):
    return [{"path": p, "type": "blob", "size": 1} for p in paths]


def test_full_flow():
    client = FakeClient(
        {"Python": 100},
        blobs("requirements.txt", "Dockerfile"),
        {"requirements.txt": "fastapi\n"},
    )
    result = analyze_technologies(client, "o", "r", "main")
    assert [f.name for f in result.languages] == ["Python"]
    assert [f.name for f in result.frameworks] == ["FastAPI"]
    assert [f.name for f in result.tools] == ["Docker"]
    assert result.notes == []


def test_full_flow_download_failure_is_a_note_not_a_crash():
    client = FakeClient({"Python": 1}, blobs("requirements.txt"), {})
    result = analyze_technologies(client, "o", "r", "main")
    assert any("Could not download requirements.txt" in n for n in result.notes)


def test_full_flow_rate_limit_is_passed_up():
    client = FakeClient({}, blobs("requirements.txt"), {"requirements.txt": RateLimitError("limit")})
    try:
        analyze_technologies(client, "o", "r", "main")
        assert False, "should have raised"
    except RateLimitError:
        pass


def test_full_flow_truncated_tree_is_mentioned():
    client = FakeClient({"Go": 1}, blobs("main.go"), {}, truncated=True)
    result = analyze_technologies(client, "o", "r", "main")
    assert any("cut the file list" in n for n in result.notes)