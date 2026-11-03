---
name: arbitrate
description: Run the factory arbiter on a job waiting on the owner. Use for /factory:arbitrate <job-id>.
---

Read `../run/SKILL.md`, resolved against this skill's base directory. Treat
that file's base directory as the factory skill's base directory (its `CFG`
and `schema.md` are there). Run its `## Setup check`, then follow its
`## arbitrate` section with these arguments: $ARGUMENTS
