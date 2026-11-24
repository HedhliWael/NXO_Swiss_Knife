# NXO Swiss Knife — Project Documentation

> **Living document.** This file is consulted and updated as long as the project
> is in development. Every change, new feature, or fix should be recorded in
> `CHANGELOG.md` (see [Maintenance rules](#8-maintenance-rules)).
>
> **Priority for LLM-assisted work — query the Vector DB BEFORE reading any
> file of this repository.** Use the companion **Vector_DB** store to retrieve
> context (`C:\Users\hedhl\source\repos\Vector_DB`; usage is documented in its
> `README.md`, workflow in [§7](#7-vector-db-integration-token-efficient-development))
> to reduce token consumption. **Direct file reading is NOT allowed until the
> Vector DB query has returned no useful information** (0 relevant chunks, or
> chunks that do not answer the question). **Querying the Vector DB is
> MANDATORY before every file read** — no exception for "exact current
> content" or precise edits: query the store first, and only then read the
> file directly.

---

## 1. Description

**NXO Swiss Knife** is a local, multi-project web tool for managing firewall
configuration objects (currently **Palo Alto** and **Fortinet**).

It is organized around three levels:

- **Projects** — containers grouping the work of a team/customer.
- **Firewalls** — belong to a project, each with a vendor, a management IP and
  optional API credentials.
- **Configuration objects** — imported from firewall configuration files
  (addresses, address groups, services, service groups, security rules,
  interfaces, zones). Objects are normalized into a JSON `payload`,
  fingerprinted, and tracked with a full modification history.

Core capabilities:

- **Three-step web flow**: 1) **Dashboard** (exhaustive lists of projects and
  firewalls), 2) **Project view** (statistics, per-firewall/per-type object
  counts — clicking a count opens the filtered object list with modify /
  delete / add actions, staged changes committed by a **Validate** button),
  3) **Export** (subset or full object set to a chosen attached firewall, as a
  vendor-specific config file or an API push).
- **Multi-step wizards** (client-side, Alpine + API):
  - *Firewall* (3 steps): basic data (name, vendor, **model**, management IP,
    **login/password or API-token** authentication, description) → import
    configuration (file upload or REST API, **Check connectivity** button,
    progress bars for upload and streaming REST retrieval) → create, with
    the option to **skip the import**. If the import fails (e.g. no file
    chosen), a **Back** button returns to step 2 and the step-3 button
    becomes **Import configuration** — the already-created firewall is
    re-imported, never re-created.
  - *Project* (3 steps): name + description → attach **existing** firewalls
    (any firewall — also without an imported configuration; "create a
    firewall first" suggestion when none exist) → validation summary, then the
    new project page opens immediately.
- Import configurations from **file upload** or **remote URL** with
  vendor-specific parsers.
  Accepted file types — reference samples of each are in
  [`files/`](#2-architecture--layout):
  FortiGate full CLI config (`.conf`), Palo Alto PAN-OS XML export
  (`.xml`, minified or pretty-printed) and Palo Alto export in set/
  `show` format (`.txt`).
- **Upsert** semantics: objects are created/updated per
  `(firewall, object_type, name)`; changes are written to
  `modification_history`.
- **Staged edits + Validate**: object edits/deletes/creates are staged
  client-side and committed atomically by `POST /api/objects/commit`.
- **Trash**: soft delete with reason, restore support.
- **Export**: generate vendor configuration text (temporary download link) or
  push it with streaming progress (currently a mock push).
- REST **API** (`/api/...`) plus a browser UI (Alpine.js + Tailwind CDN).

### Stack

| Layer | Technology |
|---|---|
| Web framework | Flask 2.3.3 |
| ORM / DB | Flask-SQLAlchemy 3.0.5, SQLAlchemy 2.1.9, SQLite (`instance/swissknife.db`) |
| Forms / CSRF | Flask-WTF 1.1.1, WTForms 3.0.1 |
| Frontend JS | Alpine.js (CDN, v3) |
| Styling | Tailwind CSS (CDN build — dev only) |
| Misc | python-dotenv, requests |
| Companion RAG project | **Vector_DB** (sibling repo `C:\Users\hedhl\source\repos\Vector_DB`) — ChromaDB + Ollama `nomic-embed-text`, token-efficient context retrieval; see [§7](#7-vector-db-integration-token-efficient-development) |

Python: 3.13 (`.venv` in the repository root).

---

## 2. Architecture & layout

```
NXO_Swiss_Knife/
├── app/
│   ├── factory.py          # create_app() — Flask factory, db.create_all() + one-off migrations
│   │                       #   (firewalls.project_id nullable, firewall auth columns,
│   │                       #   config_objects.project_id nullable)
│   ├── extensions.py       # db = SQLAlchemy()
│   ├── models.py           # Project, Firewall (project_id nullable = can be unassigned;
│   │                       #   model, auth_mode password|token, api_token; set_project()
│   │                       #   keeps object project_ids in sync), ConfigObject
│   │                       #   (project_id nullable), ModificationHistory, Trash
│   ├── views.py            # Web UI routes (dashboard, project pages w/ per-firewall/per-type
│   │                       #   stats, attach/remove firewall, import, objects w/ type-specific
│   │                       #   columns, export w/ stats, trash)
│   ├── api/routes.py       # REST API (projects + attach, firewalls + detail/update
│   │                       #   GET/POST/PATCH /api/firewalls/<id>, import + /import/stream
│   │                       #   NDJSON progress, /connectivity, objects CRUD + /objects/commit
│   │                       #   batch validate, trash, /export/file + download, /export/push
│   │                       #   streaming, auth placeholder)
│   ├── errors.py           # API exception types
│   ├── forms/              # ProjectForm (used by the project edit page)
│   └── vendors/            # base.py, factory.py (parser registry), paloalto.py, fortinet.py
├── templates/
│   ├── base.html           # Layout + navbar (Dashboard / Firewalls / Objects / Trash,
│   │                       #   block `nav`) + scripts (app.js BEFORE Alpine, loaded with a
│   │                       #   ?v= cache-buster — Jinja global `app_version` = app.js mtime)
│   ├── index.html          # Dashboard: exhaustive project + firewall lists, hosts both
│   │                       #   creation wizards (modals) + the edit-firewall modal
│   ├── _project_wizard.html  # 3-step project creation wizard (basic data → attach
│   │                       #   existing firewalls — with or without an imported
│   │                       #   configuration → validate + open project page)
│   ├── _firewall_wizard.html # 3-step firewall creation wizard (basic data → import
│   │                       #   w/ connectivity check + progress → create / skip import;
│   │                       #   on import failure: Back to step 2 + "Import configuration"
│   │                       #   retry without re-creating the firewall; "Done — go to
│   │                       #   dashboard" hidden while the retry is pending; the step-3
│   │                       #   action label is a single x-text span)
│   ├── _firewall_edit.html   # Edit-firewall modal (wizard step-1 fields; loads current
│   │                       #   values incl. credentials, PATCH /api/firewalls/<id>)
│   ├── project.html        # Project detail: stat cards, objects by type per firewall as a
│   │                       #   block per firewall (clickable type-chip grid + total link,
│   │                       #   "Total per type" footer), firewalls table (Import / Edit /
│   │                       #   View Objects / Remove) with the "Attach existing" form (any
│   │                       #   firewall, config-less ones marked "no configuration yet")
│   │                       #   at the bottom of the SAME card, Export button below the card
│   ├── _project_nav.html   # Conditional navbar partial (Objects / Export)
│   ├── project_edit.html   # Edit project name/description
│   ├── export.html         # Export page: per-firewall/type + modified stats, 4-step wizard
│   │                       #   (type step: Select all / Tagged only / Clear shortcuts,
│   │                       #   per-type Tagged only / All objects scope)
│   ├── import.html         # Standalone import wizard (firewall → source/types → review)
│   ├── objects.html        # Scoped object list: type-specific columns, add/modify/delete
│   │                       #   staging, Validate (commit), pagination 10-500, Export button,
│   │                       #   "In export" tag column + selection checkboxes (Include /
│   │                       #   Remove from export buttons apply the selection). Modify modal:
│   │                       #   visual payload form (one field per payload key: text/number/
│   │                       #   boolean/list/JSON + "Re-sync from Payload JSON") + Payload JSON
│   │                       #   textarea; Validate = stage + commit the single change
│   ├── trash.html          # Trash bin + restore
│   ├── firewalls.html      # Firewall dashboard (card grid + New Firewall wizard modal
│   │                       #   + edit-firewall modal; per-card Objects / Import / Edit /
│   │                       #   Delete; deep link ?edit=<id> opens the edit modal)
│   └── projects.html       # Full-page project list + create form
├── files/                  # Reference samples of the config file types accepted by Import
│   ├── FGT_CHATEAUDUN_2_7-2_1761_202610011359.conf  # FortiGate (FortiOS 7.x) full CLI config (778 KB)
│   ├── MT-FGTVYV324082026.xml                       # Palo Alto (PAN-OS 11.1) XML device export, minified (1.95 MB)
│   ├── MT-FGTVYV324082026-pretty.xml                # same export, pretty-printed (3.84 MB)
│   └── MT-FGTVYV324082026-set.txt                   # same config, set (show) format export (2.54 MB)
├── static/js/app.js        # Alpine components: dashboard, firewallDashboard, projectWizard,
│   │                       #   firewallWizard, firewallEdit, objectTable, exportWizard,
│   │                       #   importWizard, trashBin
├── instance/swissknife.db  # SQLite database (tables auto-created + migrated at startup)
├── .gitignore              # ignores .venv/, __pycache__, QA/
├── QA/                   # Files created during the testing phase (test scripts,
│   │                     #   run logs, generated artifacts, API probes) — see
│   │                     #   [§9](#9-qa-folder-files-created-during-the-testing-phase)
└── requirements.txt        # + requests (connectivity checks, REST retrieval/push)
```

Key design notes:

- `create_app()` calls `db.create_all()` **after** the blueprint imports
  (models register their tables in the metadata at import time), then runs the
  one-off SQLite migrations (`firewalls.project_id` nullable, firewall
  `model`/`auth_mode`/`api_token` columns, `config_objects.project_id`
  nullable) so existing databases evolve in place.
- The navbar in `base.html` is a `{% block nav %}` so the project pages can
  override it with the conditional `_project_nav.html`.
- The wizards are Alpine components talking to the REST API (no CSRF forms):
  `projectWizard()` / `firewallWizard()` in `static/js/app.js`; progress bars
  use XHR upload progress (files) and NDJSON streaming responses
  (`/api/import/stream`, `/api/export/push`).
- `Firewall.set_project()` keeps `config_objects.project_id` in sync when a
  firewall is attached to / removed from a project.
- **Alpine `x-data` attributes that embed JSON (via `tojson`) must be
  single-quoted**: the JSON output contains double quotes, which would
  terminate a double-quoted HTML attribute mid-attribute and silently break
  the component (root cause of the 2026-11-24 edit-form bug). Bindings inside
  components must also short-circuit optional state (`connResult && …`),
  because Alpine evaluates `x-show` / `x-text` even on hidden elements.

---

## 3. How to run

```bat
:: from the repo root (Windows)
.venv\Scripts\activate
pip install -r requirements.txt

:: run (dev server)
.venv\Scripts\python -c "from app.factory import create_app; create_app().run(host='127.0.0.1', port=5000)"
```

Open `http://127.0.0.1:5000` — the dashboard is the landing page.

> **Note:** with debug mode **off**, Jinja templates are cached per process.
> After editing any template, **restart the server**.

### Running the dev server in the background (verification / LLM sessions)

Use this when the app must run unattended (e.g. headless-browser
verification against `http://127.0.0.1:5000`). **Do not** pass the `-c`
inline script directly through `Start-Process -ArgumentList` — it fails on
the first attempt for two compounding reasons:

1. `Start-Process -ArgumentList` **does not quote array elements**: it joins
   them with spaces into one command line, so
   `-ArgumentList '-c','from app.factory import create_app; …'` reaches
   python as separate argv items (`-c`, `from`, `app.factory`, …) — python
   gets a broken `-c` value, dies at startup with a `SyntaxError`, and the
   port never opens. Escaping the quotes for the cmd → `powershell -Command`
   nesting does not fix it.
2. Relative `-RedirectStandardOutput` / `-RedirectStandardError` paths are
   resolved against the **caller's current directory**, not against
   `-WorkingDirectory` — the log files land elsewhere, the crash message is
   lost, and the failure looks silent.

Reliable recipe (verified — succeeds on the first attempt):

1. Create a launcher `_run_server.bat` in the repository root (the quoting
   lives inside the file, where cmd applies it directly):

   ```bat
   @echo off
   cd /d C:\Users\hedhl\source\repos\NXO_Swiss_Knife
   ".venv\Scripts\python.exe" -c "from app.factory import create_app; create_app().run(host='127.0.0.1', port=5000)"
   ```

2. Launch it with **absolute** redirect paths:

   ```powershell
   Start-Process -FilePath 'C:\Users\hedhl\source\repos\NXO_Swiss_Knife\_run_server.bat' -WorkingDirectory 'C:\Users\hedhl\source\repos\NXO_Swiss_Knife' -RedirectStandardOutput 'C:\Users\hedhl\source\repos\NXO_Swiss_Knife\_server_log.txt' -RedirectStandardError 'C:\Users\hedhl\source\repos\NXO_Swiss_Knife\_server_err.txt' -WindowStyle Hidden -PassThru
   ```

3. Wait for the port with a **fast** TCP probe — `Test-NetConnection` takes
   1-2 s per attempt, and a 20-30-iteration loop exceeds a typical 60 s
   command timeout:

   ```powershell
   foreach ($i in 1..15) {
     try { $c = New-Object Net.Sockets.TcpClient; $c.Connect('127.0.0.1', 5000); $c.Close(); 'PORT UP'; break }
     catch { Start-Sleep -Milliseconds 400 }
   }
   ```

4. When done: stop it by port owner and delete the temporary files —
   `_run_server.bat` + `_server_log.txt` / `_server_err.txt` are **not** part
   of the repository, and stray `.txt` / `.py` files at the repo root would
   be picked up by the next Vector DB re-index:

   ```powershell
   $c = Get-NetTCPConnection -LocalPort 5000 -State Listen | Select-Object -First 1
   Stop-Process -Id $c.OwningProcess -Force
   Remove-Item .\_run_server.bat, .\_server_log.txt, .\_server_err.txt
   ```

Environment variables (all optional):

| Variable | Purpose | Default |
|---|---|---|
| `SWISSKNIFE_SECRET` | Flask secret key | `dev-secret-change-me` |
| `DATABASE_URL` | SQLAlchemy URI | `sqlite:///swissknife.db` (in `instance/`) |
| `SWISSKNIFE_ENABLE_PUSH` | `1` to enable the mock push URL | off |
| `SWISSKNIFE_ADMIN_USER` / `SWISSKNIFE_ADMIN_PASS` | placeholder login | `admin` / `change-me` |

The `RAG_*` variables (source root, Ollama URL, thresholds, chunk sizes) belong
to the **Vector_DB** project, not to this app — see
[§7](#7-vector-db-integration-token-efficient-development).

---

## 4. Changelog (modifications)

The full changelog lives in its own file: **`CHANGELOG.md`** (repository
root) — chronological log, newest first.

Add entries there when recording changes
(see [Maintenance rules](#8-maintenance-rules)).

---

## 5. Feature tracking

Status legend: ✅ done · 🚧 in progress · 📋 planned.

### Done

| Feature | Where | Notes |
|---|---|---|
| Dashboard: exhaustive projects + firewalls | `views.dashboard`, `index.html`, `dashboard()` | Two card sections (projects, firewalls) with counts, both creation wizards, `GET /api/projects` + `GET /api/firewalls` |
| Firewall creation wizard (3 steps) | `_firewall_wizard.html`, `firewallWizard()`, `POST /api/firewalls` | Step 1 basic data (name, vendor, **model**, mgmt IP, **login/password or API token**, description); step 2 import source (file upload or REST API) with **Check connectivity** (`POST /api/connectivity`) ; step 3 create + **skip import** option; import runs after create with XHR upload progress or `/api/import/stream` NDJSON progress; **on import failure (e.g. "No configuration file chosen") a Back button returns to step 2** and the step-3 button becomes **Import configuration** — the created firewall is re-imported, never re-created; **while a retry is pending the "Done — go to dashboard" button is hidden** (`x-show="!importError"`, only Back + Import configuration apply); the step-3 action label is a single deterministic `x-text` span (per-state `x-show` spans could be left stale by Alpine's delayed show/hide scheduling, which blanked the "Import configuration" label after a failed no-file import) |
| Project creation wizard (3 steps) | `_project_wizard.html`, `projectWizard()`, `POST /api/projects` | Step 1 name/description; step 2 attach existing firewalls (**any firewall — also without an imported configuration**, marked "no configuration yet"; "create a firewall first" suggestion when none exist); step 3 validation summary → opens the new project page immediately; attaching moves the firewall (objects follow via `set_project()`) |
| Project cards: Open / Delete | `index.html`, `dashboard()` | Delete = `confirm()` + cascade delete; **the list refreshes in place** (the POST follows the 302, final 200 = success, `reloadAll()` re-fetches both lists — no page reload); the same `deleteEntity` pattern applies to firewall deletes on the dashboard and the `/firewalls` page (`firewallDashboard()`) |
| Project detail page + conditional navbar | `project_detail`, `project.html`, `_project_nav.html` | Navbar: Objects / Export; stat cards (firewalls, objects, types, **modified**, last import); **objects by type, per firewall** — one block per firewall with a clickable type-chip grid (count click → filtered object list, zero counts muted) + clickable per-firewall total and a "Total per type" footer; **Firewalls card** with the firewall table (per-row Import / Edit / View Objects / Remove) **and the "Attach existing" form at the bottom of the same card** (any firewall — config-less ones marked "no configuration yet"); **Export button below the firewall card** → `/projects/<id>/export` |
| Project page: per-row Remove firewall (unassign) | `remove_project_firewall`, `project.html` | `confirm()` dialog; `set_project(None)` — firewall + objects kept; reattach via "Attach existing" |
| Firewall dashboard (card style) | `firewalls_page`, `firewalls.html`, `firewallDashboard()` | Card grid; New Firewall = 3-step wizard modal; per-card Objects / **Import** / **Edit** / Delete; `GET /api/firewalls` adds `project`, `objects_count`, `has_config`, `types_counts`; deep link `?edit=<id>` opens the edit modal |
| Firewall edit modal (change any firewall field) | `_firewall_edit.html`, `firewallEdit()`, `GET/POST/PATCH /api/firewalls/<id>` | Same fields as wizard step 1 (name, vendor, model, mgmt IP, login/password or API token, description); `GET` returns the stored credentials for the form (the list endpoint hides them); empty values clear a field, the inactive credential side clears automatically; optional `project_id` (int/null) reassigns/unassigns and syncs the objects via `set_project()`; friendly error on the `(project_id, name)` unique constraint; Edit buttons on the dashboard + firewall dashboard cards and per row in the project table; list refreshes after save |
| Import shortcut on firewall cards | `firewalls.html`, `index.html` | Per-card **Import** links to `/import?firewall_id=…` — the existing import wizard (file or URL, per-type) starts at the source step; re-importing upserts the objects |
| Project edit page | `edit_project`, `project_edit.html` | Name + description (Flask-WTF `ProjectForm`) |
| Object list (type-specific, staged edits) | `objects_page`, `objects.html`, `objectTable()` | Scoped by navigation context (no project/firewall filters); **columns per object type** from the normalized payloads; add/modify/delete actions **staged client-side**, committed atomically by **Validate** → `POST /api/objects/commit`; `POST /api/objects` for single creates; pagination: total pages, next/prev, rows-per-page 10/15/25/50/100/500; back-to-project link; **Export** button below the table; **"In export" tag column** (badge per tagged row) + **selection checkboxes** (row + page header, tagged rows preselected, **no server call on check/uncheck**) — the selection is applied by the toolbar **Include in the export (N)** / **Remove from export (N)** buttons → `POST /api/objects/export-include` (`include: true/false`); counts = selected rows that will change. **Modify modal: visual payload form** — one field per payload key (text/number/boolean/one-item-per-line list/JSON textarea; `buildPayloadFields`/`applyPayloadFields`) + "↻ Re-sync from Payload JSON"; the modal **Validate** = stage + commit the single change (list refreshes; on failure the change stays staged for the toolbar); row-level Delete stages the trash move |
| Export page + 4-step wizard | `export_page`, `export.html`, `exportWizard()` | Stats: objects per firewall/type + **modified** per firewall/type; step 1 destination (attached firewalls), step 2 type filter (**Select all / Tagged only / Clear** shortcuts — "Tagged only" selects every type filter in the tagged scope; per-type **Tagged only** / **All objects** radios), step 3 summary + method, step 4 file (progress + download link via `POST /api/export/file` / `GET /api/export/file/<token>`) or push (connection status + Push + streaming progress via `POST /api/export/push`); **the generated configuration spans ALL firewalls in the database** — the destination receives every active object of the selected types, not only its own imported configuration (both file and push go through `_build_config()`); the "Object types to export" counts therefore span every firewall; **Validate & return to project** after success |
| Export (legacy endpoint) | `POST /api/export` | Parser-generated download or mock push (kept for compatibility) |
| Import wizard (file / URL, per-type) | `import_page`, `import.html`, `POST /api/import` | Vendor auto-detection (incl. PAN-OS set format). Both parsers store **address, address group, service, service group, security rule, interface, zone**: Fortinet = full FortiOS CLI export (`address`+`address6`, `addrgrp`, `service custom`, `service group`, `policy`, `system interface`, `system zone` or interface `set zone`); Palo Alto = PAN-OS 11.x XML device export (objects directly under `vsys/entry`), older wrapped exports, app-generated `<paloalto>` docs **and** set/`show` format. Samples in `files/`; see [§2](#2-architecture--layout) |
| Streaming import with progress | `POST /api/import/stream` | NDJSON progress events (connect/download/parse/import); used by the firewall wizard for REST sources |
| Connectivity check | `POST /api/connectivity` | TCP :443 + vendor API probe (Fortinet `/api?uuid=`, PAN-OS `/api/?type=op`), self-signed TLS handled, used by the firewall wizard and the export push step |
| Trash + restore | `trash_page`, `trash.html`, `/api/trash` | Soft delete with reason |
| REST API + error handlers | `app/api/routes.py`, `errors.py` | Projects (+`firewall_ids` attach), firewalls (+detail/update `GET/POST/PATCH /api/firewalls/<id>`), import (+stream), objects (GET/POST/commit), trash, export (file/push), connectivity, auth placeholder |
| Auth placeholder | `/api/auth/login`, `current_user()` | Session user only — see Known issues |
| DB schema auto-creation + migrations | `factory.create_app` | `db.create_all()` + one-off migrations: `firewalls.project_id` nullable, `firewalls.model`/`auth_mode`/`api_token`, `config_objects.project_id` nullable (table rebuild) |
| Demo data seed | `instance/swissknife.db` | "Demo Project" + 2 demo firewalls |
| Vector DB (standalone project) | `C:\Users\hedhl\source\repos\Vector_DB` | indexes this repo **including the `files/` sample configs** (`.conf`/`.xml`/`.txt`) and the frontend (`templates/*.html` + `static/js/app.js`, Tree-sitter AST chunking); top-3 chunk retrieval with cosine threshold, file-scoped queries via `--where file=...` — the only search path for the multi-MB samples, see [§7](#7-vector-db-integration-token-efficient-development) |

### Planned (suggested backlog)

| Feature | Notes |
|---|---|
| 📋 Real authentication | Replace `current_user()` / `/api/auth/login` with JWT or session login; protect API + UI routes |
| 📋 Project delete from project page | Currently only from the dashboard cards |
| 📋 Import: per-project pre-filter | Import wizard lists all firewalls; could accept `?project_id=` |
| 📋 Config diff / change review | Compare old vs new payload before upsert (history exists, no diff view) |
| 📋 Alembic migrations | Replace the one-off SQLite migrations + `db.create_all()` startup behavior for schema evolution |
| 📋 Real vendor push | `_mock_push_config` is a placeholder — the streaming push skeleton, connectivity probe and auth modes (login/password, API token) are already in place |
| 📋 Real vendor import via API | `/api/import/stream` already downloads from a URL; add vendor-specific API endpoints (FortiOS `get config`, PAN-OS `show config`) instead of a plain GET |
| 📋 Route / IPsec tunnel parsers | `route` and `ipsec_tunnel` are still not parsed (see Known issues) |
| 📋 Tests | Web UI and flows verified with **obscura (headless browser)**; any test scripts / artifacts created during the testing phase are stored in **`QA/`** (see [§9](#9-qa-folder-files-created-during-the-testing-phase)) — no permanent automated test suite in the repo |
| 📋 Production packaging | Tailwind CDN → PostCSS build; WSGI server (gunicorn); `run.py` entry point |
| 📋 Backup / export of whole project | Currently only config export per firewall |

---

## 6. Known issues & technical debt

- **No real authentication.** `current_user()` returns a session user or
  "system"; the login endpoint is a demo placeholder.
- **`db.create_all()` at startup** — fine for dev, but schema evolution relies
  on the one-off migrations in `factory.py` (no Alembic): `firewalls.project_id`
  nullable, `firewalls.model`/`auth_mode`/`api_token` columns,
  `config_objects.project_id` nullable (table rebuild).
- **`config_objects.project_id` is nullable.** Objects imported into an
  unassigned firewall have `project_id = NULL` until the firewall is attached
  (attach/remove syncs the objects via `Firewall.set_project()`).
- **Staged object edits are all-or-nothing.** `POST /api/objects/commit`
  applies the whole batch in one transaction; any validation/constraint error
  rolls everything back (the staged changes stay in the browser).
- **Tailwind via CDN** — dev-only warning shown in the console; not a
  production build.
- **Push is mocked** (`_mock_push_config`); real vendor APIs are not called
  unless `SWISSKNIFE_ENABLE_PUSH=1` (and even then it hits a placeholder URL).
- **Vendor parsers cover 7 of 9 object types.** Both `FortinetParser` and
  `PaloAltoParser` store address, address group, service, service group,
  security rule, interface and zone; `route` and `ipsec_tunnel` are not yet
  implemented (selecting them yields an import warning). Known limits:
  Fortinet `all`/`none` and other value-less address entries are skipped
  (counted in warnings); PAN-OS **dynamic** address groups are skipped
  (warning); a Palo Alto object-only export carries no interfaces (0
  interface objects), and a FortiGate export without `config system zone` /
  `set zone` carries no zones (rule `*_zones` stay empty); the set-format
  interface capture (`set devices system …`) is best-effort.
- **Connectivity check is best-effort.** TCP :443 + one HTTP probe per vendor;
  it reports reachability and the API status code but does not perform a full
  credential verification beyond the probe's HTTP 401/403 answer.
- **Export file artifacts are in-memory.** Generated download links
  (`/api/export/file/<token>`) live in the process and expire after 1 hour or
  on restart — re-generate if a link stops working.
- **Templates cached when debug is off** — restart the server after template
  edits.
- **Browsers cache `static/js/app.js` for Flask's default static max-age
  (12 h).** The `base.html` script tag therefore carries a `?v=<mtime>`
  cache-buster (Jinja global `app_version`, set in `create_app()` from the
  file's mtime): after a server restart following an app.js edit, a plain
  page refresh already loads the new JS. Without it, a stale cached app.js
  (older function names) silently breaks interactions on the fresh HTML.
- **No tests**, no `run.py` / packaging entry point.
- **Firewall attach moves the firewall** by design — attaching (project
  wizard, "Attach existing") reassigns it from its current project; the UI
  states this in both places.
- **`GET /api/objects` caps `per_page` at 500** (raised from 200 for the
  rows-per-page selector on the object list page).
- **`GET /api/firewalls/<id>` returns the stored credentials in plain text**
  (login/password or API token) so the edit form can pre-fill them — the
  list endpoint keeps hiding them. Same local-dev caveat as the model
  comment: store encrypted credentials in production.

---

## 7. Vector DB integration (token-efficient development)

**Priority:** when **modifying this project or adding new features**,
LLM-assisted work **MUST query the standalone Vector_DB project before every
direct reading of this repository's files** — the query is a mandatory first
step of any change (including a precise edit), to reduce token consumption.
**Direct file reading is NOT allowed until the retrieval has returned no
useful information** (0 relevant chunks, or chunks that do not answer the
question):

- **Location & usage:** `C:\Users\hedhl\source\repos\Vector_DB` — independent
  repo; **its `README.md` holds the full documentation** and is the reference
  for how to query/index the store.
- **What it indexes:** this repository (default extensions
  `.py`/`.js`/`.html`/`.css`/`.conf`/`.txt` — `.md` files are intentionally
  not indexed; skips `node_modules/`, `dist/`, `build/`, minified
  `.min.js`/`.min.css`, source maps `.map` and lockfiles; configurable via
  `RAG_SOURCE_ROOT` / `--ext`). Chunks live in its own
  `./.vectordb` (ChromaDB, cosine; local Ollama `nomic-embed-text` embeddings).
- **Token saving:** retrieval returns only the top 3 chunks (cosine >= 0.45,
  ~300-500 words each with 50-word overlap) and the built LLM prompt contains
  ONLY those chunks — typically a few thousand words instead of tens of
  thousands per file. An unrelated query returns 0 chunks (the prompt says so
  explicitly) so no prompt tokens are wasted.

### Workflow for feature development / modification

1. **Start Ollama** (once per machine boot, background on Windows):

   ```bat
   powershell -NoProfile -Command "Start-Process 'C:\Users\hedhl\AppData\Local\Programs\Ollama\ollama.exe' -ArgumentList 'serve' -WindowStyle Hidden"
   ```

   (model `nomic-embed-text` is already pulled; run
   `ollama pull nomic-embed-text` if missing)

2. **Mandatory Vector DB query BEFORE reading any file** — ask the store
   about the area you will touch (usage reference:
   `C:\Users\hedhl\source\repos\Vector_DB\README.md`):

   ```bat
   :: from C:\Users\hedhl\source\repos\Vector_DB, with its venv activated
   python rag_query.py "How does the export flow work?"
   python rag_query.py "What validation rules does ProjectForm implement?"
   python rag_query.py "How is modification history written?" --where "file=app/models.py"
   ```

   Feed the printed prompt — or the `prompt` field of
   `POST http://127.0.0.1:5100/api/rag/query` — to the LLM. Only when the
   query returns no useful information (0 relevant chunks, or chunks that do
   not answer the question) may you fall back to reading the file directly.

3. **Implement the change** in this repo (models, views, API, templates,
   `PROJECT.md`).

4. **Re-index afterwards** so the store reflects the new code/docs:

   ```bat
   :: from the Vector_DB repo root
   python index_db.py         :: skips unchanged files; re-embeds only changed ones
   python index_db.py --prune :: optional: drop chunks of files that were deleted
   ```

   (or run the Vector_DB HTTP service and `POST /api/rag/reindex`).

   If the run must be **backgrounded with a log** (Windows): never use
   `start "" python index_db.py > _log.txt 2>&1` — cmd redirection applies to
   `start` itself, the child gets a throwaway console, the log stays empty and
   the process dies with that console. Use PowerShell `Start-Process` with
   explicit stream redirection instead (see the Notes below).

5. **Verify:** `GET http://127.0.0.1:5100/api/rag/status`, or ask the store
   about the new feature with `python rag_query.py`.

### Vector_DB configuration (env vars, all optional)

| Variable | Purpose | Default |
|---|---|---|
| `RAG_SOURCE_ROOT` | repository to index (this repo by default) | `C:/Users/hedhl/source/repos/NXO_Swiss_Knife` |
| `RAG_OLLAMA_URL` | Ollama server URL | `http://127.0.0.1:11434` |
| `RAG_EMBED_MODEL` | embedding model | `nomic-embed-text` |
| `RAG_TOP_K` | chunks per query | `3` |
| `RAG_MIN_COSINE` | similarity threshold | `0.45` |
| `RAG_CHUNK_MIN_WORDS` / `RAG_CHUNK_MAX_WORDS` / `RAG_CHUNK_OVERLAP_WORDS` | chunk sizes | `300` / `500` / `50` |
| `VECTOR_DB_HOST` / `VECTOR_DB_PORT` | HTTP service binding | `127.0.0.1` / `5100` |

Notes:

- The Vector_DB store is **local-only and gitignored**; it may contain
  sensitive data (e.g. `ENC` passwords from firewall configs) — never share
  `.vectordb/`.
- Ollama must be running for indexing/querying; otherwise the Vector_DB CLI
  exits with a clear error and its HTTP service returns 503.
- **Backgrounding the re-index on Windows:** do NOT use
  `start "" python index_db.py > _reindex_log.txt 2>&1` — in cmd the
  redirection only applies to `start` itself; the child process's stdout/
  stderr go to a new throwaway console, so the log stays empty and the
  process dies with that console. Use PowerShell `Start-Process` with
  explicit stream redirection (`-u` = unbuffered, so progress is logged live):

  ```powershell
  Start-Process -FilePath "C:\Users\hedhl\source\repos\Vector_DB\.venv\Scripts\python.exe" \
    -ArgumentList '-u','index_db.py' \
    -WorkingDirectory "C:\Users\hedhl\source\repos\Vector_DB" \
    -RedirectStandardOutput "_reindex_log.txt" -RedirectStandardError "_reindex_err.txt" \
    -PassThru
  ```

  (`-PassThru` returns the process object — check completion via
  `Wait-Process` / `$p.ExitCode`.) Short incremental re-indexes (a few
  seconds) can simply run in the foreground. Keep the `-RedirectStandard*`
  paths **absolute** — relative paths resolve against the caller's current
  directory, not `-WorkingDirectory` (same pitfall as the §3 background
  server recipe).
- The `.html` templates and the `.js` frontend code are indexed with
  **Tree-sitter AST chunking** (JS/TS top-level functions/declarations,
  Python top-level `def`/`class` blocks, HTML body-level elements,
  CSS rules); if this repo adds other file types worth indexing, extend
  the scope in Vector_DB
  (`RAG_SOURCE_ROOT` + `--ext`, or `DEFAULT_INDEX_EXTS` in
  `app/rag/config.py` there).

---

## 8. Maintenance rules

1. **Querying the Vector_DB store is MANDATORY before every direct file read
   of this repository** (token-efficient context retrieval) — follow the
   usage documented in `C:\Users\hedhl\source\repos\Vector_DB\README.md`
   (workflow in
   [§7](#7-vector-db-integration-token-efficient-development)). **No direct
   file reading is allowed until the query has returned no useful
   information** (0 relevant chunks, or chunks that do not answer the
   question) — no exception for precise edits: query the store first, then
   read the file.
   **For the sample configuration files in `files/`, the Vector DB is the
   ONLY allowed search path** (multi-MB files, already indexed): query with a
   `--where file=files/...` filter, see
   [§7](#7-vector-db-integration-token-efficient-development).
2. **Before committing any change**, add an entry to **`CHANGELOG.md`**
   under today's date:
   - what changed (bug fix / feature / refactor),
   - which files were touched,
   - how it was verified.
3. **Update the Feature tracking table** in
   [§5](#5-feature-tracking):
   - move items 📋 → 🚧 → ✅ as work progresses,
   - add new 📋 rows when a new capability is scoped.
4. If an architecture decision changes (DB, stack, routes), update
   [§1](#1-description), [§2](#2-architecture--layout) and
   [§3](#3-how-to-run) in the same pass.
5. Keep this file at the repository root: `PROJECT.md`.
6. **After any change to code or documentation**, update the **Vector_DB**
   store so retrieval reflects the current state of this repository:
   from `C:\Users\hedhl\source\repos\Vector_DB` (with its venv activated)
   run `python index_db.py` — add `--prune` when files were deleted —
   see the workflow in
   [§7](#7-vector-db-integration-token-efficient-development) (step 4).
7. **Testing:** functional verification of the web UI and its flows is done
   with **obscura (the headless browser)**; there is no permanent automated
   test suite in the repo. **Every file created during the testing process
   (test scripts, run logs, dumps, screenshots, API probes) MUST be placed in
   the `QA/` folder** — never at the repository root or inside `app/`,
   `templates/`, `static/` or `files/` (stray files at the root would be
   picked up by the next Vector DB re-index) — see
   [§9](#9-qa-folder-files-created-during-the-testing-phase).
8. `QA/` is disposable: after a test round its contents may be deleted; nothing
   in `QA/` is a permanent part of the application and `QA/` scripts are not
   imported by the app (they rely only on the app's own venv).

---

## 9. QA folder — files created during the testing phase

`C:\Users\hedhl\source\repos\NXO_Swiss_Knife\QA` is the designated location
for **every file created during the testing process**:

- ad-hoc test scripts (Python / PowerShell) written to verify an endpoint,
  parser, or flow,
- server run logs and console captures from test runs,
- generated artifacts (exported configuration files, DB dumps, screenshots)
  kept for analysis,
- one-off API probe scripts run against `http://127.0.0.1:5000`.

Rules:

1. **Never create test files at the repository root or inside `app/`,
   `templates/`, `static/` or `files/`** — they would be picked up by the
   next Vector DB re-index and pollute the source tree.
2. Functional verification of the web UI itself remains **obscura
   (headless browser) only** — the `QA/` scripts *support* (not replace) it,
   e.g. direct REST checks and parser/DB assertions.
3. `QA/` contents are **disposable**: after a test round, files may be
   deleted; nothing in `QA/` is a permanent part of the application.
4. `QA/` scripts are not imported by the app and are not listed in
   `requirements.txt` — they run with the app's own `.venv` (Python stdlib +
   `requests` + `sqlite3`).

### Typical scripts (created per test round in `QA/`)

| Script (suggested name) | Purpose |
|---|---|
| `qa_api_smoke.py` | Hit the main REST endpoints (`GET /api/projects`, `GET /api/firewalls`, `GET /api/objects`, `POST /api/objects/commit`, `POST /api/export/file`, `POST /api/connectivity`) and assert status codes + JSON shape |
| `qa_parser_check.py` | Run `PaloAltoParser` / `FortinetParser` on the samples in `files/` and assert per-type object counts (address, service, rule, interface, zone, …) |
| `qa_db_inspect.py` | Count rows in `projects` / `firewalls` / `config_objects` / `modification_history` / `trash` in `instance/swissknife.db`; verify upsert + history writes |
| `qa_export_roundtrip.py` | Generate an export via `POST /api/export/file`, download it, compare object counts against the DB, and optionally re-parse the generated file |
| `qa_server.ps1` (or `_run_server.bat`) | Start/stop the dev server in the background + fast TCP port probe — the recipe from [§3](#3-how-to-run), adapted for a test round |
| `qa_wizard_flows.md` (notes) | Check-list of obscura sessions: firewall/project wizards, staged edits + Validate, trash restore, export wizard |
