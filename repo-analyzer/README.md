# GitHub Repository Analyzer

A small Python CLI that inspects public GitHub repositories using the GitHub REST API.

## Setup

Requirements: Python 3.11 or newer and internet access.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

The analyzer works without a token, but GitHub's unauthenticated API limit is lower. To use a token, set `GITHUB_TOKEN` in the current PowerShell session; never put a real token in source control:

```powershell
$env:GITHUB_TOKEN = "your-token"
```

## Usage

```powershell
python main.py https://github.com/psf/requests
```

The argument must identify a GitHub repository. Invalid URLs, missing/private repositories, rate limits, network errors, and API errors are reported without exposing the token. Each analysis section is handled independently where possible.

## Features

- Repository metadata, GitHub language statistics, known frameworks/libraries, and tooling inferred from file names.
- File structure: tracked file count, top-level folder counts, file extensions, and a likely purpose for recognized extensions. Unrecognized types are labeled as undetermined.
- Dependency inventory from `requirements*.txt`, `pyproject.toml`, and `package.json`, including declared version text and evidence location. Entries are labeled `Exact pinned version`, `Version range`, or `Version not specified`; these labels do not imply health or outdatedness.
- The tool does not query package registries, so it does not claim that a dependency is outdated, vulnerable, or abandoned. No supported dependency file means health could not be assessed.
- A monthly terminal chart of commits in the current and preceding 11 calendar months, plus a top-contributor summary from fetched commit authors. The GitHub API query is bounded to at most 1,000 commits; the report notes when this cap is reached.
- GitHub API request-limit status when returned by the API.

## Complexity score

The 0–100 score is a structural proxy based on GitHub's file tree, not a source-code parser:

```text
score = 40 * min(source_files / 100, 1)
      + 30 * min(source_bytes / 10,485,760, 1)
      + 30 * min(max_source_folder_depth / 10, 1)
```

It combines source-file count (up to 40 points), source bytes (up to 30), and deepest source-file path (up to 30). Source extensions are a fixed list in `analyzer/analysis.py`; file sizes come from the GitHub tree. The score is capped at 100 and rounded to one decimal place. It does not measure branching, maintainability, runtime complexity, test quality, or architectural difficulty. A truncated GitHub tree can make the measured inputs incomplete, and size/depth are only rough proxies.

## Dependencies and Libraries

- `requests` for GitHub API and public raw-file requests.
- `rich` for terminal tables and output.
- `pytest` for tests.
- Python standard library for URL parsing, JSON/TOML parsing, dates, and analysis.

No additional runtime dependency is used. TOML parsing uses `tomllib` from Python 3.11+.

## Tests and saved demos

Run the test suite:

```powershell
python -m pytest -q
```

Complete outputs for the two public repository demos are saved in `demos/`. To reproduce them after setting `GITHUB_TOKEN` if anonymous API access is rate-limited:

```powershell
python main.py https://github.com/psf/requests | Tee-Object demos/psf-requests.txt
python main.py https://github.com/pallets/flask | Tee-Object demos/pallets-flask.txt
```

GitHub results change over time. Do not treat a rate-limit error as a successful repository demo.