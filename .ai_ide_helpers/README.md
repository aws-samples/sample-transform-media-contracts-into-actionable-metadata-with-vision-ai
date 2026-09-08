# AI IDE Helpers — Agent Skills

Canonical, version-controlled [Agent Skills](https://agentskills.io/specification) that give a coding
assistant accurate, grounded knowledge of this repository without it having to rediscover the codebase
each session.

Three copies are kept here, one per assistant, because each tool loads skills from a different
directory. **The skill bodies are byte-identical** — only the install location differs.

## The four skills

| Skill | Answers |
| --- | --- |
| `media-contracts-architecture` | How does the system work? Where does a component live? What does this module do? How does a job flow from upload to summary? Where are the S3 keys and job state? |
| `media-contracts-prompts-and-schema` | How are the XML system prompts composed? What is MCS v1.0? Why is validation failing? How do I add a specialist end to end? |
| `media-contracts-deployment` | How do I deploy, resume a failed deploy, or tear down? What are the 17 CDK stacks and their order? What is this stack/bucket/parameter called? |
| `media-contracts-local-dev` | How do I run this locally? Which port? Where is the build / lint / type-check / test command? What conventions should my code match? |

Each skill also records **confirmed code-vs-doc discrepancies**, so the assistant trusts the code over a
stale docstring instead of confidently repeating a wrong path.

## Install

Skills are discovered by directory, so installing is a copy. Run these from the repo root.

### Claude Code

```bash
mkdir -p .claude/skills
cp -R .ai_ide_helpers/claude/skills/. .claude/skills/
```

Personal (all your projects) instead of project-scoped: copy into `~/.claude/skills/`.
Claude Code watches skill directories, so a new or edited skill is picked up **without a restart** —
unless you just created the top-level `skills` directory, in which case restart once.

### GitHub Copilot

```bash
mkdir -p .github/skills
cp -R .ai_ide_helpers/copilot/skills/. .github/skills/
```

`.github/skills` is Copilot's project location and works with the cloud agent, Copilot code review,
the Copilot CLI, and agent mode in VS Code. Personal scope is `~/.copilot/skills/`.

### Kiro

```bash
mkdir -p .kiro/skills
cp -R .ai_ide_helpers/kiro/skills/. .kiro/skills/
```

Personal instead of workspace: `~/.kiro/skills/`. Workspace wins over global on a name clash. Custom
agents do **not** load skills by default — add them explicitly:

```json
{ "resources": ["skill://.kiro/skills/*/SKILL.md"] }
```

### Heads-up: the install targets are gitignored

`.gitignore` ignores `.kiro/` and `.claude/` (lines 51–52). Copies placed there will not be committed
unless force-added. That is why the canonical copies live here in `.ai_ide_helpers/`, which is tracked.

`.github/` is **not** ignored, so a Copilot install at `.github/skills/` will show up as a normal change.
Either commit it deliberately or keep using the copy in this directory.

## Using them

All three assistants use the same two activation paths:

- **Automatic** — the tool matches your request against each skill's `description` and loads the body
  when it fits. This is why the descriptions are written with the words you would actually type
  ("how does the pipeline work", "add a specialist", "resume a failed deploy").
- **Explicit** — `/media-contracts-architecture` in Claude Code and Kiro. Trailing text is passed
  through as extra context.

Only `name` and `description` sit in context at rest (~100 tokens per skill). The body loads on demand.

## Frontmatter

Every file uses the same portable subset, valid for all three tools:

```yaml
---
name: media-contracts-architecture      # required; lowercase, hyphens, must match the folder name
description: ...                        # required; what it covers and when to use it
license: MIT-0                          # optional
metadata:                               # optional free-form map
  project: media-contracts-analyzer
  verified-against: repository state, September 2026
---
```

Constraints observed: `name` 1–64 chars, lowercase alphanumeric plus hyphens, no leading/trailing or
doubled hyphens, matching the parent directory. `description` 1–1024 chars (longest here is 499).
Bodies are kept under 500 lines, per the spec's guidance.

### Where the tools genuinely differ

| | Claude Code | Copilot | Kiro |
| --- | --- | --- | --- |
| Project dir | `.claude/skills/` | `.github/skills/` (also accepts `.claude/skills/`, `.agents/skills/`) | `.kiro/skills/` |
| Personal dir | `~/.claude/skills/` | `~/.copilot/skills/`, `~/.agents/skills/` | `~/.kiro/skills/` |
| `name` semantics | display label only; the **folder** sets the `/command` | identifier, normally matches the folder | **must** match the folder |
| Extra frontmatter | many Claude-only fields (`when_to_use`, `paths`, `context: fork`, `allowed-tools`, …) | `allowed-tools` | spec subset only |
| Live reload | yes | — | — |

These skills deliberately avoid the Claude-only fields. Adding any of them would make the file fail
validation on `claude.ai` upload and on `gh skill publish`, and would break the shared-body arrangement.
Because none of these skills bundle or execute a script, none needs `allowed-tools` — leave it off so
Copilot still asks before running anything.

## Maintaining them

`.ai_ide_helpers/kiro/skills/` holds the editable source. Edit there, then regenerate the other two so
they cannot drift:

```bash
python3 .ai_ide_helpers/emit_skills.py
```

The script strips each source file's frontmatter, rebuilds it identically for all three tools, and
validates that `name` matches its folder. It reports each description's length and body line count so
you can see when one is approaching a limit.

When you change the codebase in a way these skills describe — a new specialist, a new stack, a renamed
S3 prefix, a fixed bug listed under "known discrepancies" — update the relevant skill in the same
change. A confidently wrong skill is worse than no skill.
