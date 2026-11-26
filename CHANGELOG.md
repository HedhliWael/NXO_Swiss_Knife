# NXO Swiss Knife — Changelog

Chronological log of all modifications to the project. **Newest first.**

> Moved out of `PROJECT.md` §4 on 2026-11-23 — `PROJECT.md` now only points
> here. Entries are added per the
> [maintenance rules](PROJECT.md#8-maintenance-rules): what changed
> (bug fix / feature / refactor), which files were touched, and how it was
> verified.

---

## 2026-11-26

**Real authentication replaces the placeholder: session login with user + password, accounts in a SEPARATE users database (`instance/users.db`), `admin` bootstrapped on first start, and user management (add / reset password / enable-disable / delete) on the dashboard's new Users section — every page and API route is protected:**

- `app/auth.py` (new): the whole authentication layer.
  - `authenticate()` — looks the user up in the users DB and verifies the hash with `werkzeug.security.check_password_hash`; generic "Invalid username or password" for every failure, **timing equalization** (a real dummy-hash check when the user does not exist, so "unknown user" costs the same as "wrong password"), 0.5 s delay + `logger.warning` with the client IP on failed attempts.
  - `GET/POST /login` (standalone page), `POST /logout` (POST-only — no forced logout via a plain link), `GET /login` redirects signed-in users to the dashboard; the form carries a hidden `next` field so the original target survives a failed attempt.
  - `POST /api/auth/login` (JSON, same URL as the old env-var placeholder — now validates against the users DB and sets the same session cookie, so API clients can authenticate programmatically) + `GET /api/auth/me`.
  - `/api/users` CRUD: `GET` (never returns the hash), `POST` (username 2-64 chars `[A-Za-z0-9._-]` + unique, password min 8 / max 128 or **server-generated and returned once**), `PATCH` (`display_name`, `is_active`, `generate_password` → new random password returned once, or explicit `password`), `DELETE`. Guards: **no deleting or disabling your own account**, and the **last active account** cannot be disabled or deleted.
  - `before_request` login guard: page routes redirect anonymous browsers to `/login?next=<path>` (relative same-origin only), `/api/*` answers JSON `401`; static files, unknown paths (404) and the login routes stay open.
  - `ensure_admin_user()`: when the users DB is empty, creates the initial `admin` account — password from `SWISSKNIFE_ADMIN_PASS`, otherwise a random one **printed to the console once** (flushed; stored hashed, not recoverable).
  - JSON error handlers for the auth/users blueprints (mirroring the ones of `api_bp`).
- `app/models.py`: new `User` model — `__bind_key__ = "users"` → its own file `instance/users.db` via `SQLALCHEMY_BINDS` (Flask-SQLAlchemy 3.0.5 refuses two `SQLAlchemy()` instances per app, so the bind mechanism is used; the existing `db.create_all()` creates the table there automatically). `set_password`/`check_password` (scrypt + random per-password salt), `is_active`, `last_login_at`, `to_dict()` without the hash.
- `app/factory.py`: `SQLALCHEMY_BINDS` (`USERS_DATABASE_URL`, default `sqlite:///users.db`), session hardening (HttpOnly, SameSite=Lax, `SWISSKNIFE_SESSION_SECURE` for `Secure`, 8 h lifetime), `ensure_admin_user()` after the migrations, `init_auth(app)` (blueprints + guard).
- `app/api/routes.py`: `current_user()` now returns the session username (was the Bearer-token/"system" placeholder); the demo `POST /api/auth/login` (env-var comparison) removed — replaced by the same URL in `app/auth.py`.
- `templates/login.html` (new): standalone sign-in page in the app's design system (brand row, centered card, flash errors, first-start admin hint, `next` preserved).
- `templates/base.html`: navbar gains the signed-in **user chip** + **Sign out** POST form (outside the `nav` block, so the project pages' navbar shows them too).
- `templates/index.html`: new fourth section **Users** (Administration) — one `userManagement()` Alpine instance wraps the whole section (the Add user button, the table and the modal share its state); the `x-data` embeds the signed-in username as JSON → single-quoted attribute per the Alpine note in PROJECT.md §2. Table: username (+ "you" badge), display name, active/disabled badge, last login, created, actions; **Add user** modal (password optional → generated, shown **once** in a warning notice with a Copy button); Reset password / Enable / Disable / Delete behind confirms.
- `static/js/app.js`: new `userManagement(me)` component (list, add, one-shot generated-password notice + clipboard copy, reset/enable-disable/delete via the API).
- `.gitignore`: + `instance/users.db`.

- Files touched: `app/auth.py` (new), `app/models.py`, `app/factory.py`, `app/api/routes.py`, `templates/login.html` (new), `templates/base.html`, `templates/index.html`, `static/js/app.js`, `.gitignore`, `PROJECT.md` (§1/§2/§3/§5/§6), `CHANGELOG.md`.
- Verified: background server + 64-check API probe (`QA/_test_auth.py`, 64/64 pass): guards (302 `/login?next=…` on pages, JSON 401 on the API, static + 404s stay open), login (bad/unknown-user → generic 401 + no session; good → 302 + HttpOnly SameSite=Lax cookie + `next` honored; JSON login endpoint), users CRUD (create with explicit/generated password, duplicate/invalid username, short password → 400, list never leaks the hash), new users signing in, self + last-active guards, disable → login blocked → re-enable, password reset (generated + explicit, old password stops working), delete + username reuse, logout (POST only, session gone). Headless browser: login page (failed attempt shows the flash), sign-in → dashboard with the navbar user chip + Sign out, Users section table + **Add user** via the UI (generated-password notice with Copy rendered, new row present), Sign out → back to the login page. Regression: all core pages (`/`, `/projects/3`, objects, firewalls, trash, import, export) 200 for a signed-in session; demo data intact; trashed project 1 correctly 404s. During the round, stale dev servers from earlier sessions (two `flask --debug` pairs, an old `create_app().run` pair, an `http.server 8123` pair) were found holding the DBs and restarted the app on file edits — stopped and cleaned up.

---

## 2026-11-25

**Vector_DB RAG pipeline refactored (chunker v2 + strict token budget): fixes the ~262,411-token prompt overflow — token-accurate Python-aware chunking (400/500 tokens, 0% overlap, tiktoken), context headers, noise exclusion, top-k hard cap (12), chunk deduplication, and a 7,000-token hard budget enforced before every prompt:**

*Root cause of the token explosion (diagnosed on the live store):*
- The old word-based chunker (`CHUNK_MAX_WORDS=500`) could not bound token size: `split_line()` returned a whole line unchanged when it held ≤500 whitespace-separated "words", so the minified 1.95 MB PAN-OS XML and the FortiGate `.conf` produced **47,568-token chunks**. The store held 1,200 chunks over 500 tokens (401 over 2,000), and a 12-chunk retrieval measured **258,576 tokens** — matching the observed ~262k overflow.
- No token budget existed at retrieval time (only a chunk-count cap), and 94% of the corpus was the 4 non-source `files/` sample configs (+ QA test logs).

*Changes (all in the companion **Vector_DB** project `C:\Users\hedhl\source\repos\Vector_DB`):*
- `app/rag/tokens.py` (new): tiktoken (cl100k_base) wrapper — `count_tokens`, `split_tokens` (token-boundary hard split), `truncate_to_tokens` (idempotent boundary cut with marker). All size math uses a real tokenizer instead of character/word counts.
- `app/rag/config.py`: token-based config — `RAG_CHUNK_TARGET_TOKENS=400` / `RAG_CHUNK_MAX_TOKENS=500` / 0% overlap; `RAG_TOP_K=10` + `MAX_TOP_K=12` hard cap; `RAG_TOKEN_BUDGET=7000`; `CHUNKER_VERSION` stamp per chunk; noise exclusion extended (`QA/`, tool caches, `*.egg`, and non-source data extensions `.json`/`.csv`/`.tsv`/`.db`/`.sqlite`/`.bin`/`.dat`/`.parquet`/`.pyc`/`.so`/`.dll`/`.exe`/`.pdf`/media/logs are never indexed, even via `--ext`); optional `RAG_MAX_FILE_SIZE_BYTES` guard.
- `app/rag/chunker.py` (rewritten): Python split at **function granularity** via the Tree-sitter AST — every `def`/method stays intact (decorators attached); small classes stay one block, large classes become a definition block + one block per method (`Class.method`, nested classes recurse). Every chunk gets a **context header prepended before embedding** (`# File: app/models.py | Class: Firewall | Function: to_dict`). Greedy packing at 400-token target / 500-token hard cap with 0% overlap; a final token-boundary safety net guarantees **no chunk can ever exceed 500 tokens** (the old unbounded-chunk hole is closed).
- `app/rag/retrieval.py`: top-k hard-capped at 12; **deduplication** of duplicate/overlapping chunks (exact + containment, best score wins); **strict token budget** enforced right before prompt build (`enforce_token_budget` / `prepare_prompt`) — lowest-scoring chunks dropped until the context fits 7,000 tokens, best chunk truncated if even it alone exceeds the budget; size-damped ranking now token-based.
- `index_db.py`: prints chunker version + a **CHUNKER UPDATE PENDING** reminder (with the `python index_db.py --rebuild` command) whenever chunks from an older chunker are detected — unchanged files would otherwise keep stale, unbounded chunks (content-hash skip).
- `rag_query.py`: `--token-budget` option, per-chunk token counts + `context N / 7,000 tokens` line in the output.
- `app/api/rag.py`: `n_results` clamped to 12, `token_budget` request parameter, response now reports `context_tokens` + `chunks_dropped_for_budget`.
- `requirements.txt`: + `tiktoken>=0.7.0` (installed in the Vector_DB venv).
- **Wipe & re-index executed** (`python index_db.py --rebuild`): the store now holds 2,594 chunks from 36 files — **0 chunks over 500 tokens** (was 1,200), worst-case 12-chunk context is 6,000 tokens (was 258,576); QA/ logs are no longer indexed.

- Files touched (Vector_DB): `app/rag/tokens.py` (new), `app/rag/config.py`, `app/rag/chunker.py`, `app/rag/retrieval.py`, `app/rag/store.py`, `app/api/rag.py`, `index_db.py`, `rag_query.py`, `requirements.txt`, `README.md` (chunking/retrieval/config docs + new §2.1 wipe & re-index); (this repo): `PROJECT.md` §7, `CHANGELOG.md`.
- Verified: chunker smoke test on the real corpus — every chunk ≤500 tokens on all file types (incl. the 1.95 MB one-line minified XML, the 778 KB FortiGate `.conf` and the 2.5 MB PAN-OS set format); Python function-level blocks confirmed (`Firewall.to_dict`, `PaloAltoParser._parse_xml` … intact, headers correct); budget unit checks (drop + truncation paths hold the budget exactly); live queries through Ollama: `"How does the trash permanent delete work?"` → 10 chunks, **4,429/7,000 tokens**; config-file query → 5,088/7,000; HTTP API: `n_results: 99` clamped to 12, `token_budget: 1500` → 1,082 tokens + 7 dropped, `/api/rag/status` healthy (2,594 chunks / 36 files).

---

## 2026-11-26

**Object trash (project trash can): permanent delete with row selection + delete-all, and the search filter actually shows the objects — and the import wizard's review step gets a "Back to project" button instead of "Import again":**

*Bug fix — the project trash can's object table rendered no rows at all (`static/js/app.js`):*
- `trashBin().filteredItems` was a **method**, but the template reads it as a property: `x-for="item in filteredItems"` iterated the function itself (non-iterable) and `filteredItems.length > 0` tested the function's argument count, so the table was always "visible" yet empty and the "no match" empty state could never show. It is now a **getter** — all deleted objects of the project are displayed, and the search box (name / type / firewall / project / reason, client-side) filters them with the "no match" empty state working as intended.

*Feature — permanent delete of deleted objects from the project trash can:*:
- `app/api/routes.py`: new `POST /api/trash/permanent-delete` — `{trash_ids: [...]}` removes exactly the selected trash entries, `{all: true, project_id: N}` removes every deleted object of that project. Only un-restored `item_type == "object"` entries are in scope; deleting the object cascades (delete-orphan) to its modification history and its trash row, so the name is freed and the entry can never be restored. Dangling entries (object row already gone) are dropped. Errors: no ids + no `all` → 400, `all` without `project_id` → 400, nothing matched → 400.
- `static/js/app.js`: `trashBin()` gains `selected[]` (row checkboxes), `toggleSelect()` / `allSelected` (getter, header checkbox over the currently filtered rows) / `toggleAll()`, and `deleteSelected()` / `deleteAll()` — both behind a `confirm()` ("…This cannot be undone."), POSTing to the new endpoint and reloading on success; all action buttons stay disabled while a delete is in flight (`busy` flag, same pattern as restore).
- `templates/trash.html`: the Objects section of the project trash can gets a selection checkbox column (header checkbox + per-row, aria-labelled) and a toolbar with **Delete selected (N)** + **Delete all (N)** (existing `.btn.btn-danger.btn-sm` style, trash-can SVG, disabled states: nothing selected / trash empty / busy) next to the search box; the section sub now mentions restoring *or* deleting for good.

*Feature — import wizard review step: "Back to project" instead of "Import again" (`templates/import.html`):*
- Step 3 (Review) after a successful import: the "Import again" button is gone (the wizard has no re-import — a new import is started from the page's back link / firewall row as before); instead a primary **Back to project** button appears (labelled **Back to dashboard** when the wizard was opened from the dashboard), calling the existing origin-aware `goOrigin()`. Before the import the step keeps Back (to step 2 / origin) + Import, unchanged.

- Files touched: `app/api/routes.py`, `static/js/app.js`, `templates/trash.html`, `templates/import.html`, `PROJECT.md`, `CHANGELOG.md`.
- Verified: dev server + API probes (`QA/qa_trash_probe.py`): created 3 objects on a demo firewall, soft-deleted them, `GET /api/trash?project_id=` listed all 3; `POST /api/trash/permanent-delete` with 2 of the 3 trash ids → 200 + `deleted: 2`, DB rows for the objects / their history / their trash entries gone, names freed (re-create with the same name succeeds); the 3rd object + its history survived; `all: true` then removed the last one; error paths 400 (empty body, `all` without `project_id`, ids already deleted). Headless browser: `/trash?project_id=1` — all objects displayed (previously zero rows), search "address" filters to the matching rows and a bogus term shows the "no match" empty state; header checkbox selects the filtered rows, "Delete selected (2)" confirms and the list shrinks to 1, "Delete all (1)" empties the trash (empty state shown); console clean (only the documented Tailwind CDN warning). `/import?project_id=1&firewall_id=N` with a small FortiGate config upload — after the import the result panel shows and the action row offers **Back to project** (no "Import again"); from `/import` without `project_id` the label is **Back to dashboard**. Demo database restored afterwards (test objects + trash entries removed, no committed changes to demo data).

---

## 2026-12-16

**Object list: status filter (included / modified / deleted), pulsing glow on the Validate button, Export button removed — and the project page's "Manage firewalls" table now counts deleted objects too:**

*Feature — status filter on the object list page (`filter` parameter + dropdown):*
- `app/api/routes.py`: `GET /api/objects` accepts a new `filter` parameter — `included` (active objects tagged "Include in the export"), `modified` (objects with at least one `update` entry in the modification history), `deleted` (soft-deleted objects; the list always requests `include_deleted=true`, this narrows the scope to them). Unknown values are ignored.
- `static/js/app.js`: `objectTable()` gains a `statusFilter` state ("all" / "included" / "modified" / "deleted"); `load()` passes it as `?filter=`.
- `templates/objects.html`: a filter dropdown in the toolbar (after the search input) — "All objects / Included in the export / Modified / Deleted" — resets to page 1 on change.

*Feature — Validate button reminder glow:*
- `templates/objects.html`: the toolbar Validate button gets the `validate-attention` class while `pending.length > 0 && !committing`.
- `templates/base.html`: `.validate-attention` = soft pulsing green glow (`validateGlow` keyframes, 2.2 s); static glow under `prefers-reduced-motion: reduce`.

*Refactor — Export button removed from the object list page:*
- `templates/objects.html`: the conditional Export button below the table is gone (exporting stays available from the project page's "Export configuration" section and the export page).

*Feature — deleted count in the "Manage firewalls" table (project page):*
- `app/views.py`: `_project_stats()` adds per-firewall/per-type `deleted` counts + `deleted_total` (same pattern as the `modified` counts; the `modified` counts keep their "active only" definition, so a deleted+modified object is counted as deleted).
- `templates/project.html`: the Manage firewalls table's Objects cell shows a red "(N deleted)" span next to the orange "(N modified)" span, only when N > 0.

- Files touched: `app/api/routes.py`, `app/views.py`, `templates/objects.html`, `templates/project.html`, `templates/base.html`, `static/js/app.js`, `PROJECT.md`, `CHANGELOG.md`.
- Verified: `QA/qa_filter_probe.py` (11 assertions on `GET /api/objects` — per-type deleted/modified/included totals match the DB ground truth from `QA/qa_type_counts.py`; filter combined with `search`; unknown filter ignored; the deleted+modified object appears under "modified") + headless browser: `/objects?project_id=1&firewall_id=1&object_type=address` — the dropdown filters correctly (1 deleted row greyed out with badge + Restore, 1 modified, 0 included → "No objects found"); `/objects?project_id=3&firewall_id=5` — "Included" shows exactly the 7 tagged rows; staging a new object makes the Validate button gain `validate-attention` (CSS rule verified via CSSOM) and the "1 staged" badge appears, then both return to the clean state after Discard; no Export button on the object page; `/projects/1` — the Manage firewalls table shows FGT-600E with "(2 modified)" + "(2 deleted)"; console clean (only the documented Tailwind CDN warning). Demo database left untouched (staged change discarded, no committed changes).

---

## 2026-11-26

**Import wizard: back navigation to the origin page, Select all / Clear shortcuts, import history + replace-the-previous-import semantics — and the object trash gains a search box:**

*Feature — import wizard back navigation (project page / dashboard):*
- `templates/import.html`: the header back link is now context-aware — "← Dashboard" by default, "← <project name>" when the page was opened with `?project_id=` (the per-row Import action on the project page, which now carries `project_id` — `templates/project.html`). Step 1 gains a **Back** button (`goOrigin()` → dashboard or project page); step 2's **Back** leaves the wizard for the origin page when the firewall was preselected via URL (else it goes back to step 1); step 3 keeps going back to step 2.
- `app/views.py`: `import_page()` reads `?project_id=` and passes the project to the template (a trashed/unknown id falls back to the dashboard context); `static/js/app.js` `importWizard(firewalls, projectId)` gains `projectId`, `goOrigin()` and the origin-aware `back()`.

*Feature — Select all / Clear on the import source & types step (same style as the export wizard):*
- `templates/import.html`: the "Object types" block now carries the **Select all** / **Clear** link row with the exact markup of the export wizard's type step (`class="link"`, `padding: 0`, Clear in `var(--color-ink-muted)`), above the checkbox grid.
- `static/js/app.js`: `importWizard()` gains `selectAllTypes()` / `clearAllTypes()`.

*Feature — import history + a new import replaces the previous one:*
- `app/models.py`: new `ImportRecord` model (one row per import run: firewall, source_type, source_name, object_count, counts, warnings, user, created_at — `firewall_id` SET NULL so history survives firewall deletion) + `ConfigObject.import_id` (the import run that created the object; NULL for manual objects) + `import_record` relationship.
- `app/factory.py`: one-off migration `_ensure_config_objects_import_id()` (nullable `import_id` column on `config_objects`; the `import_records` table itself is created by `db.create_all()`).
- `app/api/routes.py`: `_delete_previous_import()` deletes the firewall's latest import's objects (modification history + trash rows via ORM cascade) before a new import — manually created objects (no `import_id`) are untouched; `POST /api/import` and `POST /api/import/stream` create the `ImportRecord`, tag the imported objects with it and answer `replaced` + `import_record`; new `GET /api/import/records?firewall_id=N` (newest first, limit 20).
- `templates/import.html` + `static/js/app.js`: the source & types step shows the **Import history** panel of the selected firewall (date, source file/URL, object count, per-type summary; loaded on init + firewall change + after a successful import) with the note "Importing replaces the previous import of this firewall: its objects are removed before the new configuration is applied"; the success panel confirms "Previous import removed: N objects."; the review note documents the replace semantics. The firewall wizard's import step (`/api/import/stream`) gets the same semantics automatically.

*Feature — search in the object trash:*
- `templates/trash.html`: the Objects section (project trash can) gains a search input (`class="input"`, right-aligned in the card head) filtering the deleted objects client-side by name / type / firewall / project / reason, with a "No objects in the trash match “…”" empty state.
- `static/js/app.js`: `trashBin()` gains `search` + `filteredItems()`; the table iterates `filteredItems` instead of `items`.

*Housekeeping — `files/` gitignored:*
- `.gitignore`: new `files/` entry (reference sample configurations, multi-MB, searched via the Vector DB only). The four already-tracked samples stay tracked — `git rm --cached files/` is needed to untrack them; they remain on disk as reference samples.

- Files touched: `.gitignore`, `app/models.py`, `app/factory.py`, `app/api/routes.py`, `app/views.py`, `templates/import.html`, `templates/trash.html`, `templates/project.html`, `static/js/app.js`, `PROJECT.md`, `CHANGELOG.md`.
- Verified: `QA/qa_import_roundtrip.py` (import sample config into a QA firewall twice — the second import removes the first import's objects, keeps manually created ones, and the history lists both runs newest first; `GET /api/import/records` scoped + unscoped; manual objects survive a re-import) + headless browser: `/import` header "← Dashboard" with step-1 Back → dashboard; `/import?firewall_id=…&project_id=1` header "← <project>" with step-2 Back → project page; Select all / Clear toggle the type checkboxes (same link look as the export wizard); import history panel shows the previous run and refreshes after a new import with the "Previous import removed: N objects" line; `/trash?project_id=1` search box filters the deleted objects (match + no-match states). Demo database restored afterwards (QA rows removed).

---

## 2026-11-25

**UI rework — proportions without overlap + a proper alert system (icons, accent bars, tints):**

*Fix — stat cards: label/icon collision removed by reworking the card proportions:*
- `templates/base.html`: `.stat-card` is now a flex column with a `.stat-card-head` row (label left, icon right, value below) — the icon was previously `position: absolute` top-right and collided with the label text on every card at every width (measured ≈ 30 px overlap, e.g. “Attached Firewalls” / “Imported Objects” ran under the icon on the project page). The icon chip gets an accent tint (`--color-accent-light` background, `--color-accent` glyph), `.stat-label` gains `min-width: 0; overflow-wrap: anywhere` so it wraps instead of colliding, `.stat-value-sm` tightens its top margin for the new head row.
- `templates/index.html`, `templates/project.html`: all 8 stat cards (3 dashboard + 5 project) rebuilt to the head-row structure.

*Fix — section heads wrap on narrow screens (no more title/button collision):*
- `templates/base.html`: `.section-head` gains `flex-wrap: wrap` — at 390 px the project page’s “Export configuration” section head overlapped: the squeezed title box (word “configuration” can’t break) and the `flex-shrink: 0` Export Configuration button collided (measured 462 px² overlap). The actions now drop onto their own row under the title on narrow screens; desktop is unchanged.

*Fix — wizard forms: invisible active step + invisible progress fill:*
- `templates/_firewall_wizard.html`, `templates/_project_wizard.html`: the step indicator now uses the design-system `.step-indicator` / `.step-dot` classes (active = accent, done = green, inactive = muted) with the step state bound via `:class` arrays. The old pills used `bg-primary-500`, which is **not in the Tailwind config** — the active step rendered as white text on a transparent background (invisible). The firewall wizard’s progress fill used the same undefined class (invisible progress bar) and now uses `.progress-bar` / `.progress-fill`.
- `templates/_project_wizard.html`: the selected-firewall highlight in step 2 now uses `border-blue-700 bg-blue-50` (the old `ring-2 ring-primary-500` rendered no ring at all).

*Feature — alert (flash) system redesigned to be more pleasing to the eye:*
- `templates/base.html`: the `.flash` alerts are rebuilt — each variant draws an inline SVG icon via `::before` (check-circle / ×-circle / alert-triangle / info-circle, so call sites stay plain text), carries a **4 px left accent bar** in the variant colour (success `#059669`, error `#dc2626`, warning `#d97706`, info `#2563eb`), a soft tint, a light shadow, `line-height: 1.55` and `overflow-wrap: anywhere`. Both server flash messages and the Alpine inline alerts pick the look up automatically.
- Inline wizard alerts normalized from `flash-error rounded-lg px-4 py-3 text-sm` (no base class) to `flash flash-error`: `_firewall_wizard.html` (import error, 2× step error), `_project_wizard.html` (2× step error, submit error), `_firewall_edit.html` (load/save error).
- Hand-rolled info/success/warning boxes converted to the alert system: `project.html` (pre-export hint + “no firewalls” note → `flash flash-info`), `_firewall_wizard.html` (import success panel → `flash flash-success`), `_project_wizard.html` (“no firewall” note → `flash flash-warning`), `export.html` (file result + success panels → `flash flash-success`).

- Files touched: `templates/base.html`, `templates/index.html`, `templates/project.html`, `templates/_firewall_wizard.html`, `templates/_project_wizard.html`, `templates/_firewall_edit.html`, `templates/export.html`, `PROJECT.md`, `CHANGELOG.md`.
- Verified: headless browser — automated overlap + horizontal-overflow probe (in-page iframes with real 390/768/1280 px viewports, modal overlays excluded) over all 8 pages: **0 overlaps, 0 horizontal overflow** after the change (before: stat-icon/label collisions on the dashboard + project page at every width; section-title/button collision on the project page at 390 px). Screenshots: dashboard + project stat cards (1440), mobile 390 (hero, stats single-column, Export section head with the button wrapped under the title, wizard modal), wizard step dots visible (active blue / done green), progress fill visible at 45 %, error + success alerts with icon + accent bar (objects page + firewall wizard step 1 validation). Console clean (only the documented Tailwind CDN warning). No backend changes; demo database untouched.

---

**Import page fixed: the standalone import wizard now actually imports (it previously was a plain HTML form POSTing to the GET-only page route → 405 “Method Not Allowed”):**

*Bug fix — broken import page (`/import`):*
- `templates/import.html`: the page was a stale pre-Alpine `<form method="POST">` whose action was the page's own route (`views.import_page`, `GET /import` only) — clicking **Import** hit Werkzeug's 405 “Method Not Allowed — The method is not allowed for the requested URL.” and the upload never reached the API. Replaced with the standalone 3-step wizard documented in `PROJECT.md` (firewall → source & types → review), wired to the existing `importWizard()` Alpine component: firewall select (JSON from the view), file upload (`x-ref="fileInput"`) or remote URL, per-type checkboxes (`toggleType`), a review summary (firewall / source / selected types), the **Import** button → `POST /api/import` (FormData), a success panel with per-type count chips + parser warnings + a **View objects** link, and an **Import again** action; empty state when no firewall exists.
- `static/js/app.js`: `importWizard(firewalls)` now receives the firewall list (id/name/vendor/model) from the view and adds `types` (the full 9-type list for the checkbox grid), `busy` (button disabled while the import is in flight, “Importing...” label), `fileName` + `setFileName()` (the chosen file is shown in the review) and `firewall()` (resolves the selected firewall for the review summary). `submitImport()` validates the URL field, always clears `busy` (`finally`), and parses the JSON answer defensively — a non-JSON error body (like the old 405 HTML page) now yields “Import failed (HTTP 405).” instead of a JSON parse error.
- `app/views.py`: `import_page()` passes a JSON-safe `firewalls_json` (id/name/vendor/model, `<` escaped like `export_page` — the `x-data` attribute is single-quoted) and its docstring documents that the page is GET-only while the wizard POSTs to `/api/import`.

- Files touched: `templates/import.html`, `static/js/app.js`, `app/views.py`, `CHANGELOG.md`.
- Verified: `QA/probe_import.py` — `GET /import` → 200 rendering the wizard (no `<form>` left), `GET /import?firewall_id=3` → 200 (deep link), `GET /api/import` → 405 (expected for the API; the UI no longer sends GET there), `POST /api/import` file uploads with the real reference samples → 200 (FortiGate `.conf` into FGT-30E: 1198 objects; PAN-OS `.xml` into Demo-PA-3410: 4111 objects); headless browser — the wizard walked end to end in the UI (FGT-30E selected, file chosen, review shows “File — qa-test.conf”, **Import** → `POST /api/import` → green success panel “Imported 2 objects.” with type chips, parser warnings, **View objects** + **Import again**; screenshot taken); console clean (only the documented Tailwind CDN warning). Demo database restored afterwards (`QA/cleanup_import_round.py`: the two demo firewalls were empty before the round — all verification objects + history rows removed, `last_sync_at` cleared).

**Trash separated: the dashboard trash lists projects + firewalls only, each project's trash can lists that project's deleted objects only:**

*Feature — two separate trashes (dashboard trash / per-project trash can):*
- `app/api/routes.py`: `GET /api/trash` without a scope (the dashboard trash) now
  returns only deleted projects and firewalls — object entries are skipped and
  `items` stays empty; with `?project_id=N` (the project trash can) it returns
  only that project's deleted objects, as before. Docstring updated.
- `templates/trash.html`: the **Objects** section is now rendered only in the
  scoped (project trash can) view (`x-show="projectId"`); the dashboard view
  shows the Projects and Firewalls sections only; the dashboard hero subtitle
  now states that deleted objects live in the trash can of their project.
- `static/js/app.js`: `trashBin()` loads `items` only when a project id is
  passed; the component's header comment now describes the two separate trashes.
- `app/views.py`: `trash_page` docstring updated.

- Files touched: `app/api/routes.py`, `app/views.py`, `templates/trash.html`,
  `static/js/app.js`, `PROJECT.md`, `CHANGELOG.md`.
- Verified: `QA/qa_trash_split.py` (stage A: 18 API assertions — temporary QA
  firewall round trip through the dashboard trash, QA object soft-delete,
  dashboard `GET /api/trash` → `items` empty, `GET /api/trash?project_id=1` →
  that project's deleted objects only with no project/firewall entries;
  stage B: 3 assertions + full cleanup of the QA rows) + headless browser —
  `/trash` shows only the Projects and Firewalls sections (Objects section
  hidden) with a deleted project + firewall row and Restore buttons;
  `/trash?project_id=1` shows only the Objects section with the project's
  deleted objects, and clicking **Restore** on the QA object row removed it
  from the list (the user-deleted demo objects were left untouched). Demo
  database state restored afterwards.

**Object list page: project trash-can icon in the header, no Trash in the nav bar (project-scoped views):**

*Feature — the project trash can moves onto the object list page:*
- `templates/objects.html`: when the list is scoped by a project
  (`?project_id=`), the page header now shows the project **trash-can icon
  button** (the same markup as the project page hero, → `/trash?project_id=<id>`),
  and the nav bar drops **Trash** — it uses the same conditional partial as the
  project pages (`_project_nav.html`: Dashboard / Objects). Non-project-scoped
  views keep the default nav bar (Dashboard / Trash) and no trash-can icon.

- Files touched: `templates/objects.html`, `PROJECT.md`, `CHANGELOG.md`.
- Verified: headless browser — `/objects?project_id=1&firewall_id=1&object_type=address`
  shows a nav bar with only Dashboard / Objects (no Trash) and the trash-can icon
  in the header; clicking it opens the project trash can (`/trash?project_id=1`,
  Objects section only); `/objects` (unscoped) keeps the Dashboard / Trash nav bar
  and no trash-can icon.

---

## 2026-11-26

**Trash: deleted projects and firewalls are restorable (per-type sections), project trash can, greyed-out deleted objects with Restore:**

*Feature — projects/firewalls go to the Trash instead of being hard-deleted:*
- `app/models.py`: `Project` and `Firewall` gain `is_deleted` + `deleted_at` and a
  `trash_record` relation; `soft_delete()` / `restore()` mirror the existing
  `ConfigObject` pattern. Deleting a project cascades into the trash: its
  attached firewalls (as `firewall` trash entries) and, for each firewall, every
  object individually (as `object` trash entries with the reason
  "Firewall '<name>' deleted"). `restore()` brings the descendants back with it.
- `app/models.py`: the `Trash` model is generalized — new `item_type` column
  ("object" | "project" | "firewall"), nullable `config_object_id`, new
  `project_id` / `firewall_id` columns + relationships.
- `app/factory.py`: two one-off migrations for existing databases —
  `is_deleted`/`deleted_at` added to `projects`/`firewalls` (ALTER TABLE) and
  the `trash` table rebuilt with the new columns (existing rows backfilled as
  `item_type = 'object'`).
- `app/views.py`: `POST /projects/<id>/delete` and `POST /firewalls/<id>/delete`
  now soft-delete (flash: "moved to the trash — restore it from the Trash
  page"); a project in the trash answers 404 on its page; trashed projects /
  firewalls are excluded from the dashboard lists, the project stats, the
  attachable list, the import wizard and the object-list scope (a trashed
  scope is treated as "no scope"); attach/create/patch flows reject targets
  that are in the trash with a friendly message.
- `app/api/routes.py`: `GET /api/projects` + `GET /api/firewalls` filter out
  deleted entries; `POST /api/projects` (attach) and `POST /api/firewalls` /
  `PATCH /api/firewalls/<id>` reject trash-reserved names; the project payload
  lists only active firewalls.

*Feature — `GET /api/trash` now returns the list per type + project scoping:*
- Response shape: `{projects: [...], firewalls: [...], items: [...objects]}` —
  projects carry name/description/firewall_count/object_count, firewalls carry
  name/vendor/model/project/object_count, objects carry name/type/firewall/
  project + the full serialized object (the previous response only had an
  `object` sub-object, which the old template never read — its Name/Type/
  Firewall columns rendered blank).
- `?project_id=N` scopes the response to that project's deleted objects (the
  project trash can); `POST /api/trash/<id>/restore` is generalized to
  object/project/firewall entries (cascade included) with a friendly error
  when an active entry already holds the name.
- `POST /api/objects/<id>/restore` (new): restores a single object from the
  trash — the Restore button of the object list page.

*UI — `templates/trash.html` rewritten with the section system:*
- Three labeled sections — **Projects**, **Firewalls**, **Objects** — each with
  its own table, empty state and Restore buttons; the header/subtitle adapts
  to the scope. With `?project_id=` only the Objects section is shown ("Trash
  — <project>", back link to the project page).
- `static/js/app.js` `trashBin(projectId)`: loads the three groups (scoped
  URL when a project is passed), one `restore(kind, trashId, label)` with a
  confirm and a busy state; the old dead "Delete" button (it called a
  `deleteForever` method that never existed) is gone — restore only.
- `templates/project.html`: the hero gains a **trash-can icon button**
  (next to "Edit Project") linking to `/trash?project_id=<id>` — the trash
  can for the objects tied to the project.

*UI — object list: deleted objects are greyed out and restorable in place:*
- `static/js/app.js` `objectTable()`: the list now always requests
  `include_deleted=true`; deleted rows render greyed out (`table-row-deleted`,
  new CSS in `base.html` — opacity 0.55) with a red **deleted** badge;
  their Modify/Delete buttons are replaced by a single **Restore** button
  (`restoreRow()` → `POST /api/objects/<id>/restore`, immediate — no staging);
  deleted rows cannot be opened for editing ("Restore it first") nor tagged
  for the export (checkbox disabled, excluded from `selectableRows`).
- `templates/objects.html`: row class binding, badges, button swap, disabled
  checkbox for deleted rows, "in export" badge hidden on deleted rows.

*Cleanup — Manage firewalls (project page):*
- The per-row **Edit** link is removed from the "Manage firewalls" table
  (rows keep Import / Objects / Remove); the `?edit=<id>` deep link on
  `/firewalls` stays as-is for the firewall dashboard cards.
- Delete confirmations (dashboard + firewalls page) now say "Move … to the
  trash?" and the project/firewall name stays reserved while the entry is in
  the trash (no permanent delete yet) — create/rename attempts get a
  trash-aware error instead of a generic constraint message.

- Files touched: `app/models.py`, `app/factory.py`, `app/views.py`,
  `app/api/routes.py`, `templates/project.html`, `templates/trash.html`,
  `templates/objects.html`, `templates/base.html`, `static/js/app.js`,
  `PROJECT.md`, `CHANGELOG.md`.
- Verified: `QA/qa_trash_lifecycle.py` (43 API assertions: create → trash →
  per-type listing → cascade restore → name reservation → object delete/
  restore round trip, full cleanup) + headless browser — trash page sections
  (empty + with a deleted firewall, Restore click), project hero trash can,
  Manage firewalls without Edit link, project-scoped trash, and the object
  list round trip (add → stage delete → Validate → greyed-out row with
  deleted badge + Restore → click Restore → row active again). All QA test
  rows were removed from the database afterwards.

**Complete UI-UX redesign using UI/UX Pro Max skill:**
- Redesigned all templates with a consistent Flat Design system: new purple
  primary color (#7C3AED), orange CTA accent (#F97316), and surface tint (#FAF5FF).
- Added Google Fonts: Fira Sans (body) and Fira Code (monospace) for a
  technical, precise dashboard aesthetic.
- Replaced Font Awesome with inline SVG icons for consistency and performance.
- Introduced reusable CSS utility classes in `base.html`: `.btn`, `.badge`,
  `.card`, `.input`, `.table-header`, `.flash-*`, `.modal-*`, `.stat-card`,
  `.empty-state`, `.btn-link`, `.btn-ghost`, `.btn-danger`, `.btn-success`,
  `.btn-secondary`, `.btn-accent`, `.btn-primary`.
- Updated all 14 templates: `base.html`, `index.html`, `project.html`,
  `firewalls.html`, `objects.html`, `export.html`, `import.html`,
  `projects.html`, `project_edit.html`, `trash.html`, `_project_wizard.html`,
  `_firewall_wizard.html`, `_firewall_edit.html`, `_project_nav.html`.
- Removed unnecessary box shadows (flat design), standardized border radii,
  and unified transition durations (150ms for hover, 300ms for progress).
- Improved form layouts with consistent input styling, focus rings, and labels.
- Created `DESIGN.md` documenting the complete design system (colors, typography,
  components, spacing, accessibility, Tailwind config).
- Files touched: all templates in `templates/`, new `DESIGN.md`.
- Verified: all templates use the new utility classes consistently; design system
  documentation is complete and accurate.

---

## 2026-11-25

**Documentation — strict `QA/`-only rule for every created test file and generated log:**
- `PROJECT.md` §3 (background dev server recipe): the launcher is now created as
  `QA\_run_server.bat` and the redirect logs go to `QA\_server_log.txt` /
  `QA\_server_err.txt` (updated `Start-Process` example with the absolute `QA/`
  paths); the cleanup step deletes the temporary files from `QA/` and notes they
  are disposable test-round artifacts.
- `PROJECT.md` §8 rule 7 + §9 rule 1 reworded: **every created test file and
  generated log (test scripts, run/redirect logs, launcher files, dumps,
  screenshots, API probes) MUST strictly live in `QA/`** — never at the
  repository root or inside `app/`, `templates/`, `static/` or `files/`;
  the §9 file list now explicitly includes the background dev server's launcher
  + redirect logs, and the typical-scripts table names `QA\_run_server.bat`.
- `PROJECT.md` §2 layout tree: `QA/` documented as the strict location for
  every test file and generated log.
- Files touched: `PROJECT.md`, `CHANGELOG.md`.
- Verified: `findstr` sweep — every `_run_server*` / `_server_*.txt` reference
  in `PROJECT.md` now points to `QA/`; no root-level temp-file references left.

---

**Feature — project page: export section with the previous generated / pushed files; navbars slimmed:**
- `templates/base.html`: **Firewalls link removed from the top bar** (Dashboard / Trash remain);
  new `.entrance-delay-4` delay class for the fourth staggered section.
- `templates/_project_nav.html`: **Export link removed** — the project page top bar is now
  **Dashboard / Objects** only; the Dashboard link appears **in the top bar only** (the hero's
  "← Back to Dashboard" was removed from `project.html`).
- `templates/project.html`: a blue **pre-export hint above Statistics** — "You can modify,
  adjust, select or remove objects on the object list pages before exporting the configuration
  selectively"; the **Export Configuration button moved** from the Manage firewalls section head
  to a **new LAST section "Export configuration"** (kicker "Delivery") which also **lists the
  previous generated or pushed configuration files** of the project (File / Pushed badge,
  destination, objects per type, size, UTC date) **with a Download button each** ("not on disk"
  badge when the stored file is gone).
- `app/models.py`: new **`ExportRecord`** model (`export_records` table — project_id /
  firewall_id ON DELETE SET NULL, method file|push, destination name, filename, file_path,
  object_count, per-type counts JSON, size, user, created_at).
- `app/api/routes.py`: `_exports_dir()` + **`_record_export()`** — every generated
  (`POST /api/export/file`, legacy `POST /api/export` download) or pushed
  (`POST /api/export/push`, legacy push mode) configuration is persisted to
  `instance/exports/<id>_<filename>` + an `export_records` row (best-effort, a failure never
  breaks the export); the push stream captures `current_user()` before the request context is
  gone (the stream runs in a fresh app context).
- `app/views.py`: `project_detail` builds the export list (newest first, on-disk check, human
  sizes) for the new section; new route **`GET /projects/<id>/exports/<rid>/download`** serves
  the stored file as an attachment (flash + redirect when it is no longer on disk).
- `.gitignore`: `instance/exports/` ignored (local artifacts, like the DB file).
- Files touched: `app/models.py`, `app/views.py`, `app/api/routes.py`, `templates/base.html`,
  `templates/_project_nav.html`, `templates/project.html`, `.gitignore`, `PROJECT.md`,
  `CHANGELOG.md`.
- Verified: headless browser — dashboard top bar = Dashboard/Trash; project top bar =
  Dashboard/Objects; hero without the back link; hint above Statistics; "Export configuration"
  is the last section with the file table; + `QA/qa_export_records.py` — file + push round trip,
  all record download links + the temporary token link answer 200 with attachment disposition,
  record counts match the requests (587 addresses pushed; 717 address+service file).

---

**Follow-up on the dashboard/project rework — more obvious section separation:**
- `templates/base.html`: `.section` now renders as a surface slab —
  `background: var(--color-surface-sunken)`, 1px border, `var(--radius-lg)`
  corners, 2rem inner padding (1.25rem on mobile) — so every section reads as
  its own block on the white page; white cards contrast crisply against the
  slab. Section gap widened 3rem → 3.5rem (2.5rem on mobile).
- `templates/project.html`: the "All firewalls" type-chip panel switched from
  sunken to white (`--color-surface-raised`) so it stands out on the new slab
  background.
- Files touched: `templates/base.html`, `templates/project.html`,
  `PROJECT.md`, `CHANGELOG.md`.
- Verified: headless browser at 1440 — dashboard (3 slabs) and project page
  (3 slabs) show clear separation between sections; cards, chips, table and
  attach footer all contrast correctly against the slab.

---

**Follow-up on the dashboard/project rework — section numbering removed;
project description moved under the project name:**
- `templates/base.html`: dropped the `.section-index` chip style; `.section-head-main`
  is now a plain text column (kicker + title + sub).
- `templates/index.html`: the `01/02/03` index chips are gone from the Statistics /
  Projects / Firewalls section heads (kickers, titles, subs unchanged).
- `templates/project.html`: the Description section is removed — the description now
  sits below the project name in the page hero (`No description` fallback); the
  Edit Project button moved to the hero; index chips removed from the Statistics /
  Firewalls / Manage firewalls heads.
- Files touched: `templates/base.html`, `templates/index.html`,
  `templates/project.html`, `PROJECT.md`, `CHANGELOG.md`.
- Verified: headless browser — dashboard + project page render at 1440 (no chips;
  description under the project name; Edit Project in the hero).

---

**Dashboard + project page rework — distinguishable sections and new
proportions (taste-skill 2.5, anti-slop principles):**
- `templates/base.html`: new section system — `.section` + ruled `.section-head`
  (`.section-index` monospace chip, `.section-kicker` uppercase label,
  `.section-title` 1.375rem 700, optional `.section-sub`,
  `.section-head-actions`) and `.page-hero` / `.page-hero-title` (2.625rem,
  -0.025em) / `.page-hero-sub` — a stronger type scale and a clear band per
  section on every page. Global `section { padding: 4rem 1.5rem }` removed
  (it double-inset the dashboard sections inside the already-padded container
  and bloated the wizard modal steps) → `section { padding: 0 }`.
  `.modal-content` now carries 1.75rem of internal padding (previously none —
  modal content touched the modal edges). Stat cards enlarged (padding 1.5rem,
  value 2.25rem with tabular-nums, new `.stat-icon` chip, new `.stat-value-sm`
  monospace style for date values). Mobile (<768px): the header row wraps
  (`.header-row`) and nav links shrink — removes the only page-level horizontal
  overflow at 390px.
- `templates/index.html` (dashboard): rebuilt as three labeled sections —
  **01 Statistics** (icon stat cards), **02 Projects** (card grid),
  **03 Firewalls** (card grid); the hero carries the two main actions
  (New Project / New Firewall); section heads carry the "Full list →" links.
  All Alpine bindings unchanged (`dashboard()`).
- `templates/project.html`: rebuilt as four labeled sections —
  **01 Description** (description card; Edit Project moved into the section
  head), **02 Statistics** (icon stat cards; Last Import as monospace
  `stat-value-sm`), **03 Firewalls** ("All firewalls" type-chip panel + one
  card per firewall in an `auto-fill, minmax(min(430px, 100%), 1fr)` grid —
  the `min()` guard prevents overflow below 430px; "Total: N →" links are
  nowrap), **04 Manage firewalls** (renamed from "Attached Firewalls") —
  firewall table + "Attach existing firewall" footer; the Export Configuration
  button now sits in the section head instead of a lone row at the page bottom.
- `templates/_project_nav.html`: project-page nav links moved onto the shared
  `.nav-link` class (they used `primary-*` Tailwind classes that are not in
  the Tailwind config — dead hover/active states).
- No backend or `static/js/app.js` changes.
- Files touched: `templates/base.html`, `templates/index.html`,
  `templates/project.html`, `templates/_project_nav.html`, `PROJECT.md`,
  `CHANGELOG.md`.
- Verified: headless-browser pass — dashboard 1440; project page 1440 (all 4
  sections, Export in the 04 head) + 390 width probe (zero page-level
  overflow; the wide table scrolls inside its own `.table-container`);
  wizard + edit modals padded correctly; export / firewalls / projects /
  trash pages render unchanged. The demo DB was re-seeded mid-session
  (FGT-30E / FGT-600E, 1199 objects) — the new layout adapted correctly.

---

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

**`.gitignore`: ignore the local SQLite database:**
- Added `instance/swissknife.db` to `.gitignore` (new "# Local SQLite
  database" section) — the DB is auto-created + migrated at startup and
  seeded with demo data, so it is not part of the repository; the §2 tree
  comment for `.gitignore` updated accordingly.
- Files touched: `.gitignore`, `PROJECT.md`, `CHANGELOG.md`.
- Verified: `.gitignore` now lists `instance/swissknife.db`.

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
