# NXO Swiss Knife — Changelog

Chronological log of all modifications to the project. **Newest first.**

> Moved out of `PROJECT.md` §4 on 2026-11-23 — `PROJECT.md` now only points
> here. Entries are added per the
> [maintenance rules](PROJECT.md#8-maintenance-rules): what changed
> (bug fix / feature / refactor), which files were touched, and how it was
> verified.

---

## 2026-11-25

**QA folder documented in `PROJECT.md` (all files created during the testing
phase go to `QA/`):**
- Added new section **§9 "QA folder — files created during the testing
  phase"** in `PROJECT.md`: `C:\Users\hedhl\source\repos\NXO_Swiss_Knife\QA`
  is the designated (disposable) location for every file created during
  testing — test scripts, run logs, generated artifacts (exports, DB dumps,
  screenshots), one-off API probes against `http://127.0.0.1:5000`. Test
  files must never be created at the repo root or inside `app/`,
  `templates/`, `static/` or `files/` (stray root files are picked up by the
  next Vector DB re-index). Includes a table of the typical per-test-round
  scripts (`qa_api_smoke.py`, `qa_parser_check.py`, `qa_db_inspect.py`,
  `qa_export_roundtrip.py`, `qa_server.ps1`, obscura flow check-list notes).
- Maintenance rule 7 reworded: functional UI verification stays **obscura
  (headless browser) only**, no permanent automated test suite, but **every
  file created during the testing process MUST be placed in `QA/`**; new
  rule 8: `QA/` contents are disposable and not part of the app.
- `QA/` added to the architecture/layout tree in §2; the 📋 Tests row in
  §5 updated accordingly.
- Files touched: `PROJECT.md`, `CHANGELOG.md`.
- Verified: `QA/` directory exists (currently empty); the updated tree,
  rule text and §9 render correctly in `PROJECT.md`.

**`.gitignore`: ignore the disposable `QA/` folder:**
- Added `QA/` to `.gitignore` (new "# QA — disposable test artifacts" section)
  so testing scripts, logs and artifacts are never committed; the §2 tree
  comment for `.gitignore` updated accordingly.
- Files touched: `.gitignore`, `PROJECT.md`, `CHANGELOG.md`.
- Verified: `.gitignore` now contains `QA/` after the Python/.venv sections.

---

## 2026-11-24

**Firewall wizard step 3: single x-text action label (fixes the empty "Import configuration" button after a failed no-file import):**
- Bug: after the step-3 import failed because no file was chosen (the firewall
  itself was already created), the action button's "Import configuration"
  label was rendered hidden — the button showed as an empty green box.
  Root cause: the label was three per-state `x-show` spans; Alpine's delayed
  show/hide scheduling (rAF + queueMicrotask/Promise chains) can let a hide
  scheduled during an earlier falsy state fire *after* the later show, leaving
  the label hidden in the final state.
- Fix: the three `x-show` spans in `templates/_firewall_wizard.html` are
  replaced by one deterministic `x-text` label:
  `creating ? 'Working...' : (created ? 'Import configuration' : 'Create firewall')`
  (x-text updates synchronously in the reactive effect — no show/hide race).
- Behavior kept: while an import retry is pending the **"Done — go to
  dashboard"** button stays hidden (`x-show="!importError"`); only **Back** +
  **Import configuration** apply, and a retry re-imports the already-created
  firewall, never re-creates it.
- Files touched: `templates/_firewall_wizard.html`.
- Verified: headless browser — no-file failure shows "Import configuration"
  (labeled) and no "Done — go to dashboard"; a retry without a file keeps the
  same firewall id (no re-creation); the skip-import path still shows
  "Done — go to dashboard".

**Export: whole-database delivery to the destination verified (no code change):**
- Confirmed that `POST /api/export/file` and `POST /api/export/push` deliver
  **every active object of the selected types from every firewall in the
  database** to the destination firewall (not only its own imported
  configuration) — `_build_config()` applies no firewall filter; the
  "Object types to export" step is kept as is (per-type checkboxes, per-type
  Tagged only / All objects scope, Select all / Tagged only / Clear
  shortcuts).
- Verified: headless browser — export to PA-440 (0 objects of its own): the
  generated PAN-OS XML contained all 1199 FGT-600E objects (587 address,
  52 address group, 130 service, 11 service group, 374 security rule,
  45 interface); the push stream finished with "Pushed 1199 objects to
  PA-440".

**Housekeeping: removed session-leftover files from the repository root:**
- Deleted `bs_test.py`, `bs_test.txt`, `launcher_dev.py`, `probe_port.py`,
  `server_dev.bat`, `server_dev.log`, `server_err.log`, `server_out.log`,
  `vector_db.md` and the empty `tests/` directory — leftovers of earlier
  verification sessions that the next Vector DB re-index would have picked
  up.
- Re-ran the Vector DB index with `--prune` (4 stale chunks removed; the
  collection now holds 1142 chunks from 35 files).

**Object list: visual payload form + "Validate" button in the modify modal (Move to Trash removed):**
- `objects.html` edit modal now renders one visual field per payload key
  (`buildPayloadFields`): scalars → text/number input, booleans → checkbox,
  arrays of scalars → one item per line, objects/arrays of objects → JSON
  textarea. A "↻ Re-sync from Payload JSON" button rebuilds the fields from
  the (hand-edited) textarea so the two never drift apart. On save, the
  field values are overlaid on the parsed payload (`applyPayloadFields`; the
  fields win for the keys they cover; invalid number/JSON is rejected with a
  message).
- The modal's "Move to Trash" button is removed (row-level Delete stays),
  and "Stage Changes" is renamed **Validate**: it stages the update AND
  commits it straight away (`POST /api/objects/commit` with the single
  change), then refreshes the list. Other staged changes stay pending;
  if the commit fails the change remains staged for the toolbar Validate.
- `stageSave()`/`stageDelete()` replaced by `validateFromModal()` in
  `app.js` (objectTable); `modal.fields` added to the modal state.
- Files touched: `templates/objects.html`, `static/js/app.js`.
- Verified: headless browser — address (text fields), security rule
  (text + list fields, incl. multi-item list edit and revert), re-sync from a
  hand-edited payload (text/list/boolean/json kinds all rebuilt); each
  Validate committed exactly 1 change, the list reloaded with the new values,
  and a matching `update`/`payload` row appeared in the object history.

**Dashboard + firewall page: delete now removes the card in place (no manual refresh):**
- Root cause: the delete endpoints answer with a 302 redirect, but the old
  `fetch(..., {redirect: "manual"})` + `status >= 300` check never matched in
  the browser (the post-redirect status is unreliable — observed as `200` /
  `type:basic`, never an `opaqueredirect`/`3xx`), so the `location.reload()`
  branch never ran and the card stayed until a manual refresh.
- Fix: `dashboard().deleteEntity()` (shared by project + firewall delete) and
  `firewallDashboard().deleteEntity()` now POST with the default
  follow-redirect behavior, treat the final `response.ok` as success, and
  re-fetch the list(s) in place (`reloadAll()` / `reloadFirewalls()`) — the
  deleted card disappears immediately without a full page reload. Failures
  still surface the JSON error (or an HTTP-status message) via `alert`.
- Files touched: `static/js/app.js`.
- Verified: headless browser — deleting a project and a firewall from the
  dashboard and a firewall from `/firewalls` each removed the card from the
  DOM and the component state in place, with no page reload and no error.

**Firewall wizard: "Back" button after the "No configuration file chosen" error + import retry:**
- When step 3's import fails because no file was chosen (the firewall itself
  was already created), a **Back** button is now available: `back()` allows
  going back to step 2 in that case, and the step-3 action row (Back +
  button) is shown again (`x-show="!created || importError"`).
- `create()` now distinguishes first run vs. retry: if `this.created` already
  exists it only re-runs the import (never re-creates the firewall, which
  would hit the name constraint); the step-3 button reads **Import
  configuration** instead of "Create firewall" on retry.
- Files touched: `static/js/app.js` (firewallWizard),
  `templates/_firewall_wizard.html` (step-3 action row + label).
- Verified: headless browser — with no file, step 3 showed the error plus a
  working Back button; back to step 2, choosing a source (REST URL against a
  local file server), Next, then "Import configuration" re-ran the import on
  the already-created firewall: 1198 objects imported, no duplicate firewall
  created, no constraint error.

**Firewalls without an imported configuration can now be attached to projects:**
- `project_detail` no longer filters attachable firewalls on `has_config`, and
  `attach_project_firewall` no longer rejects them (the API
  `POST /api/projects` already allowed any firewall). The project wizard's
  `init()` no longer filters `attachable` on `has_config`.
- Copy updated: project page "Attach existing" + the wizard step 2 / step 3
  notes now say any firewall can be attached (import later); the attach
  dropdown and wizard checkboxes mark config-less firewalls
  ("no configuration yet" / "0 objects (no configuration yet)").
- Files touched: `app/views.py`, `templates/project.html`,
  `templates/_project_wizard.html`, `static/js/app.js` (projectWizard).
- Verified: headless browser — wizard step 2 listed all three firewalls
  (incl. the two without a configuration, marked "no configuration yet");
  the project page "Attach existing" dropdown listed them too; attaching a
  config-less firewall succeeded and moved it to the project (then removed it
  back to unassigned to restore state).

**Bug fix: null `fw.project` no longer throws on the dashboard/firewalls pages:**
- The per-card project link used `:href="`/projects/${fw.project.id}`"` and
  `x-text="fw.project.name"` behind `x-show="fw.project"`, but Alpine
  evaluates those bindings even on hidden elements — so every unassigned
  firewall (project = null) raised "Cannot read properties of null"
  expression errors on load. Short-circuited both bindings
  (`fw.project ? … : '#'` / `fw.project ? fw.project.name : ''`).
- Files touched: `templates/index.html`, `templates/firewalls.html`.
- Verified: headless browser console is clean on `/` and `/firewalls` with
  unassigned firewalls present (previously flooded with null errors).

**PROJECT.md: first-attempt background dev-server recipe documented (§3):**
- New "Running the dev server in the background (verification / LLM
  sessions)" section: exact `_run_server.bat` launcher + `Start-Process`
  launch + fast TCP port-probe + stop/cleanup commands, with the root
  causes of the naive `Start-Process -ArgumentList '-c', …` failure —
  (1) `Start-Process` does not quote array elements, so the inline script
  is split into separate argv items and python dies with a startup
  `SyntaxError`; (2) relative `-RedirectStandard*` paths resolve against
  the caller's cwd, not `-WorkingDirectory`, so the log (and the error)
  land elsewhere and the failure looks silent.
- §7 Windows-backgrounding note: `-RedirectStandard*` paths must be
  absolute (same pitfall).
- Files touched: `PROJECT.md`, `CHANGELOG.md`.
- Verified: the recipe itself was used successfully during today's
  verification session (bat launcher started the app on the first try;
  the direct `-ArgumentList -c` attempt failed exactly as documented).

**Dashboard: removed the "Objects" link from the firewall cards:**
- The per-card action row of the dashboard firewall section now only shows
  Import / Edit / Delete (plus the "No configuration imported" note for
  firewalls without a configuration). The object count remains displayed in
  the card body, and objects stay reachable from the project page,
  the project cards ("View Objects") and the `/firewalls` page.
- Files touched: `templates/index.html`.
- Verified: headless browser on `/` — 0 remaining "Objects" links, card
  rows show Management IP / object count / Import / Edit / Delete only.

**Object list: the Actions column is no longer cropped:**
- `objects.html`: the table now sits in a horizontal scroll container
  (`overflow-x-auto`, table `min-w-full`) inside the card. With the wide
  type-specific column sets (e.g. security rules: 12 columns ≈ 2440 px),
  the card's `overflow-hidden` used to clip the rightmost Actions column
  out of reach; the card now scrolls horizontally and the column (Modify /
  Delete / Cancel + staged badges) always renders in full.
- Files touched: `templates/objects.html`.
- Verified: headless browser on a 12-column rule list — the Actions header
  and cell align exactly with the scroll container's right edge when
  scrolled (no crop); narrow lists (zone) and empty lists render unchanged.

**Project page: firewalls + "Attach existing" merged in one card; objects by type reworked:**
- The 2/3 + 1/3 grid is now a single-column layout. The **Firewalls** card
  contains the firewall table (Import / Edit / View Objects / Remove)
  **and** the **Attach existing** form at its bottom (same card, as before
  only for imported firewalls, with the "attaching moves the firewall"
  note); the Export button stays below the card.
- The "Objects by type, per firewall" matrix (one row per firewall × one
  column per type, horizontally scrollable and cramped at card width) was
  replaced by a block **per firewall**: name + vendor/model, a clickable
  "Total" link, and a responsive grid of type chips (2/4/7 columns) where
  each chip shows the type name and its count (clickable → filtered object
  list; zero counts muted). A "Total per type" footer keeps the per-type
  column totals + the all-objects link — nothing is cropped anymore.
- Files touched: `templates/project.html`.
- Verified: headless browser + raw HTML on `/projects/1` — chip links point
  to `/objects?project_id=1&firewall_id=1&object_type=…`; per-firewall
  totals match the stat card (1843 + 4085 = 5928); attach section renders
  the correct empty state when every configured firewall is already
  attached; table + attach form render in the same card.

**Vector DB — Tree-sitter extended to Python + TypeScript; corpus rebuilt uniformly:**
- `Vector_DB` now chunks Python and TypeScript with Tree-sitter too
  (`tree-sitter-python` 0.25.0, `tree-sitter-typescript` 0.23.2, pinned in
  `Vector_DB/requirements.txt`): Python top-level `def`/`class` blocks with
  decorators attached (the grammar's `decorated_definition` node), labelled
  by the signature line — same style as the old regex path, so
  `--where "section=def ..."` filters keep matching; TypeScript reuses the
  JS segmenter (functions/classes/declarations, plus interface/type/enum).
- Fixed a latent `--rebuild` bug in `Vector_DB/index_db.py`:
  `collection.delete(where={})` is rejected by ChromaDB 1.5.9 ("where needs
  an operator"); the wipe now deletes by id in batches of 5000.
- Full corpus rebuild (`index_db.py --rebuild --ext .py,.js,.html,.css,.conf,.txt,.xml`):
  35 files re-indexed with the new chunker, 0 failed, 1139 chunks — the whole
  store now uses uniform AST chunking. The two `files/*.xml` samples are
  re-included explicitly via `--ext` (`.xml` is not a default extension).
- Incident note: an earlier *foreground* rebuild was killed mid-write and
  left the HNSW binary index corrupt — every subsequent ChromaDB open
  crashed with an access violation in the Rust core (`chromadb/api/rust.py`).
  Recovery: removed the corrupt HNSW segment dir (backed up first); the Rust
  core rebuilt it from the SQLite embeddings — no data lost. Long re-indexes
  should run backgrounded with the `Start-Process` pattern (see §7).
- Files touched: `PROJECT.md`, `CHANGELOG.md`, `Vector_DB/app/rag/chunker.py`,
  `Vector_DB/index_db.py`, `Vector_DB/requirements.txt`, `Vector_DB/README.md`,
  and the ChromaDB store in `Vector_DB/.vectordb`.
- Verified: `app/api/routes.py` chunks carry `def ...()` AST labels (incl.
  decorated route handlers); "How is modification history written when an
  object changes?" → top hits `def update_object(object_id):` (0.601) +
  `class ConfigObject(db.Model):` (0.593) with the full `log_change` flow;
  export-button and exportWizard queries still return the expected chunks.

**Vector DB — `.html`/`.js`/`.css` added to the index (Tree-sitter AST chunking) + skip rules:**
- The sibling **Vector_DB** store now indexes this repo's frontend:
  `templates/*.html` (14 files, 25 chunks) and `static/js/app.js`
  (13 chunks) were added (1102 → 1139 chunks, 21 → 35 files, after
  pruning 1 stale chunk of the deleted `_tmp_inspect.py`); the default
  extensions in `Vector_DB/app/rag/config.py` are now
  `{".py", ".js", ".html", ".css", ".conf", ".txt"}`.
- New file types are chunked with **Tree-sitter AST** segmentation
  (`tree-sitter` 0.27 + javascript/html/css grammars, pinned in
  `Vector_DB/requirements.txt`): JS top-level functions/classes/declarations
  (label = signature, e.g. `function exportWizard(stats, projectId) {`),
  HTML body-level elements (label `tag#id` / `tag.class`; oversized elements
  split one level deeper), CSS rule sets + at-rules (label = selector).
  Node text is sliced on the file's UTF-8 **bytes** (Tree-sitter offsets are
  byte offsets, not character offsets) — multi-byte content can no longer
  shift chunk boundaries or corrupt section labels.
- Skip rules extended (shared `is_skipped()` in `Vector_DB/app/rag/config.py`,
  used by the CLI and `/api/rag/reindex`): `node_modules/`, `dist/`,
  `build/` directories; minified `*.min.js` / `*.min.css`; source maps
  `*.map`; lockfiles `package-lock.json`, `yarn.lock`, `pnpm-lock.yaml`.
- Files touched: `PROJECT.md`, `CHANGELOG.md`, `Vector_DB/app/rag/chunker.py`,
  `Vector_DB/app/rag/config.py`, `Vector_DB/index_db.py`,
  `Vector_DB/app/api/rag.py`, `Vector_DB/README.md`,
  `Vector_DB/requirements.txt`, and the ChromaDB store in
  `Vector_DB/.vectordb`.
- Verified: chunker test on `app.js` / templates (correct AST section labels),
  `index_db.py --prune` run (15 indexed, 18 dedup-skipped, 0 failed), and
  `rag_query.py` — "How does the exportWizard Alpine component work?" now
  returns the `app.js [function exportWizard(stats, projectId) {]` chunk as
  top hit (cosine 0.617); "Where are the Export buttons placed in the UI?"
  now surfaces the frontend component chunks instead of backend only.

**Vector DB / docs — `.md` files removed from the vector store and excluded from indexing:**
- The sibling **Vector_DB** store no longer indexes this repo's markdown
  files: the 31 existing chunks of `PROJECT.md` (14), `CHANGELOG.md` (16)
  and `vector_db.md` (1) were deleted from the `swissknife` collection
  (1133 → 1102 chunks, 24 → 21 files), and `DEFAULT_INDEX_EXTS` in
  `Vector_DB/app/rag/config.py` is now `{".py", ".conf", ".txt"}` so
  `python index_db.py` won't re-index the markdown files.
- Files touched: `PROJECT.md`, `CHANGELOG.md`, `Vector_DB/app/rag/config.py`,
  `Vector_DB/README.md`, and the ChromaDB store in `Vector_DB/.vectordb`.
- Verified: store inspection (per-file chunk counts of the `swissknife`
  collection) shows no `.md` entries, and `python index_db.py --dry-run`
  lists no `.md` files.

**Bug fix — checkbox clicks doing nothing (stale browser-cached app.js) + synchronous checkbox toggling:**
- **Root cause of "clicking a checkbox does not check/uncheck":** browsers
  cache `static/js/app.js` for Flask's default static max-age (12 h). After
  an app.js edit, a page refresh still loaded the **old** cached script
  while the (freshly rendered) template referenced the newer component
  functions — the checkbox handlers resolved to nothing and clicks were
  silently dead.
- **Fix 1 — cache-busting script tag.** `create_app()` now exposes a Jinja
  global `app_version` (= mtime of `static/js/app.js`); `base.html` loads
  the script as `app.js?v=<app_version>`, so every server restart after an
  app.js edit changes the URL and the browser fetches the new file.
- **Fix 2 — synchronous, bulletproof checkbox binding.** The objects-page
  row and header checkboxes now use `@change` (no `@click.prevent`): the
  native toggle updates the checkmark **immediately on click** in every
  browser (mouse and keyboard), and the Alpine state syncs from the `change`
  event (`:checked` re-applies the same value, no flicker). Pure-selection
  semantics unchanged — only the Include / Remove toolbar buttons touch the
  server.
- Files touched: `app/factory.py`, `templates/base.html`,
  `templates/objects.html`, `PROJECT.md`, `CHANGELOG.md`.
- Verified with obscura (headless browser): script tag renders
  `app.js?v=<mtime>` on every page; row checkbox DOM `checked` flips
  synchronously on real CDP clicks in both directions (check / uncheck);
  header select-all works with a real click (25 selected);
  full round-trip with real clicks — **Include in the export (25)** then
  **Remove from export (25)** → server back to 0 tagged.

**Bug fix / UX — objects page: selection-only checkboxes + "In export" tag column:**
- The row / header **checkboxes are selection-only again**: checking or
  unchecking a row sends nothing to the server (the previous revision
  toggled the `export_included` tag on every click, which was not the
  intended behavior). The selection is applied **only** by the toolbar
  buttons **Include in the export (N)** / **Remove from export (N)** →
  `POST /api/objects/export-include` (`include: true/false`); N counts the
  selected rows that the button will actually change (buttons disable at 0).
- The selection **mirrors the persisted tag state**: tagged rows are
  preselected on load and the selection is resynced after every button
  action, so the checkboxes always match what is really included in the
  export (the original checkbox/badge mismatch stays fixed).
- The **"in export" tag now lives in its own column** ("In export", right
  after the checkboxes): badge per tagged row, "—" otherwise.
- Files touched: `templates/objects.html`, `static/js/app.js`
  (`objectTable`), `PROJECT.md`, `CHANGELOG.md`.
- Verified with obscura (headless browser) against the Demo-Project
  (FGT-600E addresses): unchecking a tagged row left the server untouched
  (confirmed via `GET /api/objects`); **Remove from export (24)** untagged
  exactly the 24 selected rows (the deselected one stayed tagged);
  checking 2 untagged rows + **Include in the export (2)** tagged exactly
  those 2; header select-all → Include (22) → all 25 tagged →
  **Remove from export (25)** → 0 tagged (server confirmed at each step);
  tag column shows the badge / "—" per row state.

**Feature — Export button on the project page, removable "Include in the export" tag, "Tagged only" shortcut in the export wizard:**
- **Export button on the project page.** `/projects/<id>`: a new **Export**
  button right below the Firewalls card (left column) →
  `/projects/<id>/export`.
- **"Include in the export" is now removable + checkbox fix** (objects page,
  `/objects?project_id=…&firewall_id=…&object_type=…`):
  - Row checkboxes now mirror the persisted `export_included` state. Before:
    the checkbox was a transient selection cleared after tagging while the
    "in export" badge stayed — unchecking a tagged row did nothing to the tag.
  - Checking an untagged row, or unchecking a tagged one, now toggles the tag
    **immediately** (`POST /api/objects/export-include` with
    `include: true/false`; optimistic UI update, table reload on error).
  - The page header checkbox flips every object of the current page in one
    batch call (include when not all are tagged, remove when all are).
  - Toolbar: **Include in the export (N)** tags every untagged row of the
    page; new **Remove from export (N)** button untags every tagged row
    (counts computed from the current page, buttons disable when N = 0).
- **Export wizard step 2: "Tagged only" shortcut.** New button between
  **Select all** and **Clear** (`selectTaggedOnly()`): selects every object
  type filter in the **Tagged only** scope, so the export carries only the
  objects tagged "Include in the export" (per type).
- Files touched: `templates/project.html`, `templates/objects.html`,
  `templates/export.html`, `static/js/app.js` (`objectTable`,
  `exportWizard`), `PROJECT.md`, `CHANGELOG.md`.
- Verified with obscura (headless browser) against the Demo-Project
  (FGT-600E / PA-3410): Export button placement on the project page (after
  the Firewalls card, target `/projects/1/export`); row checkbox ↔ "in
  export" badge ↔ API state consistency (25 tagged addresses on page 1, 0
  mismatches); per-row uncheck → "1 object removed from the export" +
  persistence confirmed via `GET /api/objects`; per-row re-check → tagged
  again; toolbar Remove (25) / header checkbox batch include + remove;
  disabled states; "Tagged only" selects all 9 type filters in tagged scope,
  summary reports the per-type counts, and file generation honored it (25
  objects in the generated Fortinet `.txt`).

**Documentation — mandatory Vector DB query before every file read + testing rule (obscura only):**
- `PROJECT.md`: querying the **Vector_DB** store is now **MANDATORY before every
  direct file read** of this repository — direct file reading is not allowed
  until the query has returned no useful information (0 relevant chunks, or
  chunks that do not answer the question). The former exception ("or the exact
  current content is required, e.g. to make a precise edit") is removed.
  Applied in the intro block, §7 (Priority paragraph + workflow step 2) and
  §8 maintenance rule 1.
- `PROJECT.md` §8: new maintenance rule 7 — **Testing: do NOT create test
  scripts** (no pytest, no custom test files, no automated test suite); all
  functional verification of the web UI and its flows is done with
  **obscura (the headless browser) only**. The 📋 Tests row in the §5 feature
  tracking table was updated accordingly.
- Files touched: `PROJECT.md` (+ this `CHANGELOG.md` entry).
- Verified: edits reviewed in the diff; Vector_DB store re-indexed
  (`python index_db.py` → 1 indexed, 20 unchanged) so retrieval reflects the
  updated documentation.

**Feature — simplified top nav, export inclusion tags, search by any field, Palo Alto XML vs. set format:**
- **Top navbar simplified.** The top navbar now contains only:
  - dashboard (`/`): **Dashboard** and **Trash**;
  - every project page (project view **and** Export page): **Dashboard** only.
  The other navigation (firewalls, objects, export) stays available inside the
  page content (chips, type tabs, step links).
- **Export button on the objects page.** On
  `/objects?project_id=…&firewall_id=…&object_type=…` the export action is now
  a **button below the results table** (previously a navbar link), pre-filled
  with the current project, firewall and object type.
- **Search beyond the object name.** The objects page search box gained a
  field selector — *Any field* (name, description and every payload value of
  the current type), *Name*, *Description*, plus one option per displayed
  payload column (e.g. `Address`, `Type` for addresses; `Action`, `Source
  zones`, `Destination zones`, `Services` for rules). The API filters the bare
  field name against the JSON payload (`?address=`, `?action=`, …);
  `?search=` remains the generic full-text filter.
- **"Include in the export" tagging.** Every object row has a checkbox and an
  **"Include in the export"** button (per row, plus an all-rows variant above
  the table); the state is shown with an *in export* badge and persisted as
  `ConfigObject.export_included` (new column, default false, live
  `ALTER TABLE` on existing DBs) via `POST /api/objects/export-include`
  (`{object_ids, include}`).
- **Export form object types (Palo Alto).** In step 2 of the Export page,
  every checked object type has a scope radio, **"Only tagged objects"** by
  default (the elements tagged "Include in the export"), with the
  **"All objects"** option to include everything (even the not-included
  ones). The summary (step 3) shows the per-type object count and the total,
  and for **Palo Alto** firewalls the delivery format can be chosen:
  **PAN-OS config document** (`.xml`, `<paloalto>` XML, default) or
  **Set / display format** (`.txt`, `set …` lines as produced by
  `show config`). `POST /api/export/file` accepts `format` (`xml`/`set`)
  and `tagged_only_types`; files are served for 1 hour via a tokenized
  download URL.
- Files touched: `app/models.py`, `app/factory.py`, `app/views.py`,
  `app/api/routes.py`, `app/vendors/paloalto.py`, `app/vendors/fortinet.py`,
  `templates/{base,_dashboard_nav,_project_nav,project,objects,export}.html`,
  `static/js/app.js`, `CHANGELOG.md`.

**Bug fixes found during verification (same session):**
- `_build_config` now forwards `format` to the vendor parser — previously the
  "set" export silently produced XML.
- `FortinetParser.generate_config` accepts the new `format` keyword (ignored;
  Fortinet has one format) so Fortinet exports keep working.
- Parser round-trip of app-generated documents:
  - address groups are now emitted as `<address-group name=…>` (the tag used
    by real PAN-OS 11.x exports, matching the parser);
  - `_xml_object_entries` accepts app-generated `<objects><tag name=…>`
    elements directly (not just `<entry>` children);
  - `_xml_zones` accepts app-generated `<objects><zone name=…><member>`
    elements;
  - set-format detection accepts a file with a single `set` line (previously
    ≥10 lines required), so small tagged exports round-trip;
  - member-less zones are emitted as `set zone NAME network` and re-parsed as
    empty-member zones.
- The objects page field selector now sends bare payload keys (`address`,
  not `payload.address`) to the API.

**Verified:**
- Flask test-client suite (63 checks, all passing): navbar contents per page
  (dashboard = Dashboard+Trash; project/export pages = Dashboard only);
  objects page UI (field selector, per-type payload options, per-row tag
  checkbox + button, badge, Export button below the table); search by name /
  description / payload field / generic superset; tag endpoint + persistence
  + untag; tagged-only XML export (3/3, `.xml`, `application/xml`); tagged-only
  set export (3/3, `.txt`, `text/plain`) with name/value round-trip; full set
  and full XML exports with round-trip counts matching the DB (1191 address /
  99 address_group / 280 service / 27 service_group / 2476 rule / 38 zone);
  invalid format rejected 400; tags cleaned afterwards.
- Parser regression suite: 11.x device-export shape, older object-only
  export shape, and set format with bracketed lists and quoted descriptions
  all still parse.
- `node --check static/js/app.js` → OK.
- Real boot smoke test: all pages 200 over HTTP, including the new
  objects-page markup.
- Fortinet export smoke test: FGT-600E export still works with the new
  `format` argument.

---

**Feature — created firewalls are now editable (and importable from anywhere):**
- `app/api/routes.py`: new `GET/POST/PATCH /api/firewalls/<id>`.
  - `GET` returns the full record — the list endpoint deliberately hides
    credentials, so the edit form fetches them here (`api_username`,
    `api_password`, `api_token` + `project`, `objects_count`, `has_config`).
  - `POST`/`PATCH` update every field of the creation wizard (name, vendor,
    model, management IP, auth mode, login/password or API token,
    description); an empty value clears a field, the inactive credential side
    is cleared automatically, `project_id` (integer or null) reassigns /
    unassigns the firewall and syncs the objects via `set_project()`.
    Validation: name required, vendor must be registered, auth_mode
    password|token, friendly error on the `(project_id, name)` unique
    constraint.
- `templates/_firewall_edit.html` (new): Alpine edit modal — same fields as
  wizard step 1; mounts while the page scope has `editing` set, loads the
  current values on open, saves via `PATCH /api/firewalls/<id>` and calls
  `reloadFirewalls()` to refresh the list.
- `static/js/app.js`: new `firewallEdit(vendorChoices, firewallId, onSaved)`
  component; `dashboard()` and `firewallDashboard()` gain `editing`,
  `openEdit(fw)` (remounts the modal per firewall) and `reloadFirewalls()`;
  `firewallDashboard.init()` deep-links `/firewalls?edit=<id>` (used by the
  project table's Edit action).
- `templates/firewalls.html` + `templates/index.html`: per-card **Import**
  (`/import?firewall_id=…`, the existing import wizard jumps straight to the
  source step) and **Edit** buttons on every firewall card; both include the
  edit modal.
- `templates/project.html`: per-row **Edit** deep link in the firewall table
  (opens the edit modal on the firewall dashboard page).
- Files touched: `app/api/routes.py`, `templates/_firewall_edit.html` (new),
  `templates/{firewalls,index,project}.html`, `static/js/app.js`,
  `PROJECT.md`, `CHANGELOG.md`.
- Verified: 49-check round-trip on a temp DB (create → detail incl.
  credentials → full edit, auth-mode switches both ways with automatic
  credential clearing, empty-value clearing, validation errors incl. name
  clash, reassign/unassign with object `project_id` sync, POST-as-update,
  all five pages render 200 with the modal/buttons present, 404s for
  unknown ids); `node --check` on `app.js`.

**Bug fix — the firewall edit form was broken (Alpine component never mounted):**
- Root cause: `templates/_firewall_edit.html` used a double-quoted
  `x-data="firewallEdit({{ vendor_choices | tojson }}, ...)"`. The `tojson`
  list contains double quotes, which terminate the HTML attribute after
  `firewallEdit([` — Alpine logged `Unexpected token '}'`, the
  `firewallEdit()` component was never initialized, and none of the modal's
  bindings (x-model / x-show) worked (every field evaluated against the
  outer page scope → "vendor is not defined", etc.).
- Fix: single-quoted the `x-data` attribute (the convention already used by
  `_firewall_wizard.html`), and wrapped the list-refresh callback in an arrow
  — `() => reloadFirewalls()` — so the outer component's `this` is kept when
  the inner component calls it after saving.
- Also guarded the pre-existing console errors in `_firewall_wizard.html`:
  `connResult` / `importResult` expressions (`.ok`, `.detail`, `.message`,
  `.counts`, `.warnings`) were evaluated while still `null`; now
  short-circuited with `connResult && …` / `importResult && …`.
- Files touched: `templates/_firewall_edit.html`, `templates/_firewall_wizard.html`.
- Verified in a live headless browser against the running server: edit modal
  opens pre-filled (name, vendor, model, mgmt IP, auth mode, stored
  credentials, description) from the firewall dashboard, the main dashboard
  and the `/firewalls?edit=<id>` deep link; edited fields + switched auth
  password → token and saved: modal closed, card list refreshed in place,
  `GET /api/firewalls/<id>` reflected every change (token stored, login /
  password cleared); creation wizard still validates and advances through
  its steps; served HTML contains all guards. The test edits made to
  `PA-3410` during verification were restored to their original values via
  the API afterwards.

---

## 2026-11-23 (three-step flow rebuild)

**Docs — documented the correct way to background the Vector_DB re-index on Windows** (cmd `start` + redirection pitfall).
- `PROJECT.md` §7: warning in workflow step 4 + "Backgrounding the re-index on Windows" note in the §7 Notes.
- `Vector_DB/README.md` §2: "Running the indexer in the background (Windows)" — same pitfall + a ready-to-use `Start-Process` snippet.
- Why: `start "" python index_db.py > _reindex_log.txt 2>&1` only redirects `start`'s own console output; the child process's stdout/stderr go to a throwaway console, so the log stays empty and the process dies with that console.
- Correct pattern (already used in §7 step 1 for Ollama): PowerShell `Start-Process ... -RedirectStandardOutput _reindex_log.txt -RedirectStandardError _reindex_err.txt` with `python -u` for live unbuffered logging and `-PassThru` to check completion (`Wait-Process` / `$p.ExitCode`).
- Verified: both sections re-read after editing; the `Start-Process` form matches the Ollama launch pattern already documented in §7 step 1.

**Feature — the whole app reorganized around the three-step flow** (Dashboard
→ Project view → Export) with multi-step wizards. Verified: 74-check
end-to-end smoke run on a temp DB (import, stream import, project create +
attach, stats, objects CRUD + batch commit, export file/push, attach
restrictions), migration run on a copy of the real `instance/swissknife.db`
(columns added, `config_objects` rebuilt nullable, data + FKs intact,
idempotent second boot), live server run on the real DB (all pages 200,
API fields present), `node --check` on `app.js`.

**Feature — dashboard: exhaustive projects + firewalls lists**
- `templates/index.html` (rewritten) + `static/js/app.js` (`dashboard()`
  replaces `projectDashboard()`): one page, two card sections — **Projects**
  (name, description, firewalls, Open / Delete) and **Firewalls** (vendor
  badge, project or “Not attached”, mgmt IP + model, object count, Objects
  link, Delete) — both loaded from `/api/projects` + `/api/firewalls`, both
  with **New Project** / **New Firewall** buttons.
- Base navbar gains **Objects** and **Trash** links (`templates/base.html`).

**Feature — 3-step firewall creation wizard**
- `templates/_firewall_wizard.html` + `firewallWizard()` in `app.js` (modal
  on the dashboard and on the firewalls page): 
  - **Step 1** basic data: name, vendor, **model**, management IP,
    **authentication (login/password or API token)**, description.
  - **Step 2** import configuration: **file upload or REST API request**, with
    a **Check connectivity** button (vendor-aware probe) for the API source.
  - **Step 3** create the firewall, with the option to **skip the import**.
    When importing: **progress bar** — real XHR upload progress for files,
    NDJSON streaming progress (connect / download / parse / import) for REST
    sources via the new `POST /api/import/stream`; result + parser warnings
    shown afterwards, with “View imported objects” / “Done” buttons.
- `app/models.py` + `app/api/routes.py`: `Firewall` gains `model`,
  `auth_mode` (`password`|`token`) and `api_token` (credentials are stored
  per mode); `POST /api/firewalls` accepts the new fields; `GET /api/firewalls`
  adds `has_config` + `types_counts`.
- `app/factory.py`: one-off migration adds the three columns on existing
  databases (`ALTER TABLE ADD COLUMN`).
- **New `POST /api/connectivity`**: TCP :443 probe + one HTTP probe per vendor
  (Fortinet `/api?uuid=…`, PAN-OS `/api/?type=op…`, API token via
  `X-Auth-Token`), self-signed TLS handled; accepts a stored `firewall_id`
  or the raw wizard fields (firewall not yet created).

**Feature — 3-step project creation wizard**
- `templates/_project_wizard.html` + `projectWizard()` in `app.js` (modal on
  the dashboard): 
  - **Step 1** project name + description (validated).
  - **Step 2** attach **existing** firewalls — **only those that already have
    an imported configuration** (`has_config`); when none exist the step
    suggests **creating a firewall first** (opens the firewall wizard).
  - **Step 3** validation summary (name, description, firewalls to attach
    incl. “moves from …”) → `POST /api/projects` with `firewall_ids`, then
    the **newly created project page opens immediately**.
- `POST /api/projects` now accepts `firewall_ids` (existing firewalls are
  **moved** to the new project, with their objects — see `set_project()`
  below); invalid ids → 400.
- The old `POST /` Flask-WTF creation (with 2 firewall slots) and the
  project-page “Add firewall” form/route are **removed** — only existing
  firewalls can be attached (`views.add_project_firewall` gone;
  `attach_project_firewall` now refuses firewalls without an imported
  configuration).

**Feature — project page: detailed statistics + clickable count matrix**
- `app/views.py` `_project_stats()`: per-firewall/per-type object counts,
  **modified** counts (objects with an “update” change-history entry),
  column totals, last import timestamp.
- `templates/project.html` (rewritten): stat cards (attached firewalls,
  imported objects, object types, **modified objects**, last import);
  **“Objects by type, per firewall” matrix — clicking a count opens the
  object list filtered to that firewall + type** (total row per firewall
  included); firewall table (vendor/model, mgmt IP, auth mode, last import,
  objects + “(n modified)”, per-row Import / View Objects / Remove);
  “Attach existing” column restricted to imported firewalls; **no “Add
  firewall” column anymore**.
- `_project_nav.html` now exposes **Objects** (project-scoped) + **Export**.

**Feature — object list page: type-specific columns + staged Validate**
- `templates/objects.html` (rewritten) + `objectTable()` in `app.js`:
  - **Scope from the navigation context** (project / firewall / type chips) —
    project/firewall filter controls removed, name search kept.
  - **Columns specific to the object type** (address: Address/Type;
    rule: Action/Sources/Destinations/Services/Zones/Enabled; …) resolved
    from the normalized payload JSON (server passes the column map;
    generic fallback for unscoped views).
  - **Row actions: modify / delete / add.** Edits are **staged** in the
    browser (badges: *new* / *staged*; deletions hide the row); **the
    “Validate” button commits the whole batch** to the database via the new
    `POST /api/objects/commit` (single transaction, full rollback on any
    error, history + fingerprints updated); “Discard” resets. New
    `POST /api/objects` creates a single object (upsert).
  - **Pagination: total pages, next/prev, rows-per-page selector**
    (10 / 15 / 25 / 50 / 100 / 500) — `GET /api/objects` now returns
    `total_pages` and accepts `per_page` up to 500.
  - **Back-to-project** link (or dashboard when unscoped) and an **Export**
    button below the table (preselects the scoped firewall).

**Feature — export page: statistics + 4-step wizard**
- `templates/export.html` (rewritten) + `exportWizard()` in `app.js`:
  - Stats tables: **objects per firewall / per type** and **modified objects
    per firewall / type** (from `_project_stats()`).
  - **Step 1** destination firewall (attached firewalls only; preselected via
    `?firewall_id=` from the object page’s Export button).
  - **Step 2** filter by object type(s) (per-type counts + modified shown,
    select all / clear).
  - **Step 3** summary report (destination, types, object count) + method:
    **generate config file** (vendor-specific) or **push via API**.
  - **Step 4 (file)**: progress bar → **download link** (file kept in memory
    for 1 h, `POST /api/export/file` → `GET /api/export/file/<token>`) or an
    error message.
  - **Step 4 (push)**: **connection status** (connectivity probe, re-checkable)
    + **Push** button → **streaming progress** (generate → connect →
    authenticate → transfer → confirm) via `POST /api/export/push` →
    success/error message.
  - After a successful push or file download: **“Validate & return to
    project”** button.
- Legacy `POST /api/export` (download / mock push) kept for compatibility;
  shared `_build_config()` helper now backs both.

**Schema / model changes**
- `firewalls`: + `model VARCHAR(120)`, + `auth_mode VARCHAR(16)`
  (default `password`), + `api_token TEXT` (migration in `factory.py`).
- `config_objects.project_id` **now nullable** (objects of an unassigned
  firewall imported before any project exists) — one-off table-rebuild
  migration in `factory.py`; `Firewall.set_project()` (new) keeps all
  `config_objects.project_id` values in sync on attach/remove.
- `requirements.txt`: + `requests==2.34.2` (connectivity probe, REST
  retrieval/push) — was already imported but unlisted.

**Removed / changed**
- `POST /` (dashboard project creation) removed — project creation goes
  through the wizard (API). Project edit keeps `ProjectForm`.
- `views.add_project_firewall` route + project-page “Add firewall” form
  removed. `firewalls.html` New Firewall modal replaced by the 3-step wizard
  partial (shared with the dashboard).
- `app.js`: `projectDashboard` / `dataTable` replaced by `dashboard` /
  `objectTable`; new `projectWizard`, `firewallWizard`, `exportWizard`;
  `importWizard` default object types now all 9 (was address+rule).

**Files touched:** `app/models.py`, `app/factory.py`, `app/views.py`,
`app/api/routes.py`, `static/js/app.js`, `templates/{base,index,project,
objects,export,firewalls,_project_nav}.html`,
`templates/{_project_wizard,_firewall_wizard}.html` (new),
`requirements.txt`, `PROJECT.md`, `CHANGELOG.md`.

---

## 2026-11-23

**Feature — parsers rewritten: all 7 element types stored for both vendors; sample files indexed in Vector_DB:**
- `files/` now holds the reference samples of the file types accepted by
  Import (FortiGate `.conf`; PAN-OS XML export minified + pretty-printed;
  PAN-OS set/`show` format `.txt`) and they are indexed in the Vector_DB
  store (`python index_db.py files --ext conf,xml,txt`) — searching their
  content goes through the store with a `--where file=files/...` filter,
  never by direct reads. (Vector_DB: also fixed a chunker crash —
  `maximum recursion depth exceeded` — on minified one-line files like
  `MT-FGTVYV324082026.xml`.)
- `app/vendors/fortinet.py` (rewritten): now parses **address**
  (`config firewall address` + `address6`; `set subnet <ip> <mask>`/CIDR →
  CIDR, iprange, fqdn/wildcard-fqdn, associated-interface; `all`/`none`
  skipped + warned), **address group** (`config firewall addrgrp`),
  **service** (`config firewall service custom`; tcp/udp portranges
  normalized, `1-65535` → `any`, tcp+udp merged), **service group**
  (`config firewall service group`), **rule** (`config firewall policy`;
  name from `set name` or policy id, srcintf/dstintf, srcaddr/dstaddr,
  service, action accept→allow, nat/log/status/schedule/comments, source/
  destination zones resolved from the interface→zone map), **interface**
  (`config system interface`; ip normalized to CIDR, type/alias/role/zone)
  and **zone** (`config system zone`, or derived from interface `set zone`
  when that section is absent). `generate_config` emits all 7 types.
- `app/vendors/paloalto.py` (rewritten): handles **three export flavors** —
  PAN-OS 11.x XML device export (objects directly under `vsys/entry`, no
  `<objects>` wrapper), older wrapped exports and app-generated documents,
  and the **set (show) format** (quoted names, `[ ... ]` member lists,
  multi-line rules, `no set` ignored). Parses **address** (ip-netmask /
  ip / ip-netrange / fqdn), **address group** (`<static>` members; dynamic
  groups skipped + warned), **service** (protocol tcp/udp/icmp, port +
  source-port, `1-65535` → `any`), **service group** (`<members>`),
  **rule** (`from`/`to` = zones, `source`/`destination` = addresses —
  mirrored in the set format), **interface** (`network/interface/<type>/unit`
  when a full export provides them) and **zone** (vsys/zone or
  network/zone, layer3/layer2 members). `generate_config` emits all 7 types.
- `app/api/routes.py`: vendor auto-detection recognizes the PAN-OS set
  format (`set deviceconfig system`, `set rulebase security rules`, …);
  FortiGate markers are now scanned across the whole document (an export
  can spend its first tens of KB on `config system interface`); the object
  list JSON payload filters now use the normalized payload keys
  (`address`, `sources`, `members`, `port`, …).
- `PROJECT.md`: §1 (accepted file types), §2 (`files/` in the layout), §7 +
  §8 (Vector DB is the only search path for the `files/` samples), §5/§6
  updated.
- Verified (temp SQLite DB, API round-trip): FortiGate sample → **1198**
  objects (586 address, 52 address_group, 130 service, 11 service_group,
  374 rule, 45 interface, 0 zone — export defines none, 8 value-less
  entries warned); Palo Alto sample → **4111** objects (1191/99/280/27/2476
  rule/38 zone, 0 interface — object-only export) with **identical counts
  for all three file flavors** (pretty XML, minified XML, set format);
  re-import upserts without duplicates; `modification_history` written
  (13 531 rows); vendor auto-detection correct on all 4 samples.

**Fix — Palo Alto .xml imports failed (parse error / 0 objects):**
- `app/vendors/paloalto.py`: real device exports (e.g. `files/MT-FGTVYV324082026.xml`)
  were rejected or parsed to nothing because the parser expected the
  app-generated document shape:
  1. the sanity check demanded `<paloalto`/`rulebase` in the first 2 KB — a
     device export leads with `<config ...>` + a long `<mgt-config>`;
     replaced by a structural check (root tag `config`/`paloalto` or a
     `<vsys>` somewhere). XML is now parsed from **bytes**, which also
     prevents the ElementTree "Unicode strings with encoding declaration"
     ValueError (a 500) on exports with a declaration + non-ASCII text.
  2. objects live as `<address|addrgrp|service><entry name="...">` in device
     exports — the parser now reads the `entry` elements (falling back to the
     app-generated `<address name="...">` shape); addresses may use `<ip>`,
     `<fqdn>` or `<ip-netrange>`.
  3. rules live under `rulebase/security/rules/entry` in device exports;
     `<source>/<destination>` hold the address objects while `<from>/<to>`
     hold zones — the parser now maps them correctly (falling back to
     `<from>/<to>` for app-generated documents) and records `<disabled>`.
- `app/api/routes.py`: vendor auto-detection scans the first 20 KB and also
  recognizes `paloaltonetworks` / `<config`+`vsys` (device exports lead with
  the XML header, so `rulebase` was often outside the old 2 KB window).
- Verified: with the sample Palo Alto export on a temp DB — `POST /api/import`
  returns 200 and imports **2476 rules** (e.g. `GSM-INTERNET`: sources
  `SVPGSM01_10.240.59.1`, destinations `GP_Internet`, services `any`,
  description kept); the 3.84 MB pretty-printed export imports the same 2476;
  re-import upserts without duplicates; app-generated `<paloalto>` documents
  (address/addrgrp/service/rule) still parse (round-trip regression check).

**Fix — importing a FortiGate .conf returned "Internal server error." (two bugs):**
1. `app/api/routes.py`: `current_user()` (and `auth_login`) used
   `request.session`, which does not exist on Flask 2.x's Request object and
   raised `AttributeError` → generic 500 "Internal server error." on every
   `/api/import` (and any object update/delete/restore). Switched to the
   `session` global (already imported). Vendor detection also recognizes
   FortiOS 7.x `config firewall address` now.
2. `app/vendors/fortinet.py`: the parser only looked for a top-level
   `config address` section and CIDR values, so FortiOS 7.x exports
   (section `config firewall address`, entries like
   `set subnet 172.16.3.0 255.255.255.0`) parsed to **0 objects**. The
   section regex now matches both locations, the address regex accepts
   `set subnet <ip> <mask>` / `set ip <ip>` / CIDR, and values are
   normalized to CIDR (`ipaddress`); non-IP entries (iprange, fqdn, the
   "all" object) are skipped and reported as an import warning.
- `PROJECT.md`: §5 import row and §6 (partial vendor parsers) updated.
- Verified: with the sample `files/FGT_CHATEAUDUN_2_7-2_1761_202610011359.conf`
  (FortiGate 7.2.12) on a temp DB — `POST /api/import` (wizard defaults
  `address,rule`) returns 200 and imports 339 addresses with correct CIDRs
  (`Lan_172.16.3.x` → `172.16.3.0/24`, `none` → `0.0.0.0/32`), comments kept,
  254 non-IP entries skipped with a warning; objects attributed to the logged
  in user; re-import upserts without duplicates; `/api/auth/login` works and
  rejects bad credentials.

**Removal — Form Demo feature deleted:**
- Removed the demo form: `app/views.py` route `/form-demo`
  (`views.form_demo`), `app/forms/demo_form.py` (`DemoForm`), and
  `templates/form_demo.html`; `app/forms/__init__.py` no longer exports
  `DemoForm` (`__all__` is now `["ProjectForm"]`).
- `templates/base.html`: "Form Demo" nav link removed (navbar is now
  Dashboard / Firewalls).
- `PROJECT.md`: §2 layout notes updated (forms/ line and base.html line).
- Vector_DB store: re-indexed with `--prune` (chunks of the deleted
  `demo_form.py` dropped).
- Verified: app boots on a temp DB; `/`, `/firewalls`, `/projects` render
  200 without any "Form Demo" reference; `/form-demo` returns 404;
  `app.forms` still exposes `ProjectForm`.

**Docs — "query Vector DB before reading files" is now the stated priority:**
- `PROJECT.md`: the document header now states the priority explicitly — for
  LLM-assisted work, query the Vector_DB store
  (`C:\Users\hedhl\source\repos\Vector_DB`, usage per its `README.md`) BEFORE
  reading any file of this repository, to reduce token consumption; direct
  file reads only on 0-chunk retrieval or when exact content is needed for an
  edit. §7 intro/step 2 reworded the same way (README.md named as the usage
  reference), and it is now maintenance rule **1** in §8 (rules renumbered).
- Verified: header + §7 + §8 consistent; all section anchors in `PROJECT.md`
  still resolve.

**Feature — firewalls dashboard + per-row "Remove" (unassign) on the project page:**
- `templates/firewalls.html` (rewritten) + `static/js/app.js`: `/firewalls`
  is now a **Firewall Dashboard** in the same style as the project dashboard —
  card grid (name, vendor badge, project or "Not attached to a project",
  management IP, object count), **New Firewall** button with modal
  (name / vendor / management IP / optional project / description), per-card
  **Objects** link and **Delete** (confirm → `POST /firewalls/<id>/delete`).
  New Alpine component `firewallDashboard()` loads `GET /api/firewalls`.
- `app/api/routes.py`: `GET /api/firewalls` items now include `project`
  (null when unassigned) and `objects_count`; `POST /api/firewalls` and
  `views.firewalls_page` accept an optional project (unassigned firewall).
- `app/models.py` + `app/factory.py`: `firewalls.project_id` is nullable.
  `create_app()` runs a one-off SQLite migration that rebuilds the
  `firewalls` table on existing databases to drop the NOT NULL constraint
  (fresh databases are created nullable and skip it).
- `app/views.py`: the per-row action on `GET /projects/<id>` is now **Remove**
  — `POST .../firewalls/<fw_id>/remove` sets `project_id` to NULL (firewall
  and its objects are kept). Unassigned firewalls show up in the
  "Attach existing" column ("… — Unassigned") and on the firewall dashboard.
  New `POST /firewalls/<fw_id>/delete` hard-deletes a firewall + objects
  (used by the dashboard); the project-scoped `delete_project_firewall`
  route was removed.
- `templates/base.html`: **Firewalls** nav link added.
- `PROJECT.md`: §2 layout notes and the §5 Done table updated; §6 mentions
  the built-in one-off migration.
- Verified: temp-DB run (legacy NOT NULL schema migrated with data + indexes
  intact; fresh-DB path skipped) plus a copy of the real `instance/` DB
  (demo data intact, `PRAGMA foreign_key_check` clean); test-client checks
  for the dashboard page/modal, API fields, unassigned create, remove →
  unassigned with objects kept, re-attach, and dashboard delete.

**Docs — Vector_DB re-indexing is now a mandatory maintenance step after any change:**
- `PROJECT.md`: new maintenance rule 5 in [§8](PROJECT.md#8-maintenance-rules) —
  after any change to code or documentation, re-index the Vector_DB store
  (`python index_db.py` from `C:\Users\hedhl\source\repos\Vector_DB`, add
  `--prune` when files were deleted) so context retrieval stays current;
  §7 step 4 remains the detailed procedure.
- Verified: rule added and cross-anchored to §7; `PROJECT.md` sections and
  anchors unchanged otherwise.

**UI change — project page: firewall row "Change..." replaced by "Delete" (with confirmation):**
- `templates/project.html`: each firewall row no longer has the "Change..." dropdown
  (Move to… / Delete firewall) + "Apply" button; it now has a single **Delete**
  button whose form only submits after a `confirm()` dialog.
- `app/views.py`: new route `POST /projects/<id>/firewalls/<fw_id>/delete`
  (`views.delete_project_firewall`) deletes the firewall — its objects
  cascade-delete with it; the old `views.detach_project_firewall` route and the
  now-unused `other_projects` template variable were removed. Moving a firewall
  to another project is still possible via the "Attach existing" column on the
  target project's page (or when creating a project).
- `PROJECT.md`: §2 layout note and the §5 Done table updated.
- Verified: app boots on a temp DB; `GET /projects/<id>` renders 200 with a
  Delete button per firewall row (no "Change..." dropdown), the separate
  "Add firewall" column intact; `POST .../delete` removes the firewall and its
  objects and redirects with a success flash.

**UI change — project page: "Add firewall" split into a separate column:**
- `templates/project.html`: on `GET /projects/<id>` the single firewalls card
  (list table + add/attach forms in a gray footer) is now a two-column
  layout — the firewall list table in the left column (2/3 width) and a
  separate right column holding its own **Add firewall** card (name / vendor
  / management IP / submit) and **Attach existing** card. Stacked vertically
  on narrow screens; the list card no longer contains any add/attach forms.
- Hint and empty-state texts updated to point at the new column.
- No route/form-name changes: the forms still post to
  `views.add_project_firewall` and `views.attach_project_firewall`.
- Verified: app boots; `/projects/<id>` renders 200 with the list table and
  the add/attach column side by side (test client + browser screenshot);
  empty-project variant renders the "Add firewall" column with the empty-list
  text.

**Refactor — changelog moved to a separate `CHANGELOG.md` file:**
- `PROJECT.md` §4 no longer contains the log; it now points to `CHANGELOG.md`
  (this file, repository root).
- `PROJECT.md`: maintenance rule 1 updated to reference `CHANGELOG.md`;
  stale `#7-maintenance-rules` anchor in the document header fixed
  (maintenance rules are in §8).
- Verified: all section anchors in `PROJECT.md` resolve; `PROJECT.md`
  re-indexed by the Vector_DB project.

**Refactor — RAG pipeline extracted to the standalone `Vector_DB` project:**
- The local RAG pipeline (ChromaDB + Ollama `nomic-embed-text`) that was
  integrated into this repo earlier the same day now lives in an independent
  project: `C:\Users\hedhl\source\repos\Vector_DB` (see its `README.md`).
- Removed from this repo: `app/rag/`, `app/api/rag.py`, `index_db.py`,
  `rag_query.py`, `.vectordb/` (store data moved to Vector_DB);
  `app/factory.py` and `requirements.txt` restored to their pre-RAG state;
  `.gitignore` recreated (minimal: `.venv/`, `__pycache__/`).
- `PROJECT.md` [§7](PROJECT.md#7-vector-db-integration-token-efficient-development)
  now documents how to use Vector_DB when modifying this project or adding
  new features (token-efficient context retrieval).
- Verified: Vector_DB indexes this repo (20 files / 159 chunks), re-index
  skips unchanged files and prunes deleted ones, CLI + HTTP service queries
  work (relevant queries -> 3 chunks, unrelated -> 0 chunks), and this app
  boots unchanged (`create_app()` + test client 200 on `/` and
  `/api/projects`).

**Fix — dashboard "New Project" was dead (multiple root causes):**
1. `static/js/app.js` was never included in any template → Alpine components
   (`projectDashboard`, `importWizard`, `dataTable`, `trashBin`) were undefined.
   Added the script tag to `templates/base.html`.
2. `instance/swissknife.db` had **no tables** — `create_app()` never called
   `db.create_all()`. Added `db.create_all()` in `app/factory.py` **after** the
   blueprint imports (models register tables at import time; calling it earlier
   creates nothing).
3. **Alpine init race:** the Alpine CDN build auto-starts via
   `queueMicrotask()` right after its own script body, i.e. before any later
   deferred script runs. `app.js` must therefore load **before** Alpine
   (order fixed in `base.html`, with an explanatory comment).

**Feature — "New Project" converted to a Flask-WTF form:**
- `views.dashboard()` handles `GET + POST` with `ProjectForm`.
- Server-rendered modal in the dashboard (CSRF, inline errors, flash
  messages, modal auto-reopens after validation errors).

**Feature — demo data:**
- Seeded "Demo Project" with `palo-demo` (paloalto, 10.0.0.10) and
  `forti-demo` (fortinet, 10.0.0.20) in `instance/swissknife.db`.

**Feature — dashboard project cards:** Open / Edit / Delete (with
`confirm()`), delete cascades to firewalls + objects.

**Feature — create-project form with 2 firewall slots:**
- `ProjectForm` extended: per slot, `-- None --` / `Create new firewall` /
  pick an existing firewall from the DB (attaching/reassigning it to the new
  project). "Create new" reveals name, vendor (dropdown of registered
  vendors) and management IP.
- Validation: new firewalls need name + vendor; the same existing firewall
  cannot be selected in both slots; duplicate names → friendly flash errors.
- After creation, redirects to the new project page.

**Feature — project page with conditional navbar:**
- `GET /projects/<id>` (`views.project_detail`). Navbar shows **only**:
  - **Import** — only while the project has no imported objects
  - **Firewalls** — only while the project has firewalls defined
  - **Objects** — only once objects are parsed/stored (link pre-filtered to
    the project)
  - **Export** — always
- Page shows project info, firewall table with per-firewall object counts,
  and a "nothing imported yet" hint.
- Implemented by making the navbar in `base.html` a `{% block nav %}` and a
  `_project_nav.html` partial.

**Feature — project edit page:**
- `GET/POST /projects/<id>/edit` — name + description, Flask-WTF form with
  CSRF, prefilled; returns to the project page after saving.

**Feature — export page:**
- `GET /projects/<id>/export` — firewall selector, object-type checkboxes
  (all 9 types checked by default), **Download config** (file generated by the
  vendor parser) and **Push to firewall** (mock), inline error display.
  Uses the existing `POST /api/export` endpoint.

**Fix — form validation bugs found during testing:**
- `ProjectForm.validate()` dropped the parent return value →
  `validate_on_submit()` returned `None` (always falsy); now returns a real
  bool and flips it on custom errors.
- `SelectField`s with no submitted value fail "Not a valid choice" → the
  form now defaults unsubmitted selects to the blank value (edit page does
  not render the firewall selects).
- `edit_project` used a bare `ProjectForm` without firewall choices →
  "Choices cannot be None"; now uses the shared `_project_form()` helper.

**Testing:** end-to-end verification of the whole flow (create with new +
existing firewalls, firewall reassignment, conditional navbar before/after
import, edit, export, delete with cascades, validation errors) plus real
browser checks (Alpine state, console clean, modal interactions).
