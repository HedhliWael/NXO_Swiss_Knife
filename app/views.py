import json
import os

from flask import (
    Blueprint,
    abort,
    current_app,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    send_file,
)
from sqlalchemy.exc import IntegrityError

from .models import (
    ALLOWED_OBJECT_TYPES,
    ConfigObject,
    ExportRecord,
    Firewall,
    ModificationHistory,
    Project,
    db,
)
from .api.routes import current_user
from .vendors.factory import registered_vendors
from . import forms  # Import forms module


views_bp = Blueprint("views", __name__)


def _all_firewalls():
    """All active (non-deleted) firewalls, ordered by name."""
    return (
        Firewall.query.filter(Firewall.is_deleted == False)  # noqa: E712
        .order_by(Firewall.name)
        .all()
    )


def _project_name_conflict(name):
    """Friendly error message for a project name collision on create/rename.

    A project in the trash keeps its (unique) name reserved until it is
    restored — there is no permanent-delete in the UI yet.
    """
    shadow = Project.query.filter_by(name=name, is_deleted=True).first()

    if shadow is not None:
        return f"Project '{name}' is in the trash — restore it from the Trash page first."

    return "A project with this name already exists."


def _project_form(formdata=None):
    form = forms.ProjectForm(formdata)
    form.set_firewall_choices(_all_firewalls())
    return form


# Columns rendered by the object list page, per object type.
# Each entry is [header, key-path]; "payload.*" resolves into the normalized
# JSON payload, "_summary" / "_enabled" are computed client-side.
TYPE_COLUMNS = {
    "address": [
        ["Name", "name"],
        ["Address", "payload.address"],
        ["Type", "payload.address_type"],
        ["Description", "description"],
        ["Updated by", "updated_by"],
    ],
    "address_group": [
        ["Name", "name"],
        ["Members", "payload.members"],
        ["Description", "description"],
        ["Updated by", "updated_by"],
    ],
    "service": [
        ["Name", "name"],
        ["Protocol", "payload.protocol"],
        ["Port", "payload.port"],
        ["Source port", "payload.source_port"],
        ["Description", "description"],
        ["Updated by", "updated_by"],
    ],
    "service_group": [
        ["Name", "name"],
        ["Members", "payload.members"],
        ["Updated by", "updated_by"],
    ],
    "rule": [
        ["Name", "name"],
        ["Action", "payload.action"],
        ["Sources", "payload.sources"],
        ["Destinations", "payload.destinations"],
        ["Services", "payload.services"],
        ["Source zones", "payload.source_zones"],
        ["Dest. zones", "payload.destination_zones"],
        ["Enabled", "_enabled"],
        ["Description", "description"],
    ],
    "interface": [
        ["Name", "name"],
        ["IP", "payload.ip"],
        ["Type", "payload.type"],
        ["Role", "payload.role"],
        ["Alias", "payload.alias"],
    ],
    "zone": [
        ["Name", "name"],
        ["Members", "payload.members"],
    ],
}

GENERIC_COLUMNS = [
    ["ID", "id"],
    ["Type", "object_type"],
    ["Name", "name"],
    ["Firewall", "firewall_name"],
    ["Key values", "_summary"],
    ["Updated by", "updated_by"],
]


def _human_size(num_bytes):
    """Human-readable size for the project page export list."""
    size = float(num_bytes or 0)

    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{int(size)} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024


def _project_stats(project):
    """Per-firewall, per-type object statistics for a project.

    Returns a dict with:
      firewalls: [{id, name, total, types: {type: n}, modified: {type: n},
                  deleted: {type: n}, last_sync_at}]
      types: canonical list of the types present in the project (or all 9 when empty)
      totals: {objects, modified, types}
      last_import: iso timestamp of the most recent firewall import (or None)
    """
    firewalls = (
        Firewall.query.filter_by(project_id=project.id)
        .filter(Firewall.is_deleted == False)  # noqa: E712
        .order_by(Firewall.name)
        .all()
    )
    firewall_ids = [fw.id for fw in firewalls]

    type_counts = {}

    if firewall_ids:
        rows = (
            db.session.query(
                ConfigObject.firewall_id,
                ConfigObject.object_type,
                db.func.count(ConfigObject.id),
            )
            .filter(
                ConfigObject.firewall_id.in_(firewall_ids),
                ConfigObject.is_deleted == False,  # noqa: E712
            )
            .group_by(ConfigObject.firewall_id, ConfigObject.object_type)
            .all()
        )

        for fw_id, object_type, count in rows:
            type_counts[(fw_id, object_type)] = count

    modified_counts = {}

    if firewall_ids:
        rows = (
            db.session.query(
                ConfigObject.firewall_id,
                ConfigObject.object_type,
                db.func.count(db.distinct(ModificationHistory.config_object_id)),
            )
            .join(ModificationHistory, ModificationHistory.config_object_id == ConfigObject.id)
            .filter(
                ConfigObject.firewall_id.in_(firewall_ids),
                ConfigObject.is_deleted == False,  # noqa: E712
                ModificationHistory.action == "update",
            )
            .group_by(ConfigObject.firewall_id, ConfigObject.object_type)
            .all()
        )

        for fw_id, object_type, count in rows:
            modified_counts[(fw_id, object_type)] = count

    included_counts = {}

    if firewall_ids:
        rows = (
            db.session.query(
                ConfigObject.firewall_id,
                ConfigObject.object_type,
                db.func.count(ConfigObject.id),
            )
            .filter(
                ConfigObject.firewall_id.in_(firewall_ids),
                ConfigObject.is_deleted == False,  # noqa: E712
                ConfigObject.export_included == True,  # noqa: E712
            )
            .group_by(ConfigObject.firewall_id, ConfigObject.object_type)
            .all()
        )

        for fw_id, object_type, count in rows:
            included_counts[(fw_id, object_type)] = count

    # Deleted (soft-deleted) objects per firewall / per type — the same
    # pattern as the modified counts, for the "Manage firewalls" table.
    deleted_counts = {}

    if firewall_ids:
        rows = (
            db.session.query(
                ConfigObject.firewall_id,
                ConfigObject.object_type,
                db.func.count(ConfigObject.id),
            )
            .filter(
                ConfigObject.firewall_id.in_(firewall_ids),
                ConfigObject.is_deleted == True,  # noqa: E712
            )
            .group_by(ConfigObject.firewall_id, ConfigObject.object_type)
            .all()
        )

        for fw_id, object_type, count in rows:
            deleted_counts[(fw_id, object_type)] = count

    present_types = {t for (_fw, t) in type_counts}

    fw_stats = []

    for fw in firewalls:
        types = {t: type_counts.get((fw.id, t), 0) for t in ALLOWED_OBJECT_TYPES}
        modified = {t: modified_counts.get((fw.id, t), 0) for t in ALLOWED_OBJECT_TYPES}
        included = {t: included_counts.get((fw.id, t), 0) for t in ALLOWED_OBJECT_TYPES}
        deleted = {t: deleted_counts.get((fw.id, t), 0) for t in ALLOWED_OBJECT_TYPES}
        fw_stats.append(
            {
                "id": fw.id,
                "name": fw.name,
                "vendor": fw.vendor,
                "model": fw.model,
                "management_ip": fw.management_ip,
                "auth_mode": fw.auth_mode or "password",
                "total": sum(types.values()),
                "modified_total": sum(modified.values()),
                "included_total": sum(included.values()),
                "deleted_total": sum(deleted.values()),
                "types": types,
                "modified": modified,
                "included": included,
                "deleted": deleted,
                "last_sync_at": fw.last_sync_at.isoformat() if fw.last_sync_at else None,
            }
        )

    types = [t for t in ALLOWED_OBJECT_TYPES if t in present_types]
    total_objects = sum(type_counts.values())
    total_modified = sum(modified_counts.values())
    last_import = max((fw.last_sync_at for fw in firewalls if fw.last_sync_at), default=None)

    col_totals = {
        t: sum(type_counts.get((fw.id, t), 0) for fw in firewalls)
        for t in ALLOWED_OBJECT_TYPES
    }

    return {
        "firewalls": fw_stats,
        "types": types or list(ALLOWED_OBJECT_TYPES),
        "col_totals": col_totals,
        "totals": {
            "objects": total_objects,
            "modified": total_modified,
            "types": len(present_types),
        },
        "last_import": last_import.isoformat() if last_import else None,
    }


def _export_database_stats():
    """Per-type object statistics over every firewall in the database.

    An export delivers the whole database configuration to the destination
    firewall (not only its own objects), so the "Object types to export"
    step of the export wizard counts objects across all firewalls.

    Returns a dict with:
      types: {type: n}        active objects per type
      included: {type: n}     objects tagged "Include in the export" per type
      modified: {type: n}     objects with an update in the history per type
    """
    types = {t: 0 for t in ALLOWED_OBJECT_TYPES}
    included = {t: 0 for t in ALLOWED_OBJECT_TYPES}
    modified = {t: 0 for t in ALLOWED_OBJECT_TYPES}

    for object_type, count in (
        db.session.query(ConfigObject.object_type, db.func.count(ConfigObject.id))
        .filter(ConfigObject.is_deleted == False)  # noqa: E712
        .group_by(ConfigObject.object_type)
        .all()
    ):
        types[object_type] = count

    for object_type, count in (
        db.session.query(ConfigObject.object_type, db.func.count(ConfigObject.id))
        .filter(
            ConfigObject.is_deleted == False,  # noqa: E712
            ConfigObject.export_included == True,  # noqa: E712
        )
        .group_by(ConfigObject.object_type)
        .all()
    ):
        included[object_type] = count

    for object_type, count in (
        db.session.query(
            ConfigObject.object_type,
            db.func.count(db.distinct(ModificationHistory.config_object_id)),
        )
        .join(
            ModificationHistory,
            ModificationHistory.config_object_id == ConfigObject.id,
        )
        .filter(
            ConfigObject.is_deleted == False,  # noqa: E712
            ModificationHistory.action == "update",
        )
        .group_by(ConfigObject.object_type)
        .all()
    ):
        modified[object_type] = count

    return {"types": types, "included": included, "modified": modified}


@views_bp.route("/")
def dashboard():
    """Dashboard: exhaustive lists of all projects and all firewalls.

    Project creation (3-step wizard) and firewall creation (3-step wizard)
    run client-side against the API and are hosted in this page's modals.
    """
    return render_template(
        "index.html",
        vendor_choices=registered_vendors(),
        object_types=ALLOWED_OBJECT_TYPES,
    )


@views_bp.route("/projects/<int:project_id>")
def project_detail(project_id):
    project = Project.query.get_or_404(project_id)

    # A project in the trash is not openable — restore it from the Trash page.
    if project.is_deleted:
        abort(404)

    stats = _project_stats(project)

    # Any firewall not attached to this project can be attached — also
    # without an imported configuration (it can be imported later).
    # Firewalls in the trash are not attachable (restore them first).
    attachable_firewalls = []

    for fw in Firewall.query.order_by(Firewall.name).all():
        if fw.project_id == project.id or fw.is_deleted:
            continue
        attachable_firewalls.append((fw, fw.objects_count))

    # Previous generated / pushed configuration files of the project
    # (newest first) — listed in the "Export configuration" section.
    exports = []

    for record in ExportRecord.query.filter_by(project_id=project.id).order_by(
        ExportRecord.created_at.desc(), ExportRecord.id.desc()
    ).all():
        counts = record.counts or {}
        exports.append(
            {
                "id": record.id,
                "filename": record.filename,
                "method": record.method,
                "destination": record.destination_name or "—",
                "object_count": record.object_count,
                "types_summary": ", ".join(
                    f"{t} {n}" for t, n in sorted(counts.items())
                ),
                "size_human": _human_size(record.size_bytes),
                "created": (
                    record.created_at.strftime("%Y-%m-%d %H:%M")
                    if record.created_at
                    else "—"
                ),
                "available": os.path.isfile(
                    os.path.join(
                        current_app.instance_path,
                        "exports",
                        os.path.basename(record.file_path),
                    )
                ),
                "download_url": url_for(
                    "views.download_project_export",
                    project_id=project.id,
                    export_id=record.id,
                ),
            }
        )

    return render_template(
        "project.html",
        project=project,
        stats=stats,
        attachable_firewalls=attachable_firewalls,
        exports=exports,
        object_types=ALLOWED_OBJECT_TYPES,
    )


@views_bp.route("/projects/<int:project_id>/firewalls/attach", methods=["POST"])
def attach_project_firewall(project_id):
    """Attach an existing firewall (currently attached to another project, or unassigned).

    Firewalls without an imported configuration can be attached too; the
    configuration can be imported later from the project or firewall pages.
    """
    project = Project.query.get_or_404(project_id)

    raw_id = request.form.get("firewall_id") or ""
    try:
        firewall_id = int(raw_id)
    except ValueError:
        firewall_id = None

    if firewall_id is None or firewall_id <= 0:
        flash("Select a firewall to attach.", "error")
        return redirect(url_for("views.project_detail", project_id=project.id))

    firewall = Firewall.query.get(firewall_id)

    if firewall is None:
        flash("The selected firewall no longer exists.", "error")
    elif firewall.is_deleted:
        flash(f"Firewall '{firewall.name}' is in the trash — restore it from the Trash page first.", "error")
    elif firewall.project_id == project.id:
        flash(f"Firewall '{firewall.name}' is already attached to this project.", "error")
    else:
        firewall.set_project(project.id)
        db.session.commit()
        flash(f"Firewall '{firewall.name}' attached to project '{project.name}'.", "success")

    return redirect(url_for("views.project_detail", project_id=project.id))


@views_bp.route(
    "/projects/<int:project_id>/firewalls/<int:firewall_id>/remove", methods=["POST"]
)
def remove_project_firewall(project_id, firewall_id):
    """Remove a firewall from this project without deleting it (it becomes unassigned)."""
    project = Project.query.get_or_404(project_id)
    firewall = Firewall.query.get_or_404(firewall_id)

    if firewall.project_id != project.id:
        flash("That firewall does not belong to this project.", "error")
        return redirect(url_for("views.project_detail", project_id=project.id))

    name = firewall.name
    firewall.set_project(None)
    db.session.commit()
    flash(f"Firewall '{name}' was removed from project '{project.name}'.", "success")

    return redirect(url_for("views.project_detail", project_id=project.id))


@views_bp.route("/projects/<int:project_id>/exports/<int:export_id>/download")
def download_project_export(project_id, export_id):
    """Serve a previously generated or pushed configuration file of the project."""
    project = Project.query.get_or_404(project_id)
    record = ExportRecord.query.filter_by(id=export_id, project_id=project.id).first_or_404()
    path = os.path.join(
        current_app.instance_path, "exports", os.path.basename(record.file_path)
    )

    if not os.path.isfile(path):
        flash("The file is no longer on disk — generate it again.", "error")
        return redirect(url_for("views.project_detail", project_id=project.id))

    mimetype = (
        "application/xml" if record.filename.lower().endswith(".xml") else "text/plain"
    )
    return send_file(
        path,
        mimetype=mimetype,
        as_attachment=True,
        download_name=record.filename,
    )


@views_bp.route("/firewalls/<int:firewall_id>/delete", methods=["POST"])
def delete_firewall(firewall_id):
    """Move a firewall to the trash (its objects follow — restorable from the Trash page).

    The UI asks for confirmation first.
    """
    firewall = Firewall.query.get_or_404(firewall_id)

    if firewall.is_deleted:
        flash("That firewall is already in the trash.", "error")
        return redirect(url_for("views.firewalls_page"))

    name = firewall.name
    firewall.soft_delete(user=current_user(), reason="Deleted from UI")
    db.session.commit()
    flash(f"Firewall '{name}' was moved to the trash — restore it from the Trash page.", "success")

    return redirect(url_for("views.firewalls_page"))


@views_bp.route("/projects/<int:project_id>/edit", methods=["GET", "POST"])
def edit_project(project_id):
    project = Project.query.get_or_404(project_id)

    if request.method == "POST":
        form = _project_form(request.form)

        if form.validate_on_submit():
            project.name = form.name.data
            project.description = form.description.data

            try:
                db.session.commit()
                flash("Project updated successfully!", "success")
                return redirect(url_for("views.project_detail", project_id=project.id))
            except IntegrityError:
                db.session.rollback()
                flash(_project_name_conflict(form.name.data), "error")
                return redirect(url_for("views.project_detail", project_id=project.id))

        return render_template("project_edit.html", project=project, form=form)

    form = _project_form()
    form.name.data = project.name
    form.description.data = project.description
    return render_template("project_edit.html", project=project, form=form)


@views_bp.route("/projects/<int:project_id>/delete", methods=["POST"])
def delete_project(project_id):
    """Move a project to the trash (its firewalls + objects follow — restorable).

    The UI asks for confirmation first.
    """
    project = Project.query.get_or_404(project_id)

    if project.is_deleted:
        flash("That project is already in the trash.", "error")
        return redirect(url_for("views.dashboard"))

    name = project.name
    project.soft_delete(user=current_user(), reason="Deleted from UI")
    db.session.commit()

    flash(f"Project '{name}' was moved to the trash — restore it from the Trash page.", "success")
    return redirect(url_for("views.dashboard"))


@views_bp.route("/projects/<int:project_id>/export")
def export_page(project_id):
    project = Project.query.get_or_404(project_id)
    stats = _project_stats(project)

    # JSON-safe copy for the Alpine export wizard (no "><" sequences).
    # "database" carries the per-type counts over ALL firewalls: an export
    # delivers the whole database configuration, not only the destination's
    # own objects.
    stats_json = json.dumps(
        {
            "types": ALLOWED_OBJECT_TYPES,
            "firewalls": stats["firewalls"],
            "database": _export_database_stats(),
        }
    ).replace("<", "\\u003c")

    preselected = request.args.get("firewall_id", "")

    return render_template(
        "export.html",
        project=project,
        stats=stats,
        stats_json=stats_json,
        preselected_firewall=preselected,
        object_types=ALLOWED_OBJECT_TYPES,
    )


@views_bp.route("/import")
def import_page():
    """Standalone import wizard (firewall → source/types → review).

    The wizard is client-side (the Alpine ``importWizard()`` component in
    app.js) and POSTs to ``/api/import`` — this page is GET-only and only
    renders the wizard.
    """
    firewalls = _all_firewalls()

    # JSON-safe firewall list for the Alpine wizard (embedded in a
    # single-quoted x-data attribute; '<' escaped like export_page does).
    firewalls_json = json.dumps(
        [
            {
                "id": fw.id,
                "name": fw.name,
                "vendor": fw.vendor,
                "model": fw.model,
            }
            for fw in firewalls
        ]
    ).replace("<", "\\u003c")

    return render_template(
        "import.html",
        firewalls=firewalls,
        firewalls_json=firewalls_json,
        object_types=ALLOWED_OBJECT_TYPES,
    )


@views_bp.route("/objects")
def objects_page():
    """Object list, scoped by the navigation context (project / firewall / type).

    The scope is fixed by where the user came from (dashboard, project count
    click, firewall card) — there are no project/firewall filter controls on
    the page itself. Columns are specific to the scoped object type.
    """
    project_id = (request.args.get("project_id") or "").strip()
    firewall_id = (request.args.get("firewall_id") or "").strip()
    object_type = (request.args.get("object_type") or "").strip()

    project = None
    firewall = None

    # Entries in the trash are out of scope (restore them from the Trash page
    # first) — treat them as if the scope was not given.
    if project_id.isdigit():
        project = Project.query.get(int(project_id))
        if project is not None and project.is_deleted:
            project = None
        project_id = str(project.id) if project else ""
    else:
        project_id = ""

    if firewall_id.isdigit():
        firewall = Firewall.query.get(int(firewall_id))
        if firewall is not None and firewall.is_deleted:
            firewall = None
        firewall_id = str(firewall.id) if firewall else ""
    else:
        firewall_id = ""

    if object_type and object_type not in ALLOWED_OBJECT_TYPES:
        object_type = ""

    columns = TYPE_COLUMNS.get(object_type, GENERIC_COLUMNS)
    columns_json = json.dumps(columns).replace("<", "\\u003c")

    # Search fields offered by the object list page (besides name/description):
    # one bare payload key per column displayed for the current object type
    # (the API filters them as ?address=, ?action=, etc.).
    payload_search_keys = []
    for _header, key in columns:
        if key.startswith("payload."):
            bare = key[len("payload."):]
            if bare not in payload_search_keys:
                payload_search_keys.append(bare)

    return render_template(
        "objects.html",
        project=project,
        firewall=firewall,
        project_id=project_id,
        firewall_id=firewall_id,
        object_type=object_type,
        columns=columns,
        columns_json=columns_json,
        payload_search_keys=payload_search_keys,
    )


@views_bp.route("/trash")
def trash_page():
    """Trash page — two separate trashes (restorable).

    Without a scope (the dashboard trash) the page lists deleted projects and
    firewalls only. With ``?project_id=`` (the trash can on the project page)
    it is scoped to that project's deleted objects only.
    """
    project = None
    project_id = ""

    raw_id = (request.args.get("project_id") or "").strip()

    if raw_id.isdigit():
        project = Project.query.get(int(raw_id))
        project_id = str(project.id) if project else ""

    return render_template("trash.html", project=project, project_id=project_id)


@views_bp.route("/projects", methods=["GET", "POST"])
def projects_page():
    from .forms import ProjectForm
    
    if request.method == "POST":
        form = ProjectForm(request.form)
        if form.validate_on_submit():
            try:
                project = Project(name=form.name.data, description=form.description.data)
                db.session.add(project)
                db.session.commit()
                flash("Project created successfully!", "success")
                return redirect(url_for("views.projects_page"))
            except IntegrityError:
                db.session.rollback()
                flash(_project_name_conflict(form.name.data), "error")
                return redirect(url_for("views.projects_page"))
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    flash(f"{field}: {error}", "error")
            return redirect(url_for("views.projects_page"))
    
    projects = (
        Project.query.filter(Project.is_deleted == False)  # noqa: E712
        .order_by(Project.name)
        .all()
    )
    return render_template("projects.html", projects=projects, form=ProjectForm())


@views_bp.route("/firewalls", methods=["GET", "POST"])
def firewalls_page():
    """Firewall dashboard: all firewalls as cards (same style as the project dashboard)."""
    if request.method == "POST":
        project_id = (request.form.get("project_id") or "").strip() or None
        name = (request.form.get("name") or "").strip()
        vendor = (request.form.get("vendor") or "").strip().lower()
        management_ip = (request.form.get("management_ip") or "").strip() or None
        description = request.form.get("description") or None

        project = None
        if project_id:
            try:
                project = Project.query.get(int(project_id))
            except ValueError:
                project = None
            if project is None:
                flash("Select a valid project, or leave the firewall unassigned.", "error")
                return redirect(url_for("views.firewalls_page"))
            if project.is_deleted:
                flash(f"Project '{project.name}' is in the trash — restore it first.", "error")
                return redirect(url_for("views.firewalls_page"))

        if not name or not vendor:
            flash("Name and vendor are required.", "error")
            return redirect(url_for("views.firewalls_page"))

        try:
            firewall = Firewall(
                project_id=project.id if project else None,
                name=name,
                vendor=vendor,
                management_ip=management_ip,
                description=description,
            )
            db.session.add(firewall)
            db.session.commit()
            if project:
                flash(f"Firewall '{name}' created in project '{project.name}'.", "success")
            else:
                flash(f"Firewall '{name}' created (not attached to a project).", "success")
            return redirect(url_for("views.firewalls_page"))
        except IntegrityError:
            db.session.rollback()
            flash("A firewall with this name already exists in this project.", "error")
            return redirect(url_for("views.firewalls_page"))

    return render_template(
        "firewalls.html",
        vendor_choices=registered_vendors(),
        object_types=ALLOWED_OBJECT_TYPES,
    )