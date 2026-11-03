---
name: scout
description: Find backlog items for the factory. Use for /factory:scout (small features) and /factory:scout foundations (gaps the factory needs filled - tests, lint, rules, QA, CI).
---

Read `../run/SKILL.md`, resolved against this skill's base directory. Treat
that file's base directory as the factory skill's base directory (its `CFG`
and `schema.md` are there). Run its `## Setup check`.

- If the arguments are `foundations`: read `../setup/SKILL.md` the same way and
  follow its `## Foundations` section.
- Otherwise: follow the run skill's `## scout` section.

Arguments: $ARGUMENTS
