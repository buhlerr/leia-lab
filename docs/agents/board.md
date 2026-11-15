# Admin board (great_cto `/board`)

Only the **board** from the great_cto plugin is adopted here: a local admin panel at `http://localhost:3141` that reads this repo's Beads. Nothing else from great_cto is used: no agents, hooks, pipeline, skills, or `.great_cto/` workflow config. Issues stay in Beads (see `issue-tracker.md`).

## What it shows for this repo

- **Tasks**: the board runs `bd list --json --all --include-gates` inside the project directory and renders the result as a Kanban. It only sees what `bd` sees.
- **Last activity**: the mtime of `.beads/interactions.jsonl`, used to order the project switcher.
- The cost, pipeline, inbox and memory views read great_cto state (`~/.great_cto/verdicts/`, `.great_cto/`, `docs/plans/`). This repo has none of that, so those views stay empty.

## What it needs

1. **`bd` on `PATH`** (or `GREAT_CTO_BD_BIN` pointing at it).
2. **An initialized Beads database in the checkout.** `.beads/embeddeddolt/` is git-ignored, so a fresh clone or worktree has the `.beads/` config but no database. The board then answers `503 {"state":"unreadable"}` for that project. Initialize or sync the database first (see `bd prime` and `AGENTS.md`).
3. **The project in the board's registry**, `~/.great_cto/projects.json` (outside this repo):

   ```json
   { "projects": [ { "slug": "leia-lab", "archetype": "library", "description": "", "path": "<absolute path to this checkout>" } ] }
   ```

   An entry plus a `.beads/` directory is enough for the board to list the project. The automatic routes (current directory, directory scan, `POST /api/projects/register`) all require `.great_cto/PROJECT.md`, and the register route creates it. We do not commit that file, so register by hand as above.
4. **A built CLI for `/board`.** `/board` starts `great-cto board`, which needs the plugin's `packages/cli/dist/main.js` or `great-cto` on `PATH`. The marketplace copy ships neither (`npm install -g great-cto` is the documented fix, and it is a global install). The board itself has no npm dependencies, so this works without installing anything:

   ```bash
   node ~/.claude/plugins/cache/great-cto/great_cto/<version>/packages/board/server.mjs --port 3141 --no-open
   ```

   It binds to `127.0.0.1` only and has no login. It keeps its state in `~/.great_cto/`.

## Verified

Board 4.0.0 started from the plugin copy on a spare port, with state, registry and discovery pointed at a temporary directory:

- With only `.beads/` in the project, `/api/projects` listed it.
- `/api/tasks?project=<slug>` returned `503 unreadable` for a worktree without the Beads database.
- The same call for a checkout with the database returned `200 []`, resolved by slug (`X-Project-Resolved: slug`, no `X-Project-Fallback`), matching `bd list` there: no issues yet.
