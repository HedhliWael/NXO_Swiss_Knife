# NXO Swiss Knife — Entry Point

> **Read this file first.** It is the compact front door to the repository: a
> summary of [`PROJECT.md`](./PROJECT.md) plus the mandatory rules for
> retrieving detailed information from the Vector DB instead of reading whole
> files. For change history see [`CHANGELOG.md`](./CHANGELOG.md).

---

## 1. What this project is

**NXO Swiss Knife** is a local, multi-project web tool (Flask + SQLite) for
managing firewall configuration objects — currently **Palo Alto** and
**Fortinet**. Work is organized in three levels:

- **Projects** — containers grouping the work of a team/customer.
- **Firewalls** — belong to a project; vendor, management IP, optional API credentials.
- **Configuration objects** — imported from firewall config files (address,
  address group, service, service group, security rule, interface, zone),
  normalized into JSON payloads with full modification history.

Core flow: **Dashboard → Project view (staged edits + Validate) → Export**
(vendor-specific config file or API push). Multi-step Alpine.js wizards for
firewall/project creation; import from file upload or remote URL via vendor
parsers; soft-delete trash with restore (objects, firewalls, projects); local
user authentication in a separate `users.db`; REST API + browser UI.

### Stack (short)

| Layer | Technology |
|---|---|
| Web / ORM | Flask 2.3.3 · Flask-SQLAlchemy 3.0.5 · SQLite (`instance/swissknife.db` **+** separate `instance/users.db`) |
| Frontend | Alpine.js **pinned to 3.17.5** (CDN) · Tailwind CSS (CDN, dev only) |
| Auth | Flask session login, werkzeug scrypt hashes, per-request guard |
| Python | 3.13 — `.venv` at the repo root |

### Where things live (short map)

- `app/` — Flask app: `factory.py`, `models.py`, `auth.py`, `views.py`,
  `api/routes.py`, `vendors/` (Palo Alto / Fortinet parsers)
- `templates/` + `static/js/app.js` — browser UI (Alpine components)
- `files/` — multi-MB reference config samples (FortiGate `.conf`, PAN-OS `.xml` / `.txt`)
- `instance/` — SQLite DBs + generated exports (gitignored)
- `QA/` — disposable test scripts/logs (strictly here, never at the repo root)

---

## 2. How to run (short)

```bat
:: from the repo root (Windows)
.venv\Scripts\activate
pip install -r requirements.txt
.venv\Scripts\python -c "from app.factory import create_app; create_app().run(host='127.0.0.1', port=5000)"
```

Open `http://127.0.0.1:5000` → login page. On first start an **`admin`** account
is bootstrapped (password printed once, or set `SWISSKNIFE_ADMIN_PASS`).
Full details, env vars and the background-server recipe:
[`PROJECT.md` §3](./PROJECT.md#3-how-to-run).

---

## 3. Rule — check the Vector DB for extensive information

The companion **MyRAG** project (`C:\Users\hedhl\source\repos\MyRAG`)
indexes this repository (ChromaDB collection `swissknife`, local Ollama
`nomic-embed-text`). It is the primary source of detailed context — use it
instead of reading whole files.

### Mandatory rules

1. **Query the Vector DB BEFORE reading any file of this repository.** Direct
   file reading is allowed only when a query returns no useful information
   (0 relevant chunks, or chunks that do not answer the question) — no
   exception for precise edits: query first, then read.
2. **Use the returned line ranges as your read/write cursor.** Every chunk
   carries its 1-based source range (`line_start` / `line_end`, printed as
   `file [section] (lines X-Y)`). Read or edit exactly those lines — never
   re-read a whole file or re-locate code the query already located.
3. **For the sample configs in `files/`, the Vector DB is the ONLY search
   path** (multi-MB files): always add a `--where "file=files/..."` filter.
4. **After any change to code or documentation, re-index:** from the MyRAG
   repo run `python index_db.py` (`--prune` if files were deleted; `--rebuild`
   after a chunker change).

### How to query

Ollama must be running (start command and full workflow:
[`PROJECT.md` §7](./PROJECT.md#7-vector-db-integration-token-efficient-development)):

```bat
:: from C:\Users\hedhl\source\repos\MyRAG, with its venv activated
python rag_query.py "How does the export flow work?"
python rag_query.py "What validation rules does ProjectForm implement?" --where "file=app/forms/project_form.py"
python rag_query.py "Which address objects does the Chateau-dun firewall define?" --where "file=files/FGT_CHATEAUDUN_2_7-2_1761_202610011359.conf"
```

The CLI prints each chunk's file, section and line range plus the final context
size (strict 7,000-token budget; top-k default 10, hard cap 12, cosine ≥ 0.45).
HTTP alternative: `POST http://127.0.0.1:5100/api/rag/query` with body
`{"query": "...", "where": {"file": "app/models.py"}}`.

Full store documentation (indexing options, env vars, chunking details):
[`MyRAG\README.md`](C:\Users\hedhl\source\repos\MyRAG\README.md).

> Note: this file lives at the repo root, so it is picked up by the next
> Vector DB re-index and becomes queryable like every other document.

---

## 4. Pointers into PROJECT.md

| Topic | Section |
|---|---|
| Full description & stack | §1 |
| Architecture, file map, design notes (Alpine pinning, users-DB bind, auth guards) | §2 |
| Run instructions + background-server recipe | §3 |
| Changelog location | §4 → `CHANGELOG.md` |
| Feature tracking (done / planned) | §5 |
| Known issues & technical debt | §6 |
| Vector DB workflow details | §7 |
| Maintenance rules (source of the rules in §3 above) | §8 |
| QA folder rules | §9 |
