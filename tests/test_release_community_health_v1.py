from __future__ import annotations

from pathlib import Path
import tomllib


ROOT = Path(__file__).resolve().parents[1]


COMMUNITY_FILES = (
    "CITATION.cff",
    "CONTRIBUTING.md",
    "CODE_OF_CONDUCT.md",
    "SECURITY.md",
    "SUPPORT.md",
    ".github/PULL_REQUEST_TEMPLATE.md",
    ".github/ISSUE_TEMPLATE/bug_report.yml",
    ".github/ISSUE_TEMPLATE/feature_request.yml",
    ".github/ISSUE_TEMPLATE/config.yml",
)


def _text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_required_community_files_exist() -> None:
    for relative in COMMUNITY_FILES:
        assert (ROOT / relative).is_file(), relative


def test_citation_tracks_project_identity_and_version() -> None:
    project = tomllib.loads(_text("pyproject.toml"))["project"]
    citation = _text("CITATION.cff")
    assert "cff-version: 1.2.0" in citation
    assert 'title: "Noetrium: Reproducible Research Infrastructure for AI Agents"' in citation
    assert '- name: "Noetrium contributors"' in citation
    assert f'version: "{project["version"]}"' in citation
    assert "license: Apache-2.0" in citation
    assert 'repository-code: "https://github.com/Xalzeroph/noetrium"' in citation


def test_issue_forms_are_structured_and_route_sensitive_reports() -> None:
    bug = _text(".github/ISSUE_TEMPLATE/bug_report.yml")
    feature = _text(".github/ISSUE_TEMPLATE/feature_request.yml")
    chooser = _text(".github/ISSUE_TEMPLATE/config.yml")
    for form in (bug, feature):
        assert "name:" in form
        assert "description:" in form
        assert "body:" in form
        assert "required: true" in form
    assert "Noetrium version or exact commit" in bug
    assert "Ownership and contract boundary" in feature
    assert "blank_issues_enabled: false" in chooser
    assert "https://github.com/Xalzeroph/noetrium/discussions" in chooser
    assert "https://github.com/Xalzeroph/noetrium/security/policy" in chooser


def test_pull_request_template_requires_review_evidence() -> None:
    template = _text(".github/PULL_REQUEST_TEMPLATE.md")
    for token in (
        "## Ownership and contracts",
        "## Evidence",
        "## Failure and recovery impact",
        "exact revision",
        "fail-closed",
    ):
        assert token in template


def test_readme_surfaces_community_entry_points() -> None:
    readme = _text("README.md")
    for target in (
        "CONTRIBUTING.md",
        "SECURITY.md",
        "SUPPORT.md",
        "CITATION.cff",
        "CODE_OF_CONDUCT.md",
    ):
        assert f"]({target})" in readme

def test_project_metadata_surfaces_community_urls() -> None:
    urls = tomllib.loads(_text("pyproject.toml"))["project"]["urls"]
    assert urls["Discussions"] == "https://github.com/Xalzeroph/noetrium/discussions"
    assert urls["Security"] == "https://github.com/Xalzeroph/noetrium/security/policy"
    assert urls["Contributing"].endswith("/CONTRIBUTING.md")
    assert urls["Citation"].endswith("/CITATION.cff")
