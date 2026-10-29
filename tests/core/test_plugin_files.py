"""The Claude plugin layer: manifests, skills, agent, commands and docs stay consistent."""

import json
import re
from pathlib import Path

import pytest
import yaml

from asb.cli import app

ROOT = Path(__file__).resolve().parents[2]
SKILLS = [
    "asb-requirements",
    "asb-discovery",
    "asb-design",
    "asb-build",
    "asb-verify",
    "asb-release",
]
COMMANDS = ["asb-new", "asb-status", "asb-approve"]
DOCS = [
    "README.md",
    "CHANGELOG.md",
    "docs/user-guide.md",
    "docs/architecture.md",
    "docs/writing-a-pack.md",
    "docs/writing-a-connector.md",
]


def frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"---\n(.*?)\n---\n", text, re.DOTALL)
    assert match, f"{path}: no YAML frontmatter"
    data = yaml.safe_load(match.group(1))
    assert isinstance(data, dict), f"{path}: frontmatter is not a mapping"
    return data


def test_skill_folders_are_exactly_the_six_stages():
    found = sorted(p.name for p in (ROOT / "core" / "skills").iterdir() if p.is_dir())
    assert found == sorted(SKILLS)


@pytest.mark.parametrize("name", SKILLS)
def test_skill_frontmatter(name):
    data = frontmatter(ROOT / "core" / "skills" / name / "SKILL.md")
    assert data["name"] == name
    assert str(data.get("description", "")).strip()


def test_plugin_manifest_paths_exist():
    data = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text("utf-8"))
    assert data["name"] == "ai-solution-builder"
    assert data["version"] == "0.1.0"
    assert data["author"]["name"] == "Aexons"
    for key in ("skills", "agents", "commands", "hooks"):
        path = ROOT / data[key]
        assert path.exists(), f"plugin.json {key}: {data[key]} does not exist"
    assert (ROOT / data["hooks"]).is_file()
    json.loads((ROOT / data["hooks"]).read_text("utf-8"))


def test_marketplace_manifest():
    data = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text("utf-8"))
    assert data["name"] == "aexons-asb"
    assert data["owner"]["name"] == "Aexons"
    (plugin,) = data["plugins"]
    assert plugin["name"] == "ai-solution-builder"
    assert plugin["source"] == "./"
    assert plugin["description"].strip()
    manifest = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text("utf-8"))
    assert plugin["version"] == manifest["version"]


def test_reviewer_agent():
    data = frontmatter(ROOT / "core" / "agents" / "asb-reviewer.md")
    assert data["name"] == "asb-reviewer"
    assert str(data["description"]).strip()
    tools = {t.strip() for t in str(data["tools"]).split(",")}
    assert tools == {"Read", "Grep", "Glob", "Bash"}
    assert data["model"] == "inherit"


@pytest.mark.parametrize("name", COMMANDS)
def test_command_frontmatter(name):
    data = frontmatter(ROOT / "core" / "commands" / f"{name}.md")
    assert str(data["description"]).strip()
    assert "argument-hint" in data


def test_approve_command_is_human_only():
    text = (ROOT / "core" / "commands" / "asb-approve.md").read_text("utf-8").lower()
    assert "human" in text
    assert "explicit yes" in text


def _text_files() -> list[Path]:
    files = [ROOT / d for d in DOCS]
    for folder in ("skills", "agents", "commands"):
        files += sorted((ROOT / "core" / folder).rglob("*.md"))
    return files


def test_docs_exist():
    for doc in DOCS:
        assert (ROOT / doc).read_text("utf-8").strip(), doc


def test_every_cli_subcommand_mentioned_exists():
    commands = {c.name for c in app.registered_commands}
    assert {"new", "approve", "verify", "discover", "build"} <= commands
    pattern = re.compile(
        r"(?:`|^[ \t]*(?:\$ )?(?:uv run )?)asb ([a-z][a-z-]*)", re.MULTILINE
    )
    mentioned: set[str] = set()
    for path in _text_files():
        for sub in pattern.findall(path.read_text("utf-8")):
            assert sub in commands, f"{path.relative_to(ROOT)}: unknown `asb {sub}`"
            mentioned.add(sub)
    assert {"new", "status", "approve", "build", "verify"} <= mentioned


def test_core_stays_neutral():
    bad = []
    for path in (ROOT / "core").rglob("*"):
        if path.is_file() and "__pycache__" not in path.parts:
            text = path.read_text("utf-8", errors="ignore")
            if re.search(r"erpnext|frappe|django", text, re.IGNORECASE):
                bad.append(str(path.relative_to(ROOT)))
    assert bad == []


def test_skills_never_run_human_only_commands():
    """Every skill states the boundary: the human runs approve/use, the AI never does."""
    for name in SKILLS:
        text = (ROOT / "core" / "skills" / name / "SKILL.md").read_text("utf-8")
        assert "never run `asb approve`" in text.lower(), name
