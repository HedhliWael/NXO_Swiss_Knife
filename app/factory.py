import os

from flask import Flask

from .extensions import db


def _ensure_firewalls_project_nullable():
    """One-off migration for existing SQLite databases.

    ``firewalls.project_id`` became nullable so a firewall can be removed
    from a project without being deleted. SQLite cannot drop a NOT NULL
    constraint with ALTER TABLE, so the table is rebuilt when the stored
    schema is still NOT NULL. Fresh databases are created nullable by
    ``db.create_all()`` and skip this entirely.
    """
    raw = db.engine.raw_connection()
    try:
        cursor = raw.cursor()
        cursor.execute("PRAGMA table_info(firewalls)")
        columns = cursor.fetchall()
    finally:
        raw.close()

    if not columns:
        return

    # Rows look like (cid, name, type, notnull, dflt_value, pk).
    if not any(
        name == "project_id" and notnull for _, name, _, notnull, _, _ in columns
    ):
        return

    raw = db.engine.raw_connection()
    try:
        cursor = raw.cursor()
        cursor.execute("PRAGMA foreign_keys=OFF")
        cursor.execute("BEGIN")
        cursor.execute(
            """
            CREATE TABLE firewalls_new (
                id INTEGER NOT NULL,
                project_id INTEGER,
                name VARCHAR(120) NOT NULL,
                vendor VARCHAR(32) NOT NULL,
                management_ip VARCHAR(45),
                api_username VARCHAR(120),
                api_password TEXT,
                description TEXT,
                last_sync_at DATETIME,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                PRIMARY KEY (id),
                FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE CASCADE
            )
            """
        )
        cursor.execute(
            """
            INSERT INTO firewalls_new (
                id, project_id, name, vendor, management_ip, api_username,
                api_password, description, last_sync_at, created_at, updated_at
            )
            SELECT
                id, project_id, name, vendor, management_ip, api_username,
                api_password, description, last_sync_at, created_at, updated_at
            FROM firewalls
            """
        )
        cursor.execute("DROP TABLE firewalls")
        cursor.execute("ALTER TABLE firewalls_new RENAME TO firewalls")
        cursor.execute(
            "CREATE UNIQUE INDEX uq_firewalls_project_name"
            " ON firewalls (project_id, name)"
        )
        cursor.execute(
            "CREATE INDEX ix_firewalls_project_id ON firewalls (project_id)"
        )
        cursor.execute("CREATE INDEX ix_firewalls_vendor ON firewalls (vendor)")
        cursor.execute("COMMIT")
    except Exception:
        try:
            cursor.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        cursor.execute("PRAGMA foreign_keys=ON")
        raw.close()


def _ensure_firewall_auth_columns():
    """One-off migration for existing SQLite databases.

    ``firewalls.model``, ``firewalls.auth_mode`` and ``firewalls.api_token``
    were added for the multi-step firewall wizard (model + login/password or
    API-token authentication). SQLite ALTER TABLE can only add nullable
    columns, which is exactly what these are, so no table rebuild is needed.
    """
    raw = db.engine.raw_connection()
    try:
        cursor = raw.cursor()
        cursor.execute("PRAGMA table_info(firewalls)")
        columns = {name for _, name, _, _, _, _ in cursor.fetchall()}
    finally:
        raw.close()

    if not columns:
        return

    wanted = {
        "model": "VARCHAR(120)",
        "auth_mode": "VARCHAR(16)",
        "api_token": "TEXT",
    }

    missing = [col for col in wanted if col not in columns]
    if not missing:
        return

    raw = db.engine.raw_connection()
    try:
        cursor = raw.cursor()
        for col in missing:
            cursor.execute(f"ALTER TABLE firewalls ADD COLUMN {col} {wanted[col]}")
        raw.commit()
    except Exception:
        try:
            raw.rollback()
        except Exception:
            pass
        raise
    finally:
        raw.close()


def _ensure_config_objects_project_nullable():
    """One-off migration for existing SQLite databases.

    ``config_objects.project_id`` became nullable so an object can be imported
    into a firewall that is not attached to a project yet (the firewall
    wizard creates + imports before any project exists). SQLite cannot drop a
    NOT NULL constraint with ALTER TABLE, so the table is rebuilt when the
    stored schema is still NOT NULL. Fresh databases are created nullable by
    ``db.create_all()`` and skip this entirely.
    """
    raw = db.engine.raw_connection()
    try:
        cursor = raw.cursor()
        cursor.execute("PRAGMA table_info(config_objects)")
        columns = cursor.fetchall()
    finally:
        raw.close()

    if not columns:
        return

    if not any(
        name == "project_id" and notnull for _, name, _, notnull, _, _ in columns
    ):
        return

    raw = db.engine.raw_connection()
    try:
        cursor = raw.cursor()
        cursor.execute("PRAGMA foreign_keys=OFF")
        cursor.execute("BEGIN")
        cursor.execute(
            """
            CREATE TABLE config_objects_new (
                id INTEGER NOT NULL,
                project_id INTEGER,
                firewall_id INTEGER NOT NULL,
                object_type VARCHAR(32) NOT NULL,
                name VARCHAR(255) NOT NULL,
                description TEXT,
                payload JSON NOT NULL,
                raw_excerpt TEXT,
                fingerprint VARCHAR(64),
                is_deleted BOOLEAN NOT NULL,
                deleted_at DATETIME,
                created_by VARCHAR(120),
                updated_by VARCHAR(120),
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                PRIMARY KEY (id),
                CONSTRAINT uq_config_objects_firewall_type_name
                    UNIQUE (firewall_id, object_type, name),
                FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE CASCADE,
                FOREIGN KEY(firewall_id) REFERENCES firewalls (id) ON DELETE CASCADE
            )
            """
        )
        cursor.execute(
            """
            INSERT INTO config_objects_new (
                id, project_id, firewall_id, object_type, name, description,
                payload, raw_excerpt, fingerprint, is_deleted, deleted_at,
                created_by, updated_by, created_at, updated_at
            )
            SELECT
                id, project_id, firewall_id, object_type, name, description,
                payload, raw_excerpt, fingerprint, is_deleted, deleted_at,
                created_by, updated_by, created_at, updated_at
            FROM config_objects
            """
        )
        cursor.execute("DROP TABLE config_objects")
        cursor.execute("ALTER TABLE config_objects_new RENAME TO config_objects")
        cursor.execute(
            "CREATE INDEX ix_config_objects_project_id"
            " ON config_objects (project_id)"
        )
        cursor.execute(
            "CREATE INDEX ix_config_objects_firewall_id"
            " ON config_objects (firewall_id)"
        )
        cursor.execute(
            "CREATE INDEX ix_config_objects_object_type"
            " ON config_objects (object_type)"
        )
        cursor.execute(
            "CREATE INDEX ix_config_objects_fingerprint"
            " ON config_objects (fingerprint)"
        )
        cursor.execute(
            "CREATE INDEX ix_config_objects_firewall_type"
            " ON config_objects (firewall_id, object_type)"
        )
        cursor.execute("COMMIT")
    except Exception:
        try:
            cursor.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        cursor.execute("PRAGMA foreign_keys=ON")
        raw.close()


def _ensure_config_objects_export_included():
    """One-off migration for existing SQLite databases.

    ``config_objects.export_included`` (boolean, default false) tags the
    objects marked "Include in the export" on the object list page; the
    export wizard pre-selects them per object type. SQLite ALTER TABLE can
    add a NOT NULL column as long as it carries a default, so no rebuild is
    needed.
    """
    raw = db.engine.raw_connection()
    try:
        cursor = raw.cursor()
        cursor.execute("PRAGMA table_info(config_objects)")
        columns = {name for _, name, _, _, _, _ in cursor.fetchall()}
    finally:
        raw.close()

    if not columns or "export_included" in columns:
        return

    raw = db.engine.raw_connection()
    try:
        cursor = raw.cursor()
        cursor.execute(
            "ALTER TABLE config_objects"
            " ADD COLUMN export_included BOOLEAN NOT NULL DEFAULT 0"
        )
        raw.commit()
    except Exception:
        try:
            raw.rollback()
        except Exception:
            pass
        raise
    finally:
        raw.close()


def create_app():
    app = Flask(__name__, template_folder="../templates", static_folder="../static")


    app.config["SECRET_KEY"] = os.getenv("SWISSKNIFE_SECRET", "dev-secret-change-me")
    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
        "DATABASE_URL",
        "sqlite:///swissknife.db",
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024

    # Cache busting: browsers keep static/js/app.js for Flask's default
    # static max-age (12 h). The base template renders the script tag with
    # ?v=<mtime of app.js>, so every server restart after an app.js edit
    # forces the browser to fetch the new file (stale JS would break the
    # pages that reference newer component functions).
    app.js_path = os.path.join(app.static_folder, "js", "app.js")
    app.jinja_env.globals["app_version"] = int(os.path.getmtime(app.js_path))

    db.init_app(app)

    from .api.routes import api_bp
    from .views import views_bp

    # Models are registered in the metadata when they are imported above,
    # so create tables after that point.
    with app.app_context():
        db.create_all()
        _ensure_firewalls_project_nullable()
        _ensure_firewall_auth_columns()
        _ensure_config_objects_project_nullable()
        _ensure_config_objects_export_included()

    app.register_blueprint(api_bp)
    app.register_blueprint(views_bp)

    return app
