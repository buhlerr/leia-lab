# Issue tracker: Beads

Issues and specs for this repo live in Beads. Use the `bd` CLI for all operations (see `AGENTS.md` and `bd prime` for the full workflow and sync rules).

## Conventions

- **Create an issue**: `bd create "<title>" -t <bug|feature|task> -l "<label>,<label>" --body-file - <<'EOF' ... EOF`. Use `-d "..."` for a one-line description. The category role maps to the type too: `bug` → `-t bug`, `enhancement` → `-t feature`.
- **Read an issue**: `bd show <id> --json --include-comments` (or `bd show <id>` plus `bd comments <id>` for human-readable output).
- **List issues**: `bd list --status open --json` with `--label <name>` (all must match) or `--label-any <a>,<b>`. Use the comma form for several statuses: `--status open,in_progress`.
- **List children**: `bd list --parent <id> --status open,in_progress --json`. Check each child's blockers with `bd dep list <child-id>`.
- **Comment on an issue**: `bd comments add <id> "..."` (or `-f <file>` for long text).
- **Apply / remove labels**: `bd label add <id> <name>` or `bd label remove <id> <name>`. Several labels go comma-separated.
- **Close**: `bd close <id> --reason "..."`.

Issue IDs are Beads IDs (`<prefix>-<hash>`, e.g. `bd-a3f8`), not `#numbers`.

## Pull requests as a triage surface

**PRs as a request surface: no.** _(PRs live on GitHub and are not mirrored into Beads; set to `yes` only if this repo starts treating external PRs as feature requests, and use `gh pr` for them.)_

## When a skill says "publish to the issue tracker"

Create a Beads issue with `bd create`.

## When a skill says "fetch the issue"

Run the **Read an issue** command above.

## Wayfinding operations

Used by `/wayfinder`; `/to-tickets` uses **Blocking** too. The **map** is a single epic with **child** issues as tickets.

- **Map**: an epic labelled `wayfinder:map`, holding the Destination / Notes / Decisions so far / Added so far / Not yet specified / Out of scope body. `bd create "<title>" -t epic -l wayfinder:map --body-file -`.
- **Child ticket**: `bd create "<question>" --parent <map-id> -l wayfinder:<type>`, where `<type>` is `research`/`prototype`/`grilling`/`task`. Once claimed, the ticket is assigned to the driving dev.
- **Blocking**: `bd dep add <blocked-id> <blocker-id>` (same as `--blocked-by`). A ticket is unblocked when every blocker is closed.
- **Frontier query**: `bd ready --parent <map-id> --json` (open, no active blockers, not in progress); drop any with an assignee; first in creation order wins.
- **Claim**: `bd update <id> --claim` (atomic: sets you as assignee and status `in_progress`), the session's first write.
- **Resolve**: `bd comments add <id> "<answer>"`, then `bd close <id> --reason "<gist>"`, then append a context pointer (gist + id) to the map's Decisions-so-far with `bd update <map-id> --body-file -`.
