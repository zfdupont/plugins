---
name: tune
description: Suggest improvements to this repo's factory from its own record (settings, board, job history) and the project's current state, and apply the ones the owner picks. Use for /factory:tune.
---

# Factory tune

Setup answers "what factory fits this code?". Tune answers "how is this
factory doing, and what should change?".

Read `../run/SKILL.md`, resolved against this skill's base directory, and run
its `## Setup check`. Its `CFG`, `REPO` and settings apply here.

1. Spawn `factory:tuner` with the checkout of `base`, the absolute path of
   `factory/`, and the path of `factory/factory.yaml`. Use `models.tuner`.
   Wait for `factory/tune.md`.
2. Show the first line of `tune.md`, then ask the owner which suggestions to
   apply: one multi-select question, one option per item, in the file's
   order, with `Kind`, `Impact` and the one-line suggestion as the
   description.
3. Sort the chosen items:
   - Changes to `factory.yaml` or to reviewer and QA agent files: read
     `../setup/SKILL.md` and follow its `## Propose and write` section. Build
     `DRAFT/proposed/` as a copy of the current files with only the chosen
     changes applied (setup's survey and proposal steps are skipped). The
     owner sees the diff and approves it there.
   - Backlog items: append each to `backlog.md` as `- [ ] <item>` under a
     `## From tune <date>` heading at the end, or under `## Foundations` for
     `foundations` items.
4. Leave `tune.md` in place; the next tune run overwrites it. Tell the owner
   what changed and that nothing is committed.
