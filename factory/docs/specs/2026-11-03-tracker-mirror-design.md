# Tracker mirror: design

Status: draft for owner review. Date: 2026-11-03. Target: factory v2.

## Intent

The owner asked whether the factory could show its work in ClickUp or Jira.
The agreed direction is an optional, one-way mirror: every job on
`factory/board.json` gets a card on a kanban board in the tracker, and the card
follows the job as it moves. ClickUp first, Jira second.

This is a view, like `dashboard.html`, not a second state store. The factory
design's non-goal "GitHub issues or project boards as the state store" still
holds.

## Constraints

1. `factory/board.json` stays the source of truth. Nothing read from the
   tracker changes a job.
2. Agents keep talking only through files. The mirror agent gets paths, reads
   files, and writes its own file.
3. A tracker outage, a missing connector, or a bad mapping must never stall,
   fail, or change the stage of a job.

## Goals

1. Opt-in per repo with one new optional `factory.yaml` key, `tracker`. No key,
   no behavior change, no extra cost.
2. One card per job, created on the first board write that includes the job.
3. The card's column follows the job's stage. `arbitration` and `needs-human`
   both land in one BLOCKED column, tagged with which one, as on the dashboard.
4. The card's description shows what the dashboard card shows: note, round,
   rework count, and the review chips for every round.
5. The mirror catches up on its own after an outage: it syncs state, not events.

## Non-goals

- Two-way sync (see the last section).
- Backlog items, scout items, or follow-ups as cards. Only jobs.
- Mirroring job files (spec, reviews, decisions). Only board fields leave the
  machine.
- Creating or changing the tracker's lists, statuses, workflows, or tags. The
  owner sets those up once; the mirror checks them.
- Deleting or archiving cards.
- Dashboard changes.

## Design

### Overview

```
orchestrator rewrites board.json
  -> CFG mirror-plan REPO          local, no network, < 1 s
       nothing to do / disabled / busy / backoff -> done, loop continues
       ops pending                               -> spawn factory:mirror in background
  -> loop continues at once (never waits for the mirror)

factory:mirror (background, own context)
  -> repeat up to 3 passes:
       CFG mirror-lock REPO              busy -> stop (another agent has it)
       CFG mirror-plan REPO -> ops
       for each op: tracker MCP calls (create or update one card)
       CFG mirror-record REPO ...        (card id + hash, or the error)
       CFG mirror-unlock REPO
       CFG mirror-plan REPO              status not ops -> stop
```

Two parts:

- **Planner** (`factory_config.py`, deterministic, tested): reads `board.json`,
  the `tracker` config, and the mirror state; renders the card each job should
  have; compares a hash of it with the last pushed hash; prints the operations
  still to do. All mapping decisions live here, not in a prompt.
- **Executor** (`factory:mirror` agent): turns each operation into calls on the
  tracker's MCP server and records the outcome. It makes no mapping decisions.

The split keeps the mapping testable, keeps the model's job small enough for a
cheap model, and lets a later executor (for example a REST script) reuse the
planner unchanged.

### Where the sync hooks in

In `skills/run/SKILL.md`, the Board section gets one sentence: after every
rewrite of `board.json`, run `## Mirror`. Every board write already goes
through the orchestrator (it is the only writer), so this one hook covers every
stage change, chip update, and note.

New section `## Mirror` in `skills/run/SKILL.md`:

1. If `tracker` is not set, do nothing.
2. Run `CFG mirror-plan REPO`. If `status` is not `ops`, do nothing.
3. Otherwise spawn `factory:mirror` in the background with REPO and the
   absolute path of this skill's base directory. Do not wait for it. Its
   completion does not count toward any WAIT FOR ALL.
4. When a mirror agent finishes and its last line starts with `ERROR`, tell
   the user that line once per run (`tracker mirror: <reason>; the board is
   unaffected`). Never change a stage, note, or verdict because of it.

Rules section gains: "The mirror never blocks the loop. Never wait for it, and
never act on what it reports except to tell the user."

Options considered:

| option | how | why not |
|---|---|---|
| A. Inline MCP calls by the orchestrator | the orchestrator calls the tracker tools itself after each rewrite | an MCP call that hangs or retries holds the orchestrator's turn, so an outage stalls the job (breaks constraint 3); it also fills the orchestrator's context with tracker responses |
| **B. Background mirror agent (chosen)** | planner script plus a background executor agent | costs a small agent run per burst of board writes; mitigated by coalescing below |
| C. Standalone REST script, run in the background | `factory_mirror.py` calls the ClickUp and Jira REST APIs | needs an API token in the environment (ClickUp personal tokens have full workspace access), and the plugin would own two HTTP clients; MCP uses the owner's existing OAuth connector. Kept as the fallback executor if B proves slow or costly |
| D. A Claude Code hook on writes to `board.json` | `PostToolUse` hook runs a script | hooks run outside the orchestrator and cannot reach MCP tools, so it reduces to C plus hook setup in every repo |

Coalescing: the orchestrator often writes the board several times in a few
seconds (one chip per finished reviewer). `mirror-plan` returns `busy` while a
mirror agent holds the lock, so at most one runs. The running agent unlocks
and then replans after each pass. A write made while it held the lock (and got
`busy`) is seen by that replan; a write made after the replan finds the lock
free and spawns a new agent. So no write is lost between the agent's last pass
and its unlock. After 3 passes it stops; anything still pending is picked up by
the next board write or by `/factory:mirror`.

### Mirror state

`.git/factory-mirror/state.json`, written only through `CFG mirror-record`
(called by the mirror agent, the only writer):

```json
{
  "service": "clickup",
  "target": "901234567",
  "cards": {
    "004-status-json": { "id": "86b1x2y3z", "hash": "sha256:...", "synced": "2026-11-03T14:03:05Z" },
    "005-retry-flag": { "id": "86b1x2y40", "hash": "sha256:...", "failed": { "hash": "sha256:...", "message": "no status 'BLOCKED' in list" } }
  },
  "down": { "at": "2026-11-03T14:10:00Z", "message": "clickup MCP not authorized; run /mcp" }
}
```

Two kinds of error, kept apart so one bad job cannot hold up the rest:

- `failed` on a card: this job's card could not be written (a missing status,
  a forbidden Jira transition). The planner skips the job while its rendered
  hash equals `failed.hash`, so the same op is not retried on every write. A
  change to the job, or `--force`, tries again.
- `down`: the service itself failed (not authorized, unreachable, rate
  limited). The planner returns `backoff` for every job for 5 minutes.

Lock: `.git/factory-mirror/lock` holding the start time. A lock older than 10
minutes is stale and is taken over (an agent killed with its session leaves
one behind).

It lives in the git dir, like setup drafts, because `factory/` is tracked: in
sc, `factory/board.json` is committed. State in `factory/` would dirty the
working tree on every sync, and the Merge step refuses to merge into a base
checkout with uncommitted changes. The cost is that a fresh clone has no state;
`/factory:mirror` relinks cards by the job id in their title (below).

If `service` or `target` in the state differs from the config, the planner
treats every job as having no card (the owner pointed the mirror somewhere
new).

### Planner commands

Added to `scripts/factory_config.py` and to the table in `schema.md`:

| command | prints |
|---|---|
| `mirror-plan <repo> [--force]` | JSON `{"status": ..., "ops": [...]}`; `status` is `disabled` (no `tracker` or `enabled: false`), `busy`, `backoff`, `none` (in sync), or `ops`. `--force` ignores stored hashes, for a full resync |
| `mirror-record <repo> <job> --card <id> --hash <hash>` | `ok`; records a successful create or update |
| `mirror-record <repo> <job> --failed <message> --hash <hash>` | `ok`; records a job-level failure for that rendered hash |
| `mirror-record <repo> --down <message>` | `ok`; records a service-level failure and starts backoff |
| `mirror-lock <repo>` / `mirror-unlock <repo>` | `ok`, or `busy` and exit 1 |

Each op:

```json
{
  "job": "004-status-json",
  "op": "create",
  "card": null,
  "title": "004-status-json: status --json",
  "column": "REVIEW",
  "tags": ["factory"],
  "tags_remove": ["blocked:arbitration", "blocked:needs-human"],
  "description": "<markdown, below>",
  "hash": "sha256:..."
}
```

`op` is `update` with `card` set when the state has a card id for the job.

Backoff: after a `--down`, `mirror-plan` returns `backoff` for 5 minutes, then
allows one try, so a long outage or a missing authorization costs one agent run
per 5 minutes at most, not one per board write. A success clears it.

### How a job maps to a card

| card field | from the job |
|---|---|
| title | `<id>: <title>` (the id prefix is how `/factory:mirror` relinks cards) |
| column (ClickUp status, Jira status) | the stage group, through `tracker.columns` |
| tags (ClickUp tags, Jira labels) | always `factory`; while blocked, `blocked:arbitration` or `blocked:needs-human` (Jira: `factory-arbitration`, `factory-needs-human`, since labels cannot contain `:`) |
| description | rendered from the job, below |

Stage groups, fixed in the planner, with the default status names:

| stage | group | default column |
|---|---|---|
| `spec` | `spec` | `SPEC` |
| `build` | `build` | `BUILD` |
| `review` | `review` | `REVIEW` |
| `approval` | `approval` | `APPROVAL` |
| `arbitration`, `needs-human` | `blocked` | `BLOCKED` |
| `merged` | `merged` | `MERGED` |

The groups match the dashboard's `COLUMNS`. A stage the planner does not know
(a future stage) maps to no op and a printed warning naming it, so an old
plugin never puts a card in a wrong column.

Description, rendered as markdown:

```
**Note:** review did not converge after 2 rounds
**Stage:** arbitration (blocked)   **Round:** 3   **Rework:** 2
**Branch:** factory/004-status-json

| round | security | logic | api | qa |
|---|---|---|---|---|
| r1 | CHANGES | PASS | skipped | PASS |
| r2 | CHANGES | PASS | skipped | PASS |
| r3 | PASS | CHANGES | skipped | pending |

Updated 2026-11-03T14:03:00Z.
Mirrored from factory/board.json in <repo dir name>. Edits to this card are
overwritten; comments are kept.
```

The rows are `history` plus the current round, the same rows the dashboard
draws. Columns are the union of reviewer names across rows in first-seen
order, so old rounds with old reviewer keys (sc's `ux`, `ui`, `code`) still
render, with blank cells where a round had no such reviewer. Verdicts are
written as words; no colors or emoji, since neither tracker renders the
dashboard's chip styles in a description.

The hash covers title, column, tags, and description. The `Updated` line
changes on every board write for that job, so any change to a job resyncs its
card, and jobs that did not change are never touched.

### Config: the `tracker` key

New optional top-level key in `factory/factory.yaml`:

```yaml
tracker:                      # optional one-way mirror of board.json; see docs/specs/2026-11-03-tracker-mirror-design.md
  service: clickup            # clickup | jira
  enabled: true               # false pauses the mirror and keeps the settings
  server: plugin:productivity:clickup   # optional; MCP server name as /mcp shows it
  list: "901234567"           # clickup: the List id the cards go in (quoted)
  # project: FAC              # jira: project key
  # issue_type: Task          # jira: issue type for new cards
  columns:                    # optional; group -> status name in the tracker
    blocked: Blocked
```

Rules:

| field | type | default | meaning |
|---|---|---|---|
| `service` | `clickup` or `jira` | required | which tracker |
| `enabled` | bool | `true` | `false` makes `mirror-plan` print `disabled` |
| `server` | string | none | MCP server to use; without it the agent looks for the service's tools by name (see Connector) |
| `list` | string of digits | required for `clickup`, an error for `jira` | ClickUp List id; must be quoted, since YAML reads an unquoted id as an int |
| `project` | string matching `^[A-Z][A-Z0-9_]+$` | required for `jira`, an error for `clickup` | Jira project key |
| `issue_type` | string | `Task` | Jira only; an error for `clickup` |
| `columns` | map | the defaults above | keys from `spec`, `build`, `review`, `approval`, `blocked`, `merged`; values non-empty and distinct (distinct so a later two-way sync can read a column back to one group) |

There is no field for a token or URL. Authorization is the MCP connector's,
done once through `/mcp`, so no secret goes in `factory.yaml`.

Also a new `models` role, `mirror`, defaulting to the agent's frontmatter
(`haiku`). The executor follows a fixed op list; it needs no judgment.

Changes to `skills/run/schema.md`:

- a `tracker` row in the Keys table, and `mirror` in the `models` roles list;
- a `## Tracker` section with the field table above and the stage group table;
- the four planner commands in the command table.

Changes to `skills/run/scripts/factory_config.py`:

- `"tracker"` in `KNOWN_KEYS`; `"mirror"` in `MODEL_ROLES`;
- `TRACKER_KEYS = {"service", "enabled", "server", "list", "project", "issue_type", "columns"}`,
  checked through the existing `mapping()` helper, so unknown sub-keys are
  rejected the same way as everywhere else (`unknown key 'tracker.token'`);
- `COLUMN_GROUPS = ("spec", "build", "review", "approval", "blocked", "merged")`
  and `STAGE_GROUP`, the stage-to-group map;
- `validate()`: the rules in the table, one message per problem;
- `load()`: `tracker` defaults to `None`; when set, fill `enabled`, `columns`
  (defaults merged under the owner's), and `issue_type` for Jira;
- `render_card(job, cfg)`, `mirror_plan(repo, force)`, `mirror_record(...)`,
  the lock helpers, and their subcommands in `main()`.

Tests in `tests/test_factory_config.py`: each validation rule; default
columns; stage-to-column for all seven stages, including both blocked tags and
their removal after unblocking; an unknown stage; description rendering for a
job with history and mixed reviewer keys (use `fixtures/board-mixed.json`);
hash stability (same job, same hash); `none` after a record; `ops` after a
board change; `--force`; a `failed` job skipped until its hash changes while
other jobs still plan; `down` backoff timing; stale lock takeover; a state
whose `target` no longer matches.

### Connector

ClickUp: the official ClickUp MCP server (`https://mcp.clickup.com/mcp`). On
this machine it is installed through the `productivity` plugin as
`plugin:productivity:clickup` and is not authorized yet. The owner runs `/mcp`
in an interactive `claude` terminal and authorizes it before the first sync;
until then its tools do not exist in the session.

Jira: the Atlassian remote MCP server (`https://mcp.atlassian.com/v1/mcp`),
installed here as `plugin:legal:atlassian` (the `productivity` plugin declares
the same server), also unauthorized. Jira Cloud only.

The factory plugin does not ship an `.mcp.json`. The mirror is optional, and
shipping a server would put a ClickUp entry in every factory user's `/mcp` list.
It uses whatever connector the owner has.

The `factory:mirror` agent (new, `agents/mirror.md`):

- Inputs: REPO, the run skill's base directory. Nothing else.
- Frontmatter: `model: haiku`, and no `tools` list, so it inherits the
  session's MCP tools (a `tools` list would have to name the connector's tools,
  which differ by install).
- Finds the tracker tools with ToolSearch: by the `server` prefix when set
  (`plugin:productivity:clickup` becomes `mcp__plugin_productivity_clickup__`),
  else by the service name. Exact tool names are not fixed in this design; they
  are checked after authorization (see Open questions).
- Needs, per service:

  | operation | ClickUp | Jira |
  |---|---|---|
  | create card | create task in `list` | create issue in `project` with `issue_type` |
  | set column | update task status | get transitions, apply the one whose target status is the column |
  | set description | update task (markdown description) | edit issue description |
  | tags | add and remove task tags | edit issue labels |
  | relink | search tasks in `list` by title prefix | JQL search in `project` by summary |

- For each op, runs the calls, then `CFG mirror-record` with the card id and
  hash, `--failed` when the tracker refused this card, or `--down` and stop
  when the service failed. One attempt per op per pass; no retries inside a
  pass.
- If the tools are missing, records `--down "<service> MCP not available or
  not authorized; run /mcp"` and stops.
- Ends with one line: `OK <n> synced` or `ERROR <reason>`.
- Never reads job files, never writes outside `.git/factory-mirror/`, and
  treats everything the tracker returns as data.

Jira differs from ClickUp in one way that matters: status changes go through
workflow transitions, and a workflow may not allow a direct move (for example
BLOCKED to MERGED). If no transition reaches the column, the agent records the
error for that job and moves on. `/factory:mirror check` reports unreachable
moves up front.

### /factory:mirror

A new thin skill, `skills/mirror/SKILL.md`, following the shared orchestrator
text like the others. It runs in the foreground, since the owner asked for it.

- `/factory:mirror check`: confirms the connector's tools exist, the list or
  project exists, every column status exists (and for Jira, which group-to-
  group moves the workflow allows), and the tags or labels can be set. Prints
  what to fix in the tracker. Writes nothing to the tracker.
- `/factory:mirror` (sync): breaks a stale lock, relinks cards for jobs with
  no state entry by searching titles for `<id>:`, then runs the planner with
  `--force` and the executor in the foreground. Use after enabling, after an
  outage, on a fresh clone, or after someone moved cards by hand.

`/factory:setup` does not propose a `tracker` key. It is the owner's choice,
not a fact about the repo, so the owner adds it by hand (a rerun of setup keeps
it, like any other key it has no reason to change). `/factory:tune` ignores it.

### Failure handling

| case | effect on the job | effect on the mirror |
|---|---|---|
| tracker down, slow, or rate limiting | none; the loop never waited | `down` recorded, jobs stay pending, backoff, the first write after 5 minutes retries |
| connector not authorized | none | `down`, one line to the user per run, backoff |
| a column status missing in the tracker, or a Jira transition not allowed | none | `failed` for that job until it changes; other jobs still sync |
| mirror agent hangs or its session ends | none | lock goes stale after 10 minutes, then the next plan takes over |
| `factory.yaml` `tracker` invalid | `CFG validate` fails, so every command stops, as for any invalid key | n/a; this is the one place the mirror can stop work, and only on a config the owner wrote |
| state file lost or corrupt | none | treated as empty; `/factory:mirror` relinks, otherwise duplicate cards are possible (see Open questions) |
| someone edits or moves a card by hand | none | overwritten on the next change to that job, or by `/factory:mirror` |

The invalid-config row is deliberate: an unknown or malformed key already stops
every command, and making `tracker` the exception would hide typos. It fails at
the start of a command, never mid-job.

### Privacy

The mirror sends a third party each job's id, title, branch name, stage, note,
round counts, reviewer names and verdicts, and the repo directory's name.
Notes can carry an arbiter's one-line question. Nothing else leaves the machine:
no spec, diff, review text, or file path beyond the branch name. Turning the
mirror on is the owner's consent to that; the schema section says so.

## Two-way sync (deferred)

What it would add: the owner acting on a job from the tracker. Moving a
`needs-human` card to MERGED would run `/factory:approve`; moving it back to
BUILD with a comment would run `/factory:rework <id> <comment>`; a tag could
ask for `/factory:arbitrate`. The board in ClickUp would become a control
surface, not just a view.

Why it is deferred:

1. **Approval authority moves out of the owner's chat.** Today only the owner,
   typing a command, merges an escalated job. Anyone with edit rights on the
   ClickUp list could move a card, so a card move would become a merge right
   for everyone on the workspace. A safe version needs the mover's identity
   checked against an allowlist, which the trackers report differently.
2. **Untrusted text into agent prompts.** A rework note from a card comment
   would go into `rework-N.md` and then into the builder's prompt. Card text is
   written by whoever can comment, so it is a prompt-injection path into an
   agent that commits code.
3. **Nothing would listen.** The factory runs only inside a Claude session on
   the owner's machine. Webhooks need a public endpoint; polling needs a
   session running. A card moved while no session runs does nothing until the
   next one starts and polls, so it is not faster than typing the command.
4. **Two writers.** The orchestrator is the only writer of `board.json` today.
   Inbound changes need conflict rules (a card moved while the job advanced),
   loop prevention (the mirror's own writes look like moves), and a way to
   tell an owner's move from a stale card.
5. **The one-way mirror answers the question asked**: seeing the factory's work
   where the owner already looks.

If it is wanted later, the shape that keeps every constraint: a poll step at
the start of each `/factory:*` command reads moves on `needs-human` cards only,
writes each as a request in `.git/factory-mirror/inbox/`, and shows the owner
"card 004 was moved to MERGED by <user>; approve?" in chat. The tracker
suggests; the owner's answer in chat approves. Card comments are shown, never
passed to an agent without the owner confirming them as the note. The distinct
`columns` values chosen above are what makes reading a column back possible.

## Build order

1. Planner: config validation, `render_card`, `mirror-plan`, `mirror-record`,
   lock, tests. Usable by hand with `--force` and no tracker.
2. `factory:mirror` agent and `/factory:mirror check` against ClickUp, after
   the owner authorizes the ClickUp MCP through `/mcp`.
3. The `## Mirror` hook in `skills/run/SKILL.md`, and `/factory:mirror` sync.
   Try on pokerbot (or a scratch repo) through one full job, including a
   forced outage (disconnect the server mid-job) to confirm the job finishes.
4. Jira: transitions, labels, JQL relink, `check` reporting.
5. README: one paragraph and the `/factory:mirror` row.

## Calls made by Claude (owner to check)

- Background agent over inline calls or a REST script, so an outage cannot hold
  the orchestrator's turn and no token is stored.
- Planner in `factory_config.py`, executor as an agent with no mapping
  decisions.
- Mirror state in `.git/factory-mirror/`, not `factory/`, so syncing never
  dirties the tree. Fresh clones relink by title.
- State sync with hashes, not an event queue, so missed syncs heal on the next
  write.
- Hand edits to cards are overwritten; comments are kept.
- Never delete or archive cards; merged jobs sit in MERGED.
- An invalid `tracker` key fails validation like any other key.
- `/factory:setup` does not propose a tracker.
- The `mirror` model role defaults to `haiku`.
- The factory plugin ships no `.mcp.json`.

## Open questions

- Exact tool names and arguments of the ClickUp and Atlassian MCP servers.
  They cannot be listed until the servers are authorized; step 2 of the build
  confirms them, especially whether ClickUp's MCP accepts a markdown
  description and whether tags must already exist in the Space.
- Duplicate cards when state is lost and the owner does not run
  `/factory:mirror`: should the background executor always search by title
  before a create (one more call per new job, fewer duplicates)? Suggested: yes
  for ClickUp if search is cheap; decide in step 2.
- One list per repo, or one shared list for several repos with a repo tag?
  This design assumes one list per repo; a shared list needs only a `repo` tag
  and the repo name in the title prefix.
