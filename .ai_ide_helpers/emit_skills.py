#!/usr/bin/env python3
"""Regenerate the per-tool SKILL.md variants from the canonical Kiro bodies.

The skill bodies are byte-identical across Claude, Copilot, and Kiro — only the
install directory differs between those tools. This script keeps that true: it
reads each skill under `kiro/skills/`, strips its frontmatter, rebuilds the
frontmatter identically (the portable Agent Skills subset that all three tools
accept), and writes the result to every tool directory.

It also validates what the spec constrains: `name` must match its parent folder,
and `description` must be non-empty and within 1024 characters.

Usage (from anywhere):
    python3 .ai_ide_helpers/emit_skills.py
    python3 .ai_ide_helpers/emit_skills.py --check   # validate only, write nothing
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE_TOOL = "kiro"
TARGET_TOOLS = ("kiro", "claude", "copilot")

NAME_MAX = 64
DESCRIPTION_MAX = 1024
BODY_LINES_SOFT_MAX = 500

LICENSE = "MIT-0"
METADATA: tuple[tuple[str, str], ...] = (
    ("project", "media-contracts-analyzer"),
    ("verified-against", "repository state, September 2026"),
)

FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
NAME_RE = re.compile(r"^name:\s*(.+)$", re.MULTILINE)
DESCRIPTION_RE = re.compile(r"^description:\s*(.+)$", re.MULTILINE)
VALID_NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def build_frontmatter(name: str, description: str) -> str:
    """Render the portable frontmatter block shared by all three tools."""
    lines = [
        "---",
        f"name: {name}",
        f"description: {description}",
        f"license: {LICENSE}",
        "metadata:",
        *(f"  {key}: {value}" for key, value in METADATA),
        "---",
    ]
    return "\n".join(lines) + "\n"


def split_frontmatter(path: Path) -> tuple[str, str]:
    """Return (frontmatter_body, markdown_body). Raises ValueError when malformed."""
    text = path.read_text(encoding="utf-8")
    match = FRONTMATTER_RE.match(text)
    if match is None:
        raise ValueError("no leading '---' frontmatter block")
    return match.group(1), text[match.end() :]


def validate(name: str, description: str, folder: str) -> list[str]:
    """Return a list of spec violations; empty means valid."""
    problems: list[str] = []
    if name != folder:
        problems.append(f"name {name!r} does not match folder {folder!r}")
    if not VALID_NAME_RE.match(name):
        problems.append(f"name {name!r} must be lowercase alphanumeric with single hyphens")
    if len(name) > NAME_MAX:
        problems.append(f"name is {len(name)} chars, max {NAME_MAX}")
    if not description:
        problems.append("description is empty")
    if len(description) > DESCRIPTION_MAX:
        problems.append(f"description is {len(description)} chars, max {DESCRIPTION_MAX}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate the source skills without writing any files",
    )
    args = parser.parse_args()

    source_dir = ROOT / SOURCE_TOOL / "skills"
    if not source_dir.is_dir():
        print(f"ERROR: source directory not found: {source_dir}", file=sys.stderr)
        return 1

    skill_dirs = sorted(p for p in source_dir.iterdir() if p.is_dir())
    if not skill_dirs:
        print(f"ERROR: no skills found under {source_dir}", file=sys.stderr)
        return 1

    failed = False
    written = 0

    for skill_dir in skill_dirs:
        source = skill_dir / "SKILL.md"
        if not source.is_file():
            print(f"ERROR: {skill_dir.name}: missing SKILL.md", file=sys.stderr)
            failed = True
            continue

        try:
            frontmatter, body = split_frontmatter(source)
        except ValueError as exc:
            print(f"ERROR: {skill_dir.name}: {exc}", file=sys.stderr)
            failed = True
            continue

        name_match = NAME_RE.search(frontmatter)
        description_match = DESCRIPTION_RE.search(frontmatter)
        if name_match is None or description_match is None:
            print(
                f"ERROR: {skill_dir.name}: frontmatter must define both name and description",
                file=sys.stderr,
            )
            failed = True
            continue

        name = name_match.group(1).strip()
        description = description_match.group(1).strip()

        problems = validate(name, description, skill_dir.name)
        if problems:
            for problem in problems:
                print(f"ERROR: {skill_dir.name}: {problem}", file=sys.stderr)
            failed = True
            continue

        body_lines = body.count("\n")
        note = "" if body_lines <= BODY_LINES_SOFT_MAX else "  <- over the 500-line guideline"
        print(f"  {name}: description {len(description)} chars, body {body_lines} lines{note}")

        if args.check:
            continue

        rendered = build_frontmatter(name, description) + body
        for tool in TARGET_TOOLS:
            destination = ROOT / tool / "skills" / skill_dir.name / "SKILL.md"
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(rendered, encoding="utf-8")
            written += 1

    if failed:
        print("\nValidation failed; nothing was written for the offending skills.", file=sys.stderr)
        return 1

    if args.check:
        print(f"\nValidated {len(skill_dirs)} skills. No files written (--check).")
    else:
        print(f"\nWrote {written} files: {len(skill_dirs)} skills x {len(TARGET_TOOLS)} tools.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
