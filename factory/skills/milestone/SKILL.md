---
name: milestone
description: Run a whole milestone from the repo's milestones file as one factory job, with one builder, one review pass and auto-merge unless a step is flagged. Use for /factory:milestone <N> [<N> ...].
---

Read `../run/SKILL.md`, resolved against this skill's base directory. Treat
that file's base directory as the factory skill's base directory (its `CFG`
and `schema.md` are there). Run its `## Setup check`, then follow its
`## milestone` section with these arguments: $ARGUMENTS
