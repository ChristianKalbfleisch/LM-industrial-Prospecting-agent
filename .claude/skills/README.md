# Skills — the drop-in folder

This is where you put anything new you build for Claude Code that should be
**remembered across sessions**. Add a folder here, commit it, and it is available in
every future conversation in this repo — no need to re-explain it.

## Where knowledge should live

| Kind of knowledge | Put it in | Loaded |
|---|---|---|
| Always relevant (project purpose, conventions, glossary) | `CLAUDE.md` | Every session, automatically |
| Reference material, read on demand | `docs/*.md` | When asked, or when linked from CLAUDE.md |
| A procedure for a specific kind of task | `.claude/skills/<name>/` | Automatically, when the task matches the description |

The distinction matters for context budget. `CLAUDE.md` is loaded into *every*
conversation, so it should stay short. A skill's body is only pulled in when its
`description` matches what is being worked on, so a growing library of them stays
cheap. When in doubt, write a skill.

## Adding a skill

Create `.claude/skills/<skill-name>/SKILL.md`:

```markdown
---
name: pull-budget-review
description: Review and rank title-pull candidates against the current budget. Use when deciding which addresses or postal codes to spend title pulls on, or when auditing the cost per qualified lead of a past batch.
---

# Pull budget review

## When to use this
...

## Steps
1. ...
2. ...

## Output format
...
```

Only `name` and `description` are required in the frontmatter. Everything below is
the instructions.

**The `description` is the most important line in the file.** It is what gets matched
against the task at hand, so write it as *when to use this*, in the words you would
actually use — not as a title. `"Use when deciding which addresses to spend title
pulls on"` triggers reliably; `"Title utilities"` does not.

## Supporting files

Anything else in the folder is loaded only if the skill instructions point to it:

```
.claude/skills/pull-budget-review/
  SKILL.md          <- always read when the skill triggers
  scoring.md        <- read only if SKILL.md says to
  score_batch.py    <- run, not read
```

Keep `SKILL.md` under a few hundred lines and push detail into supporting files.

## Personal vs. shared

- `.claude/skills/` (here) — committed, travels with the repo, available to anyone
  who clones it, and available in Claude Code on the web.
- `~/.claude/skills/` — your machine only, applies to every project, not committed.

Put anything about *this business* here. Put personal cross-project habits in
`~/.claude/skills/`.

> One caveat for web and remote sessions: they run in a fresh container that is
> discarded afterward, so only files **committed to the repo** persist. `~/.claude/`
> edits made in a web session do not survive.
