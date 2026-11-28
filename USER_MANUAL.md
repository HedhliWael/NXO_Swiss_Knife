# NXO Swiss Knife — User Manual

> *A local web tool to manage firewall configuration objects — Palo Alto & Fortinet.*
> Generated from `PROJECT.md` (the project's living documentation).

---

## 1. Project description

**NXO Swiss Knife** is a **local web application for managing firewall configuration objects**, currently supporting **Palo Alto (PAN-OS)** and **Fortinet (FortiOS)**. It runs entirely on your machine — no cloud services are involved.

Work is organized around three levels:

| Level | What it is |
|---|---|
| **Project** | A container grouping the work of a team or customer |
| **Firewall** | Belongs to a project; has a vendor, model, management IP and optional API credentials (login/password or API token) |
| **Configuration object** | Addresses, address groups, services, service groups, security rules, interfaces and zones — imported from firewall configuration files, normalized into JSON, fingerprinted and tracked with a full modification history |

---

## 2. How it works

### The three-step web flow

1. **Dashboard** — statistics plus exhaustive lists of projects and firewalls; entry point for the creation wizards and user management.
2. **Project view** — per-firewall / per-type object counts (clicking a count opens the filtered object list), staged add/modify/delete actions committed atomically by the **Validate** button, firewall attach/remove, and an export section listing previously generated configuration files.
3. **Export** — a 4-step wizard: destination firewall → object types (*Select all / Tagged only / Clear*) → summary + method → download of a vendor-specific config file or API push with streaming progress.

### Wizards

- **Firewall creation (3 steps):** basic data → import configuration (file upload or REST URL, *Check connectivity* button, progress bars; the import can be skipped) → create. If the import fails, a Back button returns to step 2 and retries — the firewall is re-imported, never re-created.
- **Project creation (3 steps):** name + description → attach existing firewalls → validation summary, then the new project page opens immediately.

### Import

Sources: **file upload** or **remote URL**, with vendor auto-detection. Accepted formats — reference samples of each are in `files/`:

| Vendor | Format | Extension |
|---|---|:---:|
| Fortinet | Full CLI config export (FortiOS) | `.conf` |
| Palo Alto | PAN-OS XML device export (minified or pretty-printed) | `.xml` |
| Palo Alto | set / `show` format export | `.txt` |

> **Upsert semantics** — objects are created/updated per `(firewall, object type, name)`; every change is written to the modification history. Each import run is recorded as an *import record*; a new import **replaces** the previous one (the previous import's objects are deleted first).

### Trash & restore

Soft delete with reason for **objects, firewalls and projects**, restorable at any time (restoring a project/firewall brings its descendants back). The trash is separated by level: the dashboard trash lists deleted projects/firewalls; each project has its own trash can listing that project's deleted objects, with search and permanent delete.

### Authentication & users

Local user accounts stored in a **separate database** (`instance/users.db`). Session login guards every page and API route. User management lives on the dashboard: add users, reset passwords, enable/disable, delete.

---

### Running the application

Two possibilities:

#### 1. Run locally (source code from GitHub)

Clone the repository, install the dependencies and start the dev server:

```bat
git clone https://github.com/HedhliWael/NXO_Swiss_Knife.git
cd NXO_Swiss_Knife

:: create + activate a virtual environment (Windows, Python 3.13)
py -3.13 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

:: run (dev server)
.venv\Scripts\python -c "from app.factory import create_app; create_app().run(host='127.0.0.1', port=5000)"
```

Open `http://127.0.0.1:5000` — you are redirected to the login page.

> **First start** — an `admin` account is created and its password printed **once** to the console (or set `SWISSKNIFE_ADMIN_PASS` beforehand).

#### 2. Use the hosted instance (Render)

A temporary deployment is available at <https://nxo-swiss-knife.onrender.com> — just open it in a browser and sign in; no installation required.

---

## 3. Technology stack (the application)

| Layer | Technology |
|---|---|
| Web framework | Flask 2.3.3 |
| ORM / database | Flask-SQLAlchemy + SQLAlchemy, SQLite (`instance/swissknife.db` main DB **+** separate `instance/users.db`) |
| Authentication | Flask session login; passwords hashed with werkzeug (scrypt) |
| Forms / CSRF | Flask-WTF / WTForms |
| Frontend JS | Alpine.js 3.17.5 (CDN, pinned) |
| Styling | Tailwind CSS (CDN build — dev only) |
| Runtime | Python 3.13 |

---

## 4. Tools used for its creation (AI-assisted development)

The project was developed with **LLM assistance** through a fully local **RAG pipeline**, designed to keep prompts small and token-efficient:

- **Vector DB** — the companion repo `Vector_DB` hosts a **ChromaDB** vector store (cosine similarity) that indexes this entire repository: Python code, JS/HTML/CSS frontend, documentation *and* the multi-MB sample firewall configs.
- **Embeddings & LLM server** — **Ollama** running locally with the `nomic-embed-text` embedding model; no internet is needed at query time.
- **RAG pipeline** — a token-accurate chunker (tiktoken: 400-token target / 500 hard cap, Tree-sitter AST splitting so functions and classes stay intact), context headers embedded with each chunk, and per-chunk source line ranges stored as metadata. Retrieval returns the top-k chunks (default 10, hard cap 12) above a cosine threshold of 0.45, deduplicated, under a **strict 7,000-token budget** enforced before the prompt is built.
- **Development workflow** — for every change: query the Vector DB first (mandatory), use the returned line ranges as read/write cursors for precise edits, implement the change, then re-index (`python index_db.py`) so the store reflects the new code.

> The result: the LLM only ever sees the relevant lines of a large codebase — never whole files. Faster, cheaper and more accurate changes.
