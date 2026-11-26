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
  `modification_history`. Every import run is recorded as an
  `ImportRecord` (import history, shown on the import form); a new import
  **replaces** the previous import of the firewall — the previous import's
  objects are deleted before the new configuration is applied.
- **Staged edits + Validate**: object edits/deletes/creates are staged
  client-side and committed atomically by `POST /api/objects/commit`.
- **Trash**: soft delete with reason and restore support for **objects,
  firewalls and projects** (deleting a project/firewall cascades into the
  trash, restoring brings the descendants back). The trash is **separated
  by level**: the dashboard trash (navbar "Trash") lists deleted **projects
  and firewalls** only, and every project has its own trash can (trash-can
  icon on the project page) listing **that project's deleted objects** only.
  Deleted objects stay visible on the object list (greyed out) with a
  **Restore** button in place of Delete.
- **Export**: generate vendor configuration text (temporary download link) or
  push it with streaming progress (currently a mock push).
- **Authentication**: local user/password accounts stored in a **separate
  database file** (`instance/users.db`); session login (`/login`), a login
  guard on every page and API route, and **user management on the
  dashboard** (add users, reset passwords, enable/disable, delete). The
  initial `admin` account is bootstrapped on first start.
- REST **API** (`/api/...`) plus a browser UI (Alpine.js + Tailwind CDN).

### Stack

| Layer | Technology |
|---|---|
| Web framework | Flask 2.3.3 |
| ORM / DB | Flask-SQLAlchemy 3.0.5, SQLAlchemy 2.1.9, SQLite — main DB `instance/swissknife.db` **+ separate users DB `instance/users.db`** (the `User` model, bound via `SQLALCHEMY_BINDS`/`__bind_key__`) |
| Auth | Flask session login (`app/auth.py`); passwords hashed with `werkzeug.security` (scrypt + per-password salt) |
| Forms / CSRF | Flask-WTF 1.1.1, WTForms 3.0.1 |
| Frontend JS | Alpine.js (CDN, **pinned to v3.17.5** — the floating `@3.x.x` URL silently broke the confirm/toast `x-init` bindings when it resolved to 3.17.5; see design notes) |
| Styling | Tailwind CSS (CDN build — dev only) |
| Misc | python-dotenv, requests |
| Companion RAG project | **Vector_DB** (sibling repo `C:\Users\hedhl\source\repos\Vector_DB`) — ChromaDB + Ollama `nomic-embed-text`, token-efficient context retrieval; see [§7](#7-vector-db-integration-token-efficient-development) |

Python: 3.13 (`.venv` in the repository root).

---

## 2. Architecture & layout

```
NXO_Swiss_Knife/
├── app/
│   ├── factory.py          # create_app() — Flask factory: main + users DB binds,
│   │                       #   session-cookie config, db.create_all() + one-off migrations
│   │                       #   (firewalls.project_id nullable, firewall auth columns,
│   │                       #   config_objects.project_id nullable, export_included,
│   │                       #   projects/firewalls is_deleted+deleted_at, trash table
│   │                       #   rebuilt multi-type), ensure_admin_user() bootstrap,
│   │                       #   init_auth() (blueprints + login guard)
│   ├── extensions.py       # db = SQLAlchemy()
│   ├── models.py           # Project + Firewall (project_id nullable = can be
│   │                       #   unassigned; model, auth_mode password|token, api_token;
│   │                       #   set_project() keeps object project_ids in sync;
│   │                       #   is_deleted + soft_delete()/restore() = Trash),
│   │                       #   ConfigObject (project_id nullable, is_deleted, import_id
│   │                       #   = the import run that created it), ModificationHistory,
│   │                       #   ImportRecord (one row per import run — the import
│   │                       #   history; a new import replaces the previous one),
│   │                       #   Trash (item_type object|project|
│   │                       #   firewall — one row per deleted entity), ExportRecord
│   │                       #   (generated/pushed config files kept on disk), User
│   │                       #   (authentication account — SEPARATE users database,
│   │                       #   __bind_key__="users", set_password/check_password via
│   │                       #   werkzeug hashes, is_active, last_login_at)
│   ├── auth.py             # Authentication: /login + /logout (form), /api/auth/login
│   │                       #   (JSON, replaces the old env-var placeholder) +
│   │                       #   /api/auth/me, /api/users CRUD (list/create/reset
│   │                       #   password/enable-disable/delete — the dashboard's Users
│   │                       #   section), authenticate() (timing-equalized, generic
│   │                       #   error, 0.5 s delay + log on failure), the before_request
│   │                       #   login guard (pages → /login?next=…, API → 401 JSON),
│   │                       #   ensure_admin_user() (first-start bootstrap of `admin`),
│   │                       #   init_auth() (blueprints + guard)
│   ├── views.py            # Web UI routes (dashboard, project pages w/ per-firewall/per-type
│   │                       #   stats + previous-exports list, attach/remove firewall, import
│   │                       #   (?project_id= → wizard's back link/button returns to the
│   │                       #   project page, else the dashboard), objects w/ type-specific
│   │                       #   columns, export w/ stats, export-file download, trash)
│   ├── api/routes.py       # REST API (projects + attach, firewalls + detail/update
│   │                       #   GET/POST/PATCH /api/firewalls/<id>, import + /import/stream
│   │                       #   NDJSON progress, /connectivity, objects CRUD + /objects/commit
│   │                       #   batch validate + /objects/<id>/restore, /import/records
│   │                       #   (import history), trash (dashboard:
│   │                       #   projects/firewalls; ?project_id= the project's deleted
│   │                       #   objects; restore of any entry type;
│   │                       #   /trash/permanent-delete = permanent delete of the
│   │                       #   selected / all deleted objects of a project — object +
│   │                       #   history + trash row removed, name freed),
│   │                       #   /export/file + download,
│   │                       #   /export/push streaming — every generated/pushed config is
│   │                       #   persisted to instance/exports/ + export_records (project
│   │                       #   page list), auth placeholder)
│   ├── errors.py           # API exception types
│   ├── forms/              # ProjectForm (used by the project edit page)
│   └── vendors/            # base.py, factory.py (parser registry), paloalto.py, fortinet.py
├── templates/
│   ├── base.html           # Layout + navbar (Dashboard / Trash, block `nav`, + the
│   │                       #   signed-in user chip and the Sign out POST form outside
│   │                       #   the block so every page shows them) +
│   │                       #   section system (`.section` as a sunken surface
│   │                       #   slab with ruled `.section-head` — wraps on narrow
│   │                       #   screens: `.section-kicker` / `.section-title` /
│   │                       #   `.section-sub`; `.page-hero`) + alert system
│   │                       #   (`.flash` success/error/warning/info: per-variant SVG
│   │                       #   icon via ::before + 4px left accent bar + soft tint)
│   │                       #   + scripts (app.js BEFORE Alpine — Alpine pinned to 3.17.5,
│   │                       #   loaded with a ?v= cache-buster — Jinja global
│   │                       #   `app_version` = app.js mtime) + the global
│   │                       #   confirmation dialog + notification stack
│   │                       #   (window.nxoConfirm / window.nxoNotify — styled
│   │                       #   replacements for confirm()/alert(); host divs here,
│   │                       #   logic in app.js confirmHost()/toastHost()) + a
│   │                       #   bfcache pageshow→reload script so pages restored
│   │                       #   via the browser back/forward button re-sync with
│   │                       #   the server
│   ├── login.html          # Standalone login page (own minimal copy of the design
│   │                       #   tokens; username/password form with a hidden `next`
│   │                       #   field, generic error flash, first-start admin hint)
│   ├── index.html          # Dashboard as four labeled sections: Statistics (stat cards
│   │                       #   with label + icon in a shared head row, value below),
│   │                       #   Projects (card grid), Firewalls (card grid), Users (the
│   │                       #   account table + Add user modal — one userManagement()
│   │                       #   Alpine instance per section, its x-data embeds the signed-in
│   │                       #   username as JSON → single-quoted attribute); hero
│   │                       #   holds the New Project / New Firewall actions; hosts both
│   │                       #   creation wizards (modals) + the edit-firewall modal
│   ├── _project_wizard.html  # 3-step project creation wizard (basic data → attach
│   │                       #   existing firewalls — with or without an imported
│   │                       #   configuration → validate + open project page)
│   ├── _firewall_wizard.html # 3-step firewall creation wizard (step dots = system
│   │                       #   `.step-dot` pills; basic data → import w/ connectivity
│   │                       #   check + `.progress-bar` progress → create / skip import;
│   │                       #   on import failure: Back to step 2 + "Import configuration"
│   │                       #   retry without re-creating the firewall; "Done — go to
│   │                       #   dashboard" hidden while the retry is pending; the step-3
│   │                       #   action label is a single x-text span; errors as
│   │                       #   `flash flash-error`, import success as `flash flash-success`)
│   ├── _firewall_edit.html   # Edit-firewall modal (wizard step-1 fields; loads current
│   │                       #   values incl. credentials, PATCH /api/firewalls/<id>)
│   ├── project.html        # Project detail: hero with the project name, the description
│   │                       #   below it, the trash-can icon (the project's deleted objects
│   │                       #   → /trash?project_id=) and the Edit Project button (no back
│   │                       #   link — the Dashboard link lives in the top bar only); an info
│   │                       #   alert (`.flash flash-info`) above Statistics (modify /
│   │                       #   adjust / select / remove objects before exporting
│   │                       #   selectively); four labeled sections:
│   │                       #   Statistics (stat cards with label + icon head row, Last Import
│   │                       #   as monospace `stat-value-sm`), Firewalls (white "All firewalls" type-chip panel
│   │                       #   + one card per firewall with a clickable type-chip grid +
│   │                       #   total link), Manage firewalls (renamed from "Attached
│   │                       #   Firewalls": firewall table Import / View Objects / Remove
│   │                       #   + the "Attach existing firewall" form at the bottom of the SAME
│   │                       #   card), Export configuration (LAST section: Export Configuration
│   │                       #   button in the section head + table of the previous generated /
│   │                       #   pushed configuration files — File/Pushed badge, destination,
│   │                       #   objects per type, size, date — each downloadable)
│   ├── _project_nav.html   # Conditional navbar partial (Dashboard / Objects) on the
│   │                       #   shared `.nav-link` class
│   ├── project_edit.html   # Edit project name/description
│   ├── export.html         # Export page: per-firewall/type + modified stats, 4-step wizard
│   │                       #   (type step: Select all / Tagged only / Clear shortcuts,
│   │                       #   per-type Tagged only / All objects scope)
│   ├── import.html         # Standalone import wizard (firewall → source/types → review);
│   │                       #   back link + Back button return to the project page (when
│   │                       #   opened from it) or the dashboard; Select all / Clear
│   │                       #   shortcuts (same style as the export wizard) + import
│   │                       #   history panel (GET /api/import/records); a new import
│   │                       #   replaces the previous one (previous import's objects
│   │                       #   deleted first, confirmed in the result panel); after a
│   │                       #   successful import the review step shows the result + a
│   │                       #   "Back to project" button (→ the origin page — no
│   │                       #   "Import again")
│   ├── objects.html        # Scoped object list: type-specific columns, add/modify/delete
│   │                       #   staging, Validate (commit — soft pulsing glow while staged
│   │                       #   changes wait), pagination 10-500, status filter (Included in
│   │                       #   the export / Modified / Deleted), "In export" tag column +
│   │                       #   selection checkboxes (Include / Remove from export buttons
│   │                       #   apply the selection). Deleted objects stay in the list
│   │                       #   (greyed-out row + "deleted" badge), their Delete button
│   │                       #   becomes a Restore button. Modify modal: visual payload form
│   │                       #   (one field per payload key: text/number/boolean/list/JSON +
│   │                       #   "Re-sync from Payload JSON") + Payload JSON textarea;
│   │                       #   Validate = stage + commit the single change; project-scoped
│   │                       #   view: the project's trash-can icon in the page header
│   │                       #   (→ /trash?project_id=) and no Trash in the nav bar
│   │                       #   (Dashboard / Objects, as on the project page)
│   ├── trash.html          # Trash bin, two separate trashes: the dashboard view
│   │                       #   lists Projects / Firewalls only; ?project_id= (the project
│   │                       #   trash can) lists that project's deleted objects only —
│   │                       #   restore in both; the project trash can also has
│   │                       #   permanent delete (row checkboxes + Delete selected /
│   │                       #   Delete all with confirm → POST
│   │                       #   /api/trash/permanent-delete) + a search box showing
│   │                       #   every deleted object and filtering them (name / type /
│   │                       #   firewall / project / reason)
│   ├── firewalls.html      # Firewall dashboard (card grid + New Firewall wizard modal
│   │                       #   + edit-firewall modal; per-card Objects / Import / Edit /
│   │                       #   Delete; deep link ?edit=<id> opens the edit modal)
│   └── projects.html       # Full-page project list + create form
├── files/                  # Reference samples of the config file types accepted by Import
│   ├── FGT_CHATEAUDUN_2_7-2_1761_202610011359.conf  # FortiGate (FortiOS 7.x) full CLI config (778 KB)
│   ├── MT-FGTVYV324082026.xml                       # Palo Alto (PAN-OS 11.1) XML device export, minified (1.95 MB)
│   ├── MT-FGTVYV324082026-pretty.xml                # same export, pretty-printed (3.84 MB)
│   └── MT-FGTVYV324082026-set.txt                   # same config, set (show) format export (2.54 MB)
├── static/js/app.js        # Alpine components: dashboard (incl. totalObjects() for
│   │                       #   the "Total Objects" stat card), firewallDashboard,
│   │                       #   projectWizard, firewallWizard, firewallEdit, objectTable,
│   │                       #   exportWizard, importWizard (origin-aware Back, Select all / Clear,
│   │                       #   import history), trashBin (object-trash search),
│   │                       #   userManagement (dashboard Users section: list, add user
│   │                       #   modal, one-shot generated-password notice with copy,
│   │                       #   reset password / enable-disable / delete),
│   │                       #   confirmHost + toastHost (global confirmation dialog +
│   │                       #   toast stack registered on window.nxoConfirm /
│   │                       #   window.nxoNotify)
├── instance/swissknife.db  # SQLite database (tables auto-created + migrated at startup)
├── instance/users.db       # SEPARATE SQLite database for the authentication accounts
│   │                       #   (User model via SQLALCHEMY_BINDS "users"; gitignored)
├── instance/exports/       # Generated/pushed configuration files (export records;
│   │                       #   created on first export, ignored by git)
├── .gitignore              # ignores .venv/, __pycache__, QA/,
│   │                       #   instance/swissknife.db, instance/users.db,
│   │                       #   instance/exports/, files/
├── QA/                   # STRICT location for every created test file and
│   │                     #   generated log (test scripts, background-server
│   │                     #   launcher + run logs, generated artifacts, API
│   │                     #   probes) — see
│   │                     #   [§9](#9-qa-folder-files-created-during-the-testing-phase)
└── requirements.txt        # + requests (connectivity checks, REST retrieval/push)
```

Key design notes:

- `create_app()` calls `db.create_all()` **after** the blueprint imports
  (models register their tables in the metadata at import time), then runs the
  one-off SQLite migrations (`firewalls.project_id` nullable, firewall
  `model`/`auth_mode`/`api_token` columns, `config_objects.project_id`
  nullable, `config_objects.export_included`, `projects`/`firewalls`
  `is_deleted`+`deleted_at`, `trash` rebuilt multi-type) so existing databases
  evolve in place.
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
- **Alpine is pinned to 3.17.5** (`unpkg.com/alpinejs@3.17.5/…`): the floating
  `@3.x.x` URL resolved to 3.17.5, which changed two `x-init` behaviors and
  silently broke the confirm/toast host bindings (root cause of the
  2026-11-26 dead delete/modify/restore buttons) — (1) `this` inside `x-init`
  is **window**, not the component proxy (a `this.ask(options)` binding looked
  up `window.ask` and failed), and (2) an `x-init` expression whose value is
  a **function is invoked once with no arguments** (an inline
  `window.nxoConfirm = (options) => ask(options)` therefore called `ask()` on
  every page load — phantom dialog with default content, real requests queued
  behind it). The hosts therefore bind with
  `x-init="(function () { window.nxoConfirm = (options) => ask(options); return null; })()"`:
  the IIFE returns `null` (nothing is auto-invoked) and `ask` / `notify` are
  **bare identifiers**, which still resolve through the component scope with
  the proxy as implicit `this` (so `$nextTick` / `$refs` keep working inside
  `ask()`). Keep the pin when upgrading Alpine, and re-verify `x-init`
  semantics after any bump.
- **The users database is a separate file** (`instance/users.db`): Flask-SQLAlchemy
  3.0.5 refuses two `SQLAlchemy()` instances on one app, so the `User` model
  uses the same `db` extension with `__bind_key__ = "users"` +
  `SQLALCHEMY_BINDS = {"users": …}` in the factory; the existing
  `db.create_all()` creates the `users` table in that file automatically
  (it defaults to `bind_key="__all__"`).
- **Auth guards run per request** (`app.before_request`): page routes redirect
  anonymous browsers to `/login?next=<path>` (the original target is restored
  after signing in; `next` is validated to a relative, same-origin path),
  `/api/*` routes answer JSON `401`. Static files, unknown paths (404) and
  `/login` + `/logout` + `/api/auth/login` are exempt. The session cookie is
  HttpOnly + SameSite=Lax, the session lives 8 h, and login clears the session
  before storing the new identity (no session fixation).

---

## 3. How to run

```bat
:: from the repo root (Windows)
.venv\Scripts\activate
pip install -r requirements.txt

:: run (dev server)
.venv\Scripts\python -c "from app.factory import create_app; create_app().run(host='127.0.0.1', port=5000)"
```

Open `http://127.0.0.1:5000` — you are redirected to the **login page**
(`http://127.0.0.1:5000/login`). On the **first start** the user database is
empty: the app creates the initial **`admin`** account and prints its
password to the server console **once** (stored hashed — not recoverable).
Set `SWISSKNIFE_ADMIN_PASS` beforehand if you want a known password. New
accounts are created on the dashboard → **Users** section.

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

Reliable recipe (verified — succeeds on the first attempt). **Every file
this recipe generates (launcher + run logs) goes into `QA/`** — the strict
`QA/`-only rule of [§9](#9-qa-folder-files-created-during-the-testing-phase),
never at the repository root:

1. Create a launcher `QA\_run_server.bat` (the quoting lives inside the
   file, where cmd applies it directly):

   ```bat
   @echo off
   cd /d C:\Users\hedhl\source\repos\NXO_Swiss_Knife
   ".venv\Scripts\python.exe" -c "from app.factory import create_app; create_app().run(host='127.0.0.1', port=5000)"
   ```

2. Launch it with **absolute** redirect paths:

   ```powershell
   Start-Process -FilePath 'C:\Users\hedhl\source\repos\NXO_Swiss_Knife\QA\_run_server.bat' -WorkingDirectory 'C:\Users\hedhl\source\repos\NXO_Swiss_Knife' -RedirectStandardOutput 'C:\Users\hedhl\source\repos\NXO_Swiss_Knife\QA\_server_log.txt' -RedirectStandardError 'C:\Users\hedhl\source\repos\NXO_Swiss_Knife\QA\_server_err.txt' -WindowStyle Hidden -PassThru
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

4. When done: stop it by port owner and delete the temporary files from
   `QA/` — they are disposable test-round artifacts (strictly `QA/`, see
   [§9](#9-qa-folder-files-created-during-the-testing-phase); `QA/` contents
   may be wiped after the test round):

   ```powershell
   $c = Get-NetTCPConnection -LocalPort 5000 -State Listen | Select-Object -First 1
   Stop-Process -Id $c.OwningProcess -Force
   Remove-Item .\QA\_run_server.bat, .\QA\_server_log.txt, .\QA\_server_err.txt
   ```

Environment variables (all optional):

| Variable | Purpose | Default |
|---|---|---|
| `SWISSKNIFE_SECRET` | Flask secret key | `dev-secret-change-me` |
| `DATABASE_URL` | SQLAlchemy URI of the main database | `sqlite:///swissknife.db` (in `instance/`) |
| `USERS_DATABASE_URL` | SQLAlchemy URI of the **separate users database** | `sqlite:///users.db` (in `instance/`) |
| `SWISSKNIFE_ENABLE_PUSH` | `1` to enable the mock push URL | off |
| `SWISSKNIFE_ADMIN_USER` / `SWISSKNIFE_ADMIN_PASS` | initial account bootstrapped on first start (used only when the users DB is empty; without `SWISSKNIFE_ADMIN_PASS` a random password is generated and printed once) | `admin` / (generated) |
| `SWISSKNIFE_SESSION_SECURE` | `1` marks the session cookie `Secure` (production / HTTPS only — off for local HTTP dev) | `0` |

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
| Dashboard: exhaustive projects + firewalls | `views.dashboard`, `index.html`, `dashboard()` | Three labeled sections with ruled section heads (kicker + title + actions): **Statistics** (icon stat cards), **Projects** (card grid with per-project firewall rows), **Firewalls** (card grid); the hero carries the two main actions (New Project / New Firewall); both creation wizards, `GET /api/projects` + `GET /api/firewalls` |
| Firewall creation wizard (3 steps) | `_firewall_wizard.html`, `firewallWizard()`, `POST /api/firewalls` | Step 1 basic data (name, vendor, **model**, mgmt IP, **login/password or API token**, description); step 2 import source (file upload or REST API) with **Check connectivity** (`POST /api/connectivity`) ; step 3 create + **skip import** option; import runs after create with XHR upload progress or `/api/import/stream` NDJSON progress; **on import failure (e.g. "No configuration file chosen") a Back button returns to step 2** and the step-3 button becomes **Import configuration** — the created firewall is re-imported, never re-created; **while a retry is pending the "Done — go to dashboard" button is hidden** (`x-show="!importError"`, only Back + Import configuration apply); the step-3 action label is a single deterministic `x-text` span (per-state `x-show` spans could be left stale by Alpine's delayed show/hide scheduling, which blanked the "Import configuration" label after a failed no-file import) |
| Project creation wizard (3 steps) | `_project_wizard.html`, `projectWizard()`, `POST /api/projects` | Step 1 name/description; step 2 attach existing firewalls (**any firewall — also without an imported configuration**, marked "no configuration yet"; "create a firewall first" suggestion when none exist); step 3 validation summary → opens the new project page immediately; attaching moves the firewall (objects follow via `set_project()`) |
| Project cards: Open / Delete | `index.html`, `dashboard()` | Delete = `confirm()` ("Move … to the trash?") + **soft delete** — the project/firewall lands in the Trash (restorable; its firewalls + objects follow); **the list refreshes in place** (the POST follows the 302, final 200 = success, `reloadAll()` re-fetches both lists — no page reload); the same `deleteEntity` pattern applies to firewall deletes on the dashboard and the `/firewalls` page (`firewallDashboard()`) |
| Project detail page + conditional navbar | `project_detail`, `project.html`, `_project_nav.html` | Hero: project name, description below it, **trash-can icon button** (that project's deleted objects → `/trash?project_id=<id>`) + Edit Project button — **no back link: the Dashboard link appears in the top bar only**; a blue **pre-export hint above Statistics** (you can modify, adjust, select or remove objects on the object list pages before exporting the configuration selectively); four labeled sections with ruled section heads: **Statistics** (icon stat cards: firewalls, objects, types, **modified**, last import as monospace date), **Firewalls** ("All firewalls" type-chip panel + one card per firewall with a clickable type-chip grid (count click → filtered object list) + clickable nowrap per-firewall total), **Manage firewalls** (renamed from "Attached Firewalls") with the firewall table (per-row Import / View Objects / Remove — the per-row Edit link was removed; edit via the firewall dashboard; the Objects count shows **(N modified)** and, in the same style, **(N deleted)** hints when present) **and the "Attach existing firewall" form at the bottom of the same card** (any active firewall — config-less ones marked "no configuration yet"; firewalls in the trash are not attachable), **Export configuration (LAST section**: the **Export Configuration button in its section head** → `/projects/<id>/export` **+ the table of previous generated/pushed files, each downloadable**); project navbar = Dashboard / Objects (Export removed; the Dashboard link appears in the top bar only) on the shared `.nav-link` class; dashboard navbar = Dashboard / Trash (Firewalls link removed); a project in the trash 404s on its page |
| Project page: previous generated / pushed configuration files (downloadable) | `ExportRecord` (models), `_record_export()` + `GET /projects/<id>/exports/<rid>/download` (views), `POST /api/export/file` / `POST /api/export/push` / legacy `POST /api/export` (routes), `project.html` | Every generated or pushed configuration is persisted to `instance/exports/<id>_<filename>` + an `export_records` row (best-effort, never breaks the export; push stream captures `current_user()` before the request context is gone); the project page's **Export configuration** section lists them newest first (File / Pushed badge, destination, objects per type, size, UTC date) with a **Download** button each (attachment download; flash + redirect when the file is no longer on disk); `instance/exports/` is gitignored |
| Project page: per-row Remove firewall (unassign) | `remove_project_firewall`, `project.html` | `confirm()` dialog; `set_project(None)` — firewall + objects kept; reattach via "Attach existing" |
| Firewall dashboard (card style) | `firewalls_page`, `firewalls.html`, `firewallDashboard()` | Card grid; New Firewall = 3-step wizard modal; per-card Objects / **Import** / **Edit** / Delete; `GET /api/firewalls` adds `project`, `objects_count`, `has_config`, `types_counts`; deep link `?edit=<id>` opens the edit modal |
| Firewall edit modal (change any firewall field) | `_firewall_edit.html`, `firewallEdit()`, `GET/POST/PATCH /api/firewalls/<id>` | Same fields as wizard step 1 (name, vendor, model, mgmt IP, login/password or API token, description); `GET` returns the stored credentials for the form (the list endpoint hides them); empty values clear a field, the inactive credential side clears automatically; optional `project_id` (int/null) reassigns/unassigns and syncs the objects via `set_project()`; friendly error on the `(project_id, name)` unique constraint; Edit buttons on the dashboard + firewall dashboard cards and per row in the project table; list refreshes after save |
| Import shortcut on firewall cards | `firewalls.html`, `index.html`, `project.html` | Per-card **Import** links to `/import?firewall_id=…` — the existing import wizard (file or URL, per-type) starts at the source step; the project page's per-row Import link additionally carries `project_id`, so the wizard's back link + Back button return to the project page (dashboard links keep the dashboard as origin); re-importing upserts the objects and replaces the previous import |
| Import history + replace semantics | `ImportRecord` (models), `GET /api/import/records`, `POST /api/import` + `/api/import/stream`, `import.html`, `importWizard()` | Every import run writes an `ImportRecord` (source, counts, warnings) and the imported objects carry `ConfigObject.import_id` back to it; the import form shows the **Import history** panel of the selected firewall (newest first); **a new import replaces the previous one** — the previous import's objects (with their history + trash rows) are deleted first, confirmed in the result panel ("Previous import removed: N objects"); manually created objects (no import_id) are never touched |
| Project edit page | `edit_project`, `project_edit.html` | Name + description (Flask-WTF `ProjectForm`) |
| Object list (type-specific, staged edits, deleted rows restorable) | `objects_page`, `objects.html`, `objectTable()` | Scoped by navigation context (no project/firewall filters); **columns per object type** from the normalized payloads; add/modify/delete actions **staged client-side**, committed atomically by **Validate** → `POST /api/objects/commit`; `POST /api/objects` for single creates; pagination: total pages, next/prev, rows-per-page 10/15/25/50/100/500; back-to-project link; **status filter dropdown** (All / Included in the export / Modified / Deleted → `GET /api/objects?filter=included|modified|deleted`); **the Validate button pulses a soft glow while staged changes wait to be committed** (`.validate-attention`, quiet micro-interaction, static glow under reduced motion); **"In export" tag column** (badge per tagged row) + **selection checkboxes** (row + page header, tagged rows preselected, **no server call on check/uncheck**) — the selection is applied by the toolbar **Include in the export (N)** / **Remove from export (N)** buttons → `POST /api/objects/export-include` (`include: true/false`); counts = selected rows that will change. **Deleted objects stay in the list** (the list always requests `include_deleted=true`): greyed-out row (`.table-row-deleted`) + red **deleted** badge, their Modify/Delete buttons become a single **Restore** button (`POST /api/objects/<id>/restore`, immediate — no staging); deleted rows can't be edited ("Restore it first") nor tagged for the export. **Modify modal: visual payload form** — one field per payload key (text/number/boolean/one-item-per-line list/JSON textarea; `buildPayloadFields`/`applyPayloadFields`) + "↻ Re-sync from Payload JSON"; the modal **Validate** = stage + commit the single change (list refreshes; on failure the change stays staged for the toolbar); row-level Delete stages the trash move; when scoped by a project, the page header shows the project's **trash-can icon** (→ `/trash?project_id=<id>`) and the nav bar drops **Trash** (Dashboard / Objects, same as the project page) |
| Export page + 4-step wizard | `export_page`, `export.html`, `exportWizard()` | Stats: objects per firewall/type + **modified** per firewall/type; step 1 destination (attached firewalls), step 2 type filter (**Select all / Tagged only / Clear** shortcuts — "Tagged only" selects every type filter in the tagged scope; per-type **Tagged only** / **All objects** radios), step 3 summary + method, step 4 file (progress + download link via `POST /api/export/file` / `GET /api/export/file/<token>`) or push (connection status + Push + streaming progress via `POST /api/export/push`); **the generated configuration spans ALL firewalls in the database** — the destination receives every active object of the selected types, not only its own imported configuration (both file and push go through `_build_config()`); the "Object types to export" counts therefore span every firewall; **Validate & return to project** after success |
| Export (legacy endpoint) | `POST /api/export` | Parser-generated download or mock push (kept for compatibility) |
| Import wizard (file / URL, per-type) | `import_page`, `import.html`, `POST /api/import`, `importWizard()` | Vendor auto-detection (incl. PAN-OS set format). Both parsers store **address, address group, service, service group, security rule, interface, zone**: Fortinet = full FortiOS CLI export (`address`+`address6`, `addrgrp`, `service custom`, `service group`, `policy`, `system interface`, `system zone` or interface `set zone`); Palo Alto = PAN-OS 11.x XML device export (objects directly under `vsys/entry`), older wrapped exports, app-generated `<paloalto>` docs **and** set/`show` format. Samples in `files/`; see [§2](#2-architecture--layout). The source & types step offers **Select all / Clear** shortcuts (same link style as the export wizard's type step) and an **Import history** panel (per selected firewall, `GET /api/import/records`); the **back link** in the header + the **Back button** return to the page the wizard was opened from — the project page when opened from it (`?project_id=`), the dashboard otherwise (on step 1 Back = origin; step 2 = origin when the firewall was preselected, else step 1; step 3 = step 2); **after a successful import** the review step shows the result panel + a primary **Back to project** button (→ the origin page — "Back to dashboard" when the wizard was opened from the dashboard): there is no "Import again" |
| Streaming import with progress | `POST /api/import/stream` | NDJSON progress events (connect/download/parse/import); used by the firewall wizard for REST sources |
| Connectivity check | `POST /api/connectivity` | TCP :443 + vendor API probe (Fortinet `/api?uuid=`, PAN-OS `/api/?type=op`), self-signed TLS handled, used by the firewall wizard and the export push step |
| Trash + restore + permanent delete (objects, firewalls, projects) | `trash_page`, `trash.html`, `/api/trash` + `/api/trash/<id>/restore` + `/api/objects/<id>/restore` + `POST /api/trash/permanent-delete`, `Trash`/`Project`/`Firewall`/`ConfigObject` models, `trashBin()` | Deleted **projects and firewalls** are soft-deleted (cascading into the trash with their firewalls/objects) and restorable; the trash is **separated by level** — the **dashboard trash** (`/trash`, navbar link) lists the entries **per type** (Projects / Firewalls sections, each with counts, deleted date/reason and a Restore button) and each project's **trash can** (`GET /api/trash?project_id=N`, the trash-can icon on the project page) lists **that project's deleted objects** only — **every** deleted object is displayed (the **search box** filters them client-side by name / type / firewall / project / reason, "no match" empty state) plus **permanent delete**: row checkboxes (header checkbox = all visible rows) + **Delete selected (N)** / **Delete all (N)** buttons behind a `confirm()` → the object, its modification history and its trash row are removed from the database (name freed, no restore possible); restoring a project/firewall restores its descendants; a name stays reserved while its project/firewall entry is in the trash (trash-aware error on create/rename) |
| Global styled confirm dialog + toast stack (replacement for confirm() / alert()) | `templates/base.html` (host divs + `.confirm-content` / `.toast-stack` styles), `confirmHost()` + `toastHost()` in `static/js/app.js` | Mounted once per page; every Alpine component calls `window.nxoConfirm({ title, message, confirmLabel, danger })` (returns `Promise<boolean>`; requests made while a dialog is open are **queued and answered in order**; Escape / overlay click cancel; the Cancel button is focused on open so Enter never confirms) or `window.nxoNotify(message, variant, timeout)` (flash-styled toast bottom-right, max 4, auto-dismissing) — used by dashboard/firewall deletes, object modify/discard/delete/restore, trash restore + permanent delete, the project-page Remove-firewall button and user management. The `x-init` bindings respect the Alpine 3.17.5 constraints documented in [§2 design notes](#2-architecture--layout) (IIFE returning `null` + bare-identifier calls, pinned Alpine version) |
| Page content sync on browser back/forward (bfcache) | `templates/base.html` (`pageshow` listener in `<head>`) | A page restored from the browser back/forward cache (e.g. back to a project or the dashboard from the trash) would otherwise keep its stale rendered state; on a `pageshow` with `event.persisted`, the page reloads so the content re-syncs with the server |
| REST API + error handlers | `app/api/routes.py`, `errors.py` | Projects (+`firewall_ids` attach), firewalls (+detail/update `GET/POST/PATCH /api/firewalls/<id>`), import (+stream), objects (GET/POST/commit), trash, export (file/push), connectivity; `current_user()` now returns the signed-in session username |
| **Authentication (local user accounts, separate users DB)** | `app/auth.py`, `User` model in `app/models.py` (`__bind_key__="users"` → `instance/users.db` via `SQLALCHEMY_BINDS`), `templates/login.html`, `/login` + `/logout` + `/api/auth/login` (JSON) + `/api/auth/me` + `/api/users` (list / create / PATCH display_name·is_active·generate_password·password / DELETE), `ensure_admin_user()` in the factory, `userManagement()` in app.js, the dashboard's **Users** section | **Session login with user + password** for every page and API route (pages → `/login?next=…` redirect, the original page is restored after signing in; API → JSON 401; static files + 404s + the login routes stay open). Best practices applied: passwords hashed with `werkzeug.security` (scrypt + random per-password salt, never stored/computed in plain text), generic "Invalid username or password" answer, **timing equalization** (a dummy hash check when the user does not exist), 0.5 s delay + log line on failed logins, HttpOnly + SameSite=Lax session cookie, 8 h session lifetime, session cleared before the login is stored (no fixation), `next` validated to a relative same-origin path, logout POST-only (no forced-logout via link), username validated (2-64 chars `[A-Za-z0-9._-]`, unique), password 8-128 chars, the user list never returns the hash. **First start bootstraps the `admin` account** (name `SWISSKNIFE_ADMIN_USER`, password `SWISSKNIFE_ADMIN_PASS` or a random one **printed once** to the console). **User management on the dashboard** (Users section, `userManagement()`): account table (username + "you" badge, display name, active/disabled badge, last login, created) + **Add user** modal (password optional → server-generated, shown **once** in a warning notice with a copy button) + per-row **Reset password** (generated, shown once) / **Enable / Disable** / **Delete** behind confirms; guards: no deleting or disabling **your own** account, and the **last active account** can neither be disabled nor deleted (defense in depth). Navbar shows the signed-in username + **Sign out** on every page; the login page is standalone (same design system) with the first-start admin hint. The old `/api/auth/login` env-var placeholder is replaced by the same URL validating against the users DB (API clients can set the session programmatically) |
| DB schema auto-creation + migrations | `factory.create_app` | `db.create_all()` + one-off migrations: `firewalls.project_id` nullable, `firewalls.model`/`auth_mode`/`api_token`, `config_objects.project_id` nullable (table rebuild), `config_objects.export_included`, `projects`/`firewalls` `is_deleted`+`deleted_at`, `trash` rebuilt multi-type, **`import_records` table** (new) + `config_objects.import_id` (nullable column) |
| Demo data seed | `instance/swissknife.db` | "Demo Project" + 2 demo firewalls |
| Vector DB (standalone project) | `C:\Users\hedhl\source\repos\Vector_DB` | indexes this repo **including the `files/` sample configs** (`.conf`/`.xml`/`.txt`) and the frontend (`templates/*.html` + `static/js/app.js`); **chunker v2**: token-accurate (tiktoken) 400/500-token chunks, 0% overlap, Python split at function granularity (Tree-sitter AST, classes split per method), context headers embedded with each chunk, non-source files excluded; **retrieval**: top-10 (hard cap 12) + cosine threshold + dedup + **7,000-token strict budget** enforced before the prompt; file-scoped queries via `--where file=...` — the only search path for the multi-MB samples, see [§7](#7-vector-db-integration-token-efficient-development) |

### Planned (suggested backlog)

| Feature | Notes |
|---|---|
| 📋 Login rate limiting / lockout | Currently: 0.5 s delay + log per failed attempt; no persistent per-account/per-IP lockout |
| 📋 User roles / permissions | All accounts have the same rights; guard logic is in place to build on |
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

- **Login rate limiting is basic.** A 0.5 s delay + a log line per failed
  attempt (plus timing equalization and a generic error message), but no
  persistent lockout per account or IP — fine for a local tool, add a lockout
  before exposing the app on a network.
- **Session cookie `Secure` is off by default** (local HTTP dev). Set
  `SWISSKNIFE_SESSION_SECURE=1` when running behind HTTPS.
- **All users are administrators.** There are no roles/permissions yet —
  every signed-in account can manage every other account (self-deletion / the
  last-active-account guards are the only restrictions).
- **The initial admin password is printed once** (console/log) when the users
  DB is empty and `SWISSKNIFE_ADMIN_PASS` is not set — if the process output
  is lost, the password is not recoverable (it is stored hashed); set the
  env var for reproducible setups, or delete `instance/users.db` to start
  over.
- **`db.create_all()` at startup** — fine for dev, but schema evolution relies
  on the one-off migrations in `factory.py` (no Alembic): `firewalls.project_id`
  nullable, `firewalls.model`/`auth_mode`/`api_token` columns,
  `config_objects.project_id` nullable (table rebuild),
  `config_objects.export_included`, `projects`/`firewalls` `is_deleted`+
  `deleted_at`, `trash` rebuilt multi-type (`item_type` + `project_id`/
  `firewall_id`).
- **Trash entries keep their names reserved — for projects and firewalls.**
  Deleted **objects** can now be permanently deleted from their project's
  trash can (object + modification history + trash row removed, name freed),
  but while a project/firewall is in the trash its unique name stays taken
  (creating/renaming a project or a same-named firewall in the same project is
  rejected with a trash-aware error until the entry is restored). Unassigned
  firewalls never collide on name (SQLite treats NULL `project_id`s as
  distinct).
- **`config_objects.project_id` is nullable.** Objects imported into an
  unassigned firewall have `project_id = NULL` until the firewall is attached
  (attach/remove syncs the objects via `Firewall.set_project()`).
- **Staged object edits are all-or-nothing.** `POST /api/objects/commit`
  applies the whole batch in one transaction; any validation/constraint error
  rolls everything back (the staged changes stay in the browser).
- **Tailwind via CDN** — dev-only warning shown in the console; not a
  production build.
- **Alpine is loaded from a floating CDN URL range** — it is now pinned to
  3.17.5, but a future unpinned bump could silently change `x-init`
  semantics again (3.17.5 already broke the confirm/toast bindings); re-verify
  after any Alpine upgrade (see §2 design notes).
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
- **Export file artifacts are in-memory (temporary link only).** The
  temporary download links (`/api/export/file/<token>`) live in the process
  and expire after 1 hour or on restart — re-generate if a link stops
  working. The **previous files themselves are persistent**: every generated
  or pushed configuration is also kept in `instance/exports/` (+
  `export_records`) and stays downloadable from the project page's **Export
  configuration** section.
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
  `.py`/`.js`/`.html`/`.css`/`.conf`/`.txt`/`.md` — `.md` files are indexed with
  the heading-aware semantic segmenter; Python is split at **function
  granularity via the Tree-sitter AST** — functions and classes stay intact,
  large classes split per method (`Class.method`); skips `__pycache__/`,
  `.venv/`, `.git/`, `node_modules/`, `dist/`, `build/`, `instance/`, `QA/`,
  editor/tool caches, minified assets, source maps, lockfiles **and non-source
  data files** (`.json`, `.csv`, `.db`, binaries, ...); configurable via
  `RAG_SOURCE_ROOT` / `--ext`). Chunks live in its own
  `./.vectordb` (ChromaDB, cosine; local Ollama `nomic-embed-text` embeddings).
- **Chunking (token-accurate):** 400-token target / **500-token hard cap** /
  0% overlap, measured with a real tokenizer (tiktoken, cl100k_base). Every
  chunk carries a prepended context header (`# File: path | Class: X |
  Function: y`) that is embedded with it. A token-boundary safety net
  guarantees the cap even on minified single-line files (the previous
  word-based chunker produced 47,568-token chunks from the `files/` samples —
  the root cause of the ~262k-token prompt overflow).
- **Token saving:** retrieval returns only the top-k chunks (default 10,
  **hard-capped at 12**, cosine >= 0.45, deduplicated), and a **strict token
  budget (default 7,000 tokens)** is enforced right before the prompt is
  built — lowest-scoring chunks are dropped (the best chunk truncated if even
  it alone exceeds the budget), so the prompt context **can never exceed the
  budget**. An unrelated query returns 0 chunks (the prompt says so
  explicitly) so no prompt tokens are wasted.
- **After any chunker change:** wipe and re-index —
  `python index_db.py --rebuild` from the Vector_DB repo (the indexer prints a
  CHUNKER UPDATE PENDING reminder if it detects stale chunks).

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

   The CLI prints the final context size (`context N / 7,000 tokens`) — the
   token budget is enforced before the prompt is built, so the printed prompt
   is always within budget. Feed the printed prompt — or the `prompt` field of
   `POST http://127.0.0.1:5100/api/rag/query` (add `"token_budget": 7000` to
   override) — to the LLM. Only when the query returns no useful information
   (0 relevant chunks, or chunks that do not answer the question) may you fall
   back to reading the file directly.

3. **Implement the change** in this repo (models, views, API, templates,
   `PROJECT.md`).

4. **Re-index afterwards** so the store reflects the new code/docs:

   ```bat
   :: from the Vector_DB repo root
   python index_db.py         :: skips unchanged files; re-embeds only changed ones
   python index_db.py --prune :: optional: drop chunks of files that were deleted
   ```

   (or run the Vector_DB HTTP service and `POST /api/rag/reindex`). **After
   changing the chunking algorithm itself**, unchanged files would keep their
   old chunks — wipe and re-index instead: `python index_db.py --rebuild`
   (the indexer prints a CHUNKER UPDATE PENDING reminder when it detects
   chunks from an older chunker version).

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
| `RAG_TOP_K` | chunks per query (hard cap 12) | `10` |
| `RAG_MIN_COSINE` | similarity threshold | `0.45` |
| `RAG_CHUNK_TARGET_TOKENS` / `RAG_CHUNK_MAX_TOKENS` | chunk target / **hard cap** (tiktoken tokens) | `400` / `500` |
| `RAG_TOKEN_BUDGET` | strict cap on retrieved context per query (tokens) | `7000` |
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
   test suite in the repo. **Every created test file and generated log
   (test scripts, run logs, launcher files, dumps, screenshots, API probes)
   MUST strictly live in the `QA/` folder** — never at the repository root
   or inside `app/`, `templates/`, `static/` or `files/` (stray files at the
   root would be picked up by the next Vector DB re-index) — see
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
- server run logs and console captures from test runs — **including the
  background dev server's launcher + redirect logs** (`QA\_run_server.bat`,
  `QA\_server_log.txt`, `QA\_server_err.txt` from the
  [§3](#3-how-to-run) recipe),
- generated artifacts (exported configuration files, DB dumps, screenshots)
  kept for analysis,
- one-off API probe scripts run against `http://127.0.0.1:5000`.

Rules:

1. **Every created test file and generated log strictly lives in `QA/`** —
   test scripts, run/redirect logs, launcher files, dumps, screenshots and
   API probes alike: **never** at the repository root or inside `app/`,
   `templates/`, `static/` or `files/` — stray files at the root would be
   picked up by the next Vector DB re-index and pollute the source tree.
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
| `qa_server.ps1` (or `QA\_run_server.bat` + `QA\_server_log.txt` / `QA\_server_err.txt`) | Start/stop the dev server in the background + fast TCP port probe — the recipe from [§3](#3-how-to-run), adapted for a test round; launcher and logs strictly in `QA/` |
| `qa_wizard_flows.md` (notes) | Check-list of obscura sessions: firewall/project wizards, staged edits + Validate, trash restore, export wizard |
