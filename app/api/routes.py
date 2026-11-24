import hashlib
import json
import logging
import os
import secrets
import socket
import time
import warnings
from datetime import datetime, timedelta, timezone

import requests
from flask import Blueprint, Response, current_app, jsonify, request, session
from requests.packages.urllib3.exceptions import InsecureRequestWarning
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from werkzeug.exceptions import HTTPException

from ..errors import (
    ParsingError,
    UnsupportedVendorError,
    ValidationError,
    VendorAPIError,
)
from ..extensions import db
from ..models import (
    ALLOWED_OBJECT_TYPES,
    ConfigObject,
    Firewall,
    ModificationHistory,
    Project,
    Trash,
    log_change,
)
from ..vendors.factory import get_parser, registered_vendors

logger = logging.getLogger(__name__)

api_bp = Blueprint("api", __name__, url_prefix="/api")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def current_user():
    """
    Placeholder user resolution.

    In production, replace this with JWT, OAuth2, LDAP, or session-based authentication.
    """
    auth_header = request.headers.get("Authorization", "")

    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        return token[:64] or "system"

    # Use the `session` global (Flask >= 2.x): `request.session` does not
    # exist on the Request object and raises AttributeError.
    return session.get("user") or "system"


def _project_payload(project: Project):
    data = project.to_dict()
    data["firewalls"] = [fw.to_dict() for fw in project.firewalls]
    return data


def _serialize_object(obj: ConfigObject):
    data = obj.to_dict()
    data["firewall_name"] = obj.firewall.name if obj.firewall else None
    return data


# Normalized parser payload keys that can be searched through GET /api/objects
# (per-field filters and the generic `search` parameter).
PAYLOAD_SEARCH_KEYS = (
    "action",
    "address",
    "address_type",
    "ip",
    "protocol",
    "port",
    "source_port",
    "sources",
    "destinations",
    "services",
    "source_zones",
    "destination_zones",
    "members",
    "role",
    "alias",
    "type",
    "zone",
    "description",
)


def _normalize_type_list(value):
    if value is None:
        return []

    items = []

    if isinstance(value, str):
        items = value.split(",")
    else:
        for item in value:
            if item is None:
                continue
            if isinstance(item, str) and "," in item:
                items.extend(item.split(","))
            else:
                items.append(str(item))

    return [item.strip() for item in items if item.strip()]


def _get_selected_types():
    if request.is_json:
        data = request.get_json(silent=True) or {}
        raw = data.get("object_types")
    else:
        values = request.form.getlist("object_types")
        if not values:
            values = [request.form.get("object_types_csv", "")]
        raw = values

    types = _normalize_type_list(raw)

    if not types:
        raise ValidationError("Select at least one object type to import.")

    invalid = [t for t in types if t not in ALLOWED_OBJECT_TYPES]
    if invalid:
        raise ValidationError(f"Unsupported object types: {', '.join(invalid)}")

    # Preserve order and remove duplicates.
    return list(dict.fromkeys(types))


def _get_firewall_id():
    if request.is_json:
        data = request.get_json(silent=True) or {}
        firewall_id = data.get("firewall_id")
    else:
        firewall_id = request.form.get("firewall_id")

    if not firewall_id:
        raise ValidationError("firewall_id is required.")

    try:
        return int(firewall_id)
    except ValueError as exc:
        raise ValidationError("firewall_id must be an integer.") from exc


def _detect_vendor(raw_data: str):
    # A device export may lead with the XML header + <mgt-config>, so scan
    # a larger window than the first 2 KB. Palo Alto markers always appear
    # in the first 20 KB (XML root attributes / first `set` lines).
    sample = raw_data[:20000].lower()

    if (
        "<paloalto" in sample
        or "paloaltonetworks" in sample
        or ("<config" in sample and "vsys" in sample)
        # PAN-OS set (show) format export
        or "set deviceconfig system" in sample
        or "set rulebase security rules" in sample
        or "set address-group" in sample
        or "set service-group" in sample
    ):
        return "paloalto"

    # FortiOS CLI exports can spend the first tens of KB on system/interface
    # sections, so scan the whole document for FortiGate-specific sections.
    lowered = raw_data.lower()

    if (
        "config firewall address" in lowered
        or "config address" in lowered
        or "config firewall policy" in lowered
        or "set subnet" in lowered
    ):
        return "fortinet"

    raise UnsupportedVendorError("Could not detect vendor from configuration content.")


def _fetch_remote_config(firewall: Firewall, url):
    if not url:
        raise ValidationError("url is required when source_type=url.")

    # In production, decrypt firewall.api_password or retrieve it from a secrets manager.
    auth = None
    if firewall.api_username and firewall.api_password:
        auth = (firewall.api_username, firewall.api_password)

    try:
        response = requests.get(url, auth=auth, timeout=30)
    except requests.RequestException as exc:
        raise VendorAPIError(
            f"Network error contacting {url}: {exc}",
            status=502,
        ) from exc

    if response.status_code in (401, 403):
        raise VendorAPIError(
            "Failed to login/authenticate to firewall API.",
            status=401,
        )

    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        raise VendorAPIError(
            f"Firewall API returned HTTP {response.status_code}: {exc}",
            status=response.status_code if 500 <= response.status_code < 600 else 502,
        ) from exc

    return response.text


def _fingerprint(object_type: str, name: str, payload):
    canonical = json.dumps(
        {
            "object_type": object_type,
            "name": name,
            "payload": payload or {},
        },
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _upsert_object(firewall: Firewall, obj_data: dict, user: str):
    object_type = obj_data.get("object_type")
    name = obj_data.get("name")

    if not object_type or object_type not in ALLOWED_OBJECT_TYPES:
        raise ValidationError("Parsed object has invalid object_type.")

    if not name:
        raise ValidationError("Parsed object is missing a name.")

    payload = obj_data.get("payload") or {}
    description = obj_data.get("description")
    raw_excerpt = obj_data.get("raw_excerpt")

    existing = (
        ConfigObject.query.filter_by(
            firewall_id=firewall.id,
            object_type=object_type,
            name=name,
        )
        .first()
    )

    if existing is None:
        obj = ConfigObject(
            project_id=firewall.project_id,
            firewall_id=firewall.id,
            object_type=object_type,
            name=name,
            description=description,
            payload=payload,
            raw_excerpt=raw_excerpt,
            fingerprint=_fingerprint(object_type, name, payload),
            created_by=user,
            updated_by=user,
        )

        db.session.add(obj)
        db.session.flush()

        log_change(
            config_object=obj,
            field="payload",
            old_value=None,
            new_value=payload,
            action="import",
            user=user,
        )

        return obj, "create"

    obj = existing
    old_payload = obj.payload or {}

    if obj.is_deleted:
        obj.restore(user)
        log_change(
            config_object=obj,
            field="status",
            old_value="deleted",
            new_value="active",
            action="restore",
            user=user,
        )
        action = "restore"
    else:
        action = "update"

    if old_payload != payload:
        log_change(
            config_object=obj,
            field="payload",
            old_value=old_payload,
            new_value=payload,
            action=action,
            user=user,
        )

    obj.description = description
    obj.payload = payload
    obj.raw_excerpt = raw_excerpt
    obj.fingerprint = _fingerprint(object_type, name, payload)
    obj.updated_by = user

    return obj, action


def _mock_push_config(firewall: Firewall, config_text: str):
    """
    Mock push implementation.

    Replace this with vendor-specific REST API calls in production.
    """
    logger.info(
        "Mock push to firewall %s (%s), bytes=%d",
        firewall.name,
        firewall.vendor,
        len(config_text),
    )

    if os.getenv("SWISSKNIFE_ENABLE_PUSH") == "1":
        # Placeholder for a real vendor REST endpoint.
        url = f"https://{firewall.management_ip}/api/v2/config"

        auth = None
        if firewall.api_username and firewall.api_password:
            auth = (firewall.api_username, firewall.api_password)

        try:
            response = requests.post(
                url,
                data=config_text.encode("utf-8"),
                headers={"Content-Type": "text/plain"},
                auth=auth,
                timeout=60,
            )
        except requests.RequestException as exc:
            raise VendorAPIError(f"Push failed due to network error: {exc}", status=502) from exc

        if response.status_code in (401, 403):
            raise VendorAPIError(
                "Failed to login/authenticate during push.",
                status=401,
            )

        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise VendorAPIError(
                f"Push failed with HTTP {response.status_code}: {exc}",
                status=response.status_code if 500 <= response.status_code < 600 else 502,
            ) from exc


def _ndjson_response(generator):
    """Wrap a line generator into a buffered-friendly NDJSON streaming response."""
    return Response(
        generator,
        mimetype="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


def _progress_line(stage, percent, detail=""):
    return json.dumps(
        {"event": "progress", "stage": stage, "percent": percent, "detail": detail}
    ) + "\n"


def _stream_parse_and_import(firewall_id, vendor, selected_types, raw_data, user, start_percent, end_percent):
    """Yield NDJSON lines while parsing and upserting one configuration.

    Runs inside a fresh application context (see the stream routes) so the
    DB work stays valid for the whole duration of the streamed response.
    """
    firewall = Firewall.query.get_or_404(firewall_id)

    try:
        parser = get_parser(vendor or _detect_vendor(raw_data))
    except ValueError as exc:
        yield json.dumps({"event": "error", "error": str(exc)}) + "\n"
        return

    yield _progress_line("parse", start_percent, "Parsing configuration...")

    try:
        parsed = parser.parse_config(raw_data, selected_types)
    except ParsingError as exc:
        yield json.dumps({"event": "error", "error": str(exc)}) + "\n"
        return
    except Exception as exc:
        logger.exception("Parser failed for vendor %s.", vendor)
        yield json.dumps({"event": "error", "error": f"Failed to parse configuration: {exc}"}) + "\n"
        return

    counts = {}
    total_to_import = sum(
        1 for o in parsed.objects if o.get("object_type") in selected_types
    )
    done = 0

    try:
        for obj_data in parsed.objects:
            object_type = obj_data.get("object_type")

            if object_type not in selected_types:
                continue

            _, _action = _upsert_object(firewall, obj_data, user)
            counts[object_type] = counts.get(object_type, 0) + 1
            done += 1

            if total_to_import > 0 and (
                done % max(1, total_to_import // 20) == 0 or done == total_to_import
            ):
                percent = start_percent + int(
                    (end_percent - start_percent) * done / total_to_import
                )
                yield _progress_line(
                    "import", min(percent, end_percent), f"Imported {done}/{total_to_import} objects."
                )

        firewall.last_sync_at = datetime.now(timezone.utc)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        yield json.dumps(
            {"event": "error", "error": "Import failed due to database constraint violation."}
        ) + "\n"
        return

    yield (
        json.dumps(
            {
                "event": "done",
                "status": "ok",
                "message": f"Imported {sum(counts.values())} objects.",
                "counts": counts,
                "warnings": parsed.warnings,
            }
        )
        + "\n"
    )


def _check_connectivity_data(ip, vendor, auth_mode, api_username, api_password, api_token):
    """Best-effort connectivity probe for a firewall management endpoint.

    1. TCP connect to <ip>:443 (device up / port open).
    2. HTTP GET against the vendor API root (authentication state).

    Never raises: problems are reported inside the result dict.
    """
    result = {
        "ok": False,
        "management_ip": ip,
        "reachable": False,
        "http_status": None,
        "detail": "",
        "latency_ms": None,
    }

    if not ip:
        result["detail"] = "No management IP configured."
        return result

    start = time.time()

    try:
        with socket.create_connection((ip, 443), timeout=5):
            pass
    except socket.gaierror as exc:
        result["detail"] = f"Could not resolve '{ip}' ({exc.strerror or exc})."
        return result
    except (socket.timeout, OSError) as exc:
        result["detail"] = f"TCP connection to {ip}:443 failed ({exc})."
        return result

    result["reachable"] = True
    result["ok"] = True
    result["latency_ms"] = int((time.time() - start) * 1000)

    vendor = (vendor or "").strip().lower()

    if vendor == "fortinet":
        probe_url = f"https://{ip}/api?uuid=__connectivity_check__"
        probe_headers = {}
        auth = (api_username, api_password) if api_username and api_password else None
    elif vendor == "paloalto":
        probe_url = "https://{}".format(ip) + "/api/?type=op&command=%3Crequest%3E%3Cshow%2F%3E%3C%2Frequest%3E"
        probe_headers = {"X-Auth-Token": api_token} if api_token else {}
        auth = None
    else:
        probe_url = f"https://{ip}/"
        probe_headers = {}
        auth = None

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", InsecureRequestWarning)
            response = requests.get(
                probe_url, headers=probe_headers, auth=auth, timeout=10, verify=False
            )

        result["http_status"] = response.status_code

        if response.status_code == 200:
            result["detail"] = "Device reachable; API is responding (HTTP 200)."
        elif response.status_code in (401, 403):
            result["detail"] = (
                f"Device reachable; API returned HTTP {response.status_code} — check the credentials."
            )
        else:
            result["detail"] = f"Device reachable; API returned HTTP {response.status_code}."

    except requests.exceptions.SSLError:
        result["detail"] = (
            "Device reachable (TLS handshake OK). Certificate error — "
            "expected for self-signed firewall certificates."
        )
    except requests.RequestException as exc:
        result["detail"] = f"Device reachable at TCP level; HTTP probe failed: {exc}"

    return result


# Generated export files kept briefly in memory for the download link.
_export_artifacts = {}


def _prune_artifacts():
    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
    for token in [t for t, (_, _, _, ts) in _export_artifacts.items() if ts < cutoff]:
        _export_artifacts.pop(token, None)


def _export_file_name(firewall, fmt="xml"):
    """Filename + MIME type for a generated export file.

    Palo Alto: ``xml`` → PAN-OS ``<paloalto>`` document (.xml), ``set`` →
    set/`show` format (.txt); other vendors: native CLI config (.txt).
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    if firewall.vendor == "paloalto" and (fmt or "").strip().lower() == "xml":
        return f"{firewall.name}_{timestamp}.xml", "application/xml"
    return f"{firewall.name}_{timestamp}.txt", "text/plain"


def _build_config(firewall, object_types, tagged_only_types=None, format=None):
    """Generate the vendor configuration text for the selected objects.

    The configuration spans **all firewalls in the database** (not only the
    destination's own objects): the destination firewall receives every
    active object of the selected types, from every firewall. ``firewall``
    is the destination — it provides the vendor parser and the generation
    context. ``tagged_only_types`` restricts the listed types to the objects
    tagged "Include in the export" (``export_included``); the other selected
    types are exported in full. ``format`` is forwarded to the vendor parser
    (Palo Alto: "xml" or "set").
    """
    tagged_only = {t for t in (tagged_only_types or ()) if t in object_types}

    query = (
        ConfigObject.query.options(db.joinedload(ConfigObject.firewall))
        .filter_by(is_deleted=False)
        .filter(ConfigObject.object_type.in_(object_types))
        .order_by(ConfigObject.object_type.asc(), ConfigObject.name.asc())
    )

    if tagged_only:
        query = query.filter(
            or_(
                ConfigObject.object_type.notin_(sorted(tagged_only)),
                ConfigObject.export_included == True,  # noqa: E712
            )
        )

    objects = query.all()

    if not objects:
        raise ValidationError("No active objects selected for export.")

    try:
        parser = get_parser(firewall.vendor)
    except ValueError as exc:
        raise UnsupportedVendorError(str(exc)) from exc

    serialized_objects = [_serialize_object(obj) for obj in objects]

    try:
        config_text = parser.generate_config(
            serialized_objects,
            context={"firewall": firewall.to_dict()},
            format=format,
        )
    except Exception as exc:
        logger.exception("Config generation failed.")
        raise ValidationError(f"Failed to generate configuration: {exc}") from exc

    counts = {}
    for obj in objects:
        counts[obj.object_type] = counts.get(obj.object_type, 0) + 1

    return config_text, objects, counts


# ---------------------------------------------------------------------------
# Error Handlers
# ---------------------------------------------------------------------------

@api_bp.errorhandler(ValidationError)
def handle_validation_error(error):
    return jsonify(error=str(error)), getattr(error, "status", 400)


@api_bp.errorhandler(VendorAPIError)
def handle_vendor_api_error(error):
    return jsonify(error=error.message), error.status


@api_bp.errorhandler(Exception)
def handle_unexpected_error(error):
    db.session.rollback()

    if isinstance(error, HTTPException):
        return jsonify(error=error.description), error.code

    logger.exception("Unhandled API error")
    return jsonify(error="Internal server error."), 500


# ---------------------------------------------------------------------------
# Auth Placeholder
# ---------------------------------------------------------------------------

@api_bp.route("/auth/login", methods=["POST"])
def auth_login():
    """
    Minimal login endpoint for demonstration.

    Replace with real authentication in production.
    """
    data = request.get_json(force=True, silent=True) or {}

    username = data.get("username", "")
    password = data.get("password", "")

    expected_user = os.getenv("SWISSKNIFE_ADMIN_USER", "admin")
    expected_password = os.getenv("SWISSKNIFE_ADMIN_PASS", "change-me")

    if not username or not password:
        raise ValidationError("Username and password are required.")

    if username != expected_user or password != expected_password:
        logger.warning("Failed login attempt for user %r.", username)
        return jsonify(error="Invalid credentials."), 401

    session["user"] = username
    return jsonify(status="ok", user=username), 200


# ---------------------------------------------------------------------------
# Projects and Firewalls
# ---------------------------------------------------------------------------

@api_bp.route("/projects", methods=["GET", "POST"])
def projects():
    if request.method == "POST":
        data = request.get_json(force=True, silent=True) or {}

        name = (data.get("name") or "").strip()
        description = data.get("description")
        raw_ids = data.get("firewall_ids") or []

        if not name:
            raise ValidationError("Project name is required.")

        if not isinstance(raw_ids, list):
            raise ValidationError("firewall_ids must be a list.")

        project = Project(name=name, description=description)
        db.session.add(project)
        db.session.flush()

        attached = []

        for raw in raw_ids:
            try:
                firewall_id = int(raw)
            except (TypeError, ValueError) as exc:
                db.session.rollback()
                raise ValidationError("firewall_ids must contain integers.") from exc

            firewall = Firewall.query.get(firewall_id)

            if firewall is None:
                db.session.rollback()
                raise ValidationError(f"Firewall {firewall_id} does not exist.")

            # Attaching moves the firewall (and its objects) to the new project.
            firewall.set_project(project.id)
            attached.append(firewall.name)

        try:
            db.session.commit()
        except IntegrityError as exc:
            db.session.rollback()
            raise ValidationError("Project already exists or violates a database constraint.") from exc

        payload = _project_payload(project)
        payload["attached"] = attached

        return jsonify(status="ok", item=payload), 201

    items = [_project_payload(p) for p in Project.query.order_by(Project.name).all()]
    return jsonify(items=items), 200


@api_bp.route("/firewalls", methods=["GET", "POST"])
def firewalls():
    if request.method == "POST":
        data = request.get_json(force=True, silent=True) or {}

        project_id = data.get("project_id")
        name = (data.get("name") or "").strip()
        vendor = (data.get("vendor") or "").lower().strip()
        model = (data.get("model") or "").strip() or None
        management_ip = data.get("management_ip")
        auth_mode = (data.get("auth_mode") or "password").lower().strip()
        api_username = data.get("api_username")
        api_password = data.get("api_password")
        api_token = data.get("api_token")
        description = data.get("description")

        if not name:
            raise ValidationError("Firewall name is required.")

        if vendor not in registered_vendors():
            raise ValidationError(
                f"Unsupported vendor '{vendor}'. Supported vendors: {', '.join(registered_vendors())}"
            )

        if auth_mode not in ("password", "token"):
            raise ValidationError("auth_mode must be 'password' or 'token'.")

        # Optional: the firewall can be created without a project (unassigned).
        project = Project.query.get_or_404(project_id) if project_id else None

        firewall = Firewall(
            project_id=project.id if project else None,
            name=name,
            vendor=vendor,
            model=model,
            management_ip=management_ip,
            auth_mode=auth_mode,
            api_username=api_username if auth_mode == "password" else None,
            api_password=api_password if auth_mode == "password" else None,
            api_token=api_token if auth_mode == "token" else None,
            description=description,
        )

        db.session.add(firewall)

        try:
            db.session.commit()
        except IntegrityError as exc:
            db.session.rollback()
            raise ValidationError("Firewall already exists in this project or violates a constraint.") from exc

        return jsonify(status="ok", item=firewall.to_dict()), 201

    items = []

    for fw in Firewall.query.order_by(Firewall.name).all():
        data = fw.to_dict()
        # Dashboard extras: owning project (null when unassigned) and counts
        # of active objects (total + per type).
        active = [obj for obj in fw.config_objects if not obj.is_deleted]
        types_counts = {}

        for obj in active:
            types_counts[obj.object_type] = types_counts.get(obj.object_type, 0) + 1

        data["project"] = fw.project.to_dict() if fw.project else None
        data["objects_count"] = len(active)
        data["has_config"] = len(active) > 0
        data["types_counts"] = types_counts
        items.append(data)

    return jsonify(items=items), 200


@api_bp.route("/firewalls/<int:firewall_id>", methods=["GET", "POST", "PATCH"])
def firewall_detail(firewall_id):
    """Get one firewall, or update it.

    GET returns the full record (the list endpoint hides credentials, so the
    edit form fetches them here). POST/PATCH update the firewall with the
    same fields as the creation wizard — the body is expected to carry the
    complete set (name, vendor, model, management_ip, auth_mode,
    api_username, api_password, api_token, description); an empty string
    clears a field. `project_id` is optional and may be an integer or null
    to reassign / unassign the firewall (objects follow via set_project()).
    """
    firewall = Firewall.query.get_or_404(firewall_id)

    if request.method == "GET":
        data = firewall.to_dict()
        data["api_username"] = firewall.api_username
        data["api_password"] = firewall.api_password
        data["api_token"] = firewall.api_token
        active = [obj for obj in firewall.config_objects if not obj.is_deleted]
        data["project"] = firewall.project.to_dict() if firewall.project else None
        data["objects_count"] = len(active)
        data["has_config"] = len(active) > 0
        return jsonify(item=data), 200

    data = request.get_json(force=True, silent=True) or {}

    name = (data.get("name") or "").strip()
    if not name:
        raise ValidationError("Firewall name is required.")

    vendor = (data.get("vendor") or "").lower().strip()
    if vendor not in registered_vendors():
        raise ValidationError(
            f"Unsupported vendor '{vendor}'. Supported vendors: {', '.join(registered_vendors())}"
        )

    auth_mode = (data.get("auth_mode") or firewall.auth_mode or "password").lower().strip()
    if auth_mode not in ("password", "token"):
        raise ValidationError("auth_mode must be 'password' or 'token'.")

    # Optional reassignment: keeps the objects' project_id in sync.
    if "project_id" in data:
        raw_project_id = data.get("project_id")
        if raw_project_id in (None, ""):
            firewall.set_project(None)
        else:
            try:
                project = Project.query.get_or_404(int(raw_project_id))
            except (TypeError, ValueError) as exc:
                raise ValidationError("project_id must be an integer or null.") from exc
            firewall.set_project(project.id)

    firewall.name = name
    firewall.vendor = vendor
    firewall.model = (data.get("model") or "").strip() or None
    firewall.management_ip = (data.get("management_ip") or "").strip() or None
    firewall.auth_mode = auth_mode
    firewall.api_username = (data.get("api_username") or "").strip() or None
    firewall.api_password = (data.get("api_password") or "").strip() or None
    firewall.api_token = (data.get("api_token") or "").strip() or None
    firewall.description = (data.get("description") or "").strip() or None

    # Credentials follow the selected auth mode: the inactive side is cleared.
    if auth_mode == "password":
        firewall.api_token = None
    else:
        firewall.api_username = None
        firewall.api_password = None

    try:
        db.session.commit()
    except IntegrityError as exc:
        db.session.rollback()
        raise ValidationError(
            f"A firewall named '{name}' already exists in that project."
        ) from exc

    return jsonify(status="ok", item=firewall.to_dict()), 200


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

@api_bp.route("/import", methods=["POST"])
def import_config():
    firewall_id = _get_firewall_id()
    selected_types = _get_selected_types()

    if request.is_json:
        data = request.get_json(silent=True) or {}
        source_type = (data.get("source_type") or "file").lower()
        url = data.get("url")
    else:
        source_type = (request.form.get("source_type") or "file").lower()
        url = request.form.get("url")

    firewall = Firewall.query.get_or_404(firewall_id)

    raw_data = ""

    try:
        if source_type == "file":
            file = request.files.get("config_file")
            if not file or not file.filename:
                raise ValidationError("No configuration file uploaded.")

            raw_data = file.read().decode("utf-8", errors="replace")

        elif source_type == "url":
            raw_data = _fetch_remote_config(firewall, url)

        else:
            raise ValidationError("source_type must be 'file' or 'url'.")

    except VendorAPIError as error:
        return jsonify(error=error.message), error.status

    vendor = (firewall.vendor or "").strip().lower() or _detect_vendor(raw_data)

    try:
        parser = get_parser(vendor)
    except ValueError as exc:
        raise UnsupportedVendorError(str(exc)) from exc

    try:
        parsed = parser.parse_config(raw_data, selected_types)
    except ParsingError as exc:
        raise ValidationError(str(exc)) from exc
    except Exception as exc:
        logger.exception("Parser failed for vendor %s.", vendor)
        raise ValidationError(f"Failed to parse configuration: {exc}") from exc

    user = current_user()
    counts = {}

    try:
        for obj_data in parsed.objects:
            object_type = obj_data.get("object_type")

            if object_type not in selected_types:
                continue

            _, action = _upsert_object(firewall, obj_data, user)
            counts[object_type] = counts.get(object_type, 0) + 1

        firewall.last_sync_at = datetime.now(timezone.utc)
        db.session.commit()

    except IntegrityError as exc:
        db.session.rollback()
        raise ValidationError("Import failed due to database constraint violation.") from exc

    return jsonify(
        status="ok",
        message=f"Imported {sum(counts.values())} objects.",
        counts=counts,
        warnings=parsed.warnings,
    ), 200


@api_bp.route("/import/stream", methods=["POST"])
def import_config_stream():
    """Import with NDJSON progress events (one JSON object per line).

    Events: {"event":"progress", stage, percent, detail} ... and finally
    {"event":"done", ...} or {"event":"error", error}. For REST sources the
    download itself is streamed so the progress bar reflects the transfer.
    """
    firewall_id = _get_firewall_id()
    selected_types = _get_selected_types()

    source_type = (request.form.get("source_type") or "file").lower()
    url = request.form.get("url")

    firewall = Firewall.query.get_or_404(firewall_id)

    file_bytes = None

    if source_type == "file":
        file = request.files.get("config_file")
        if not file or not file.filename:
            raise ValidationError("No configuration file uploaded.")
        file_bytes = file.read()
    elif source_type == "url":
        if not url:
            raise ValidationError("url is required when source_type=url.")
    else:
        raise ValidationError("source_type must be 'file' or 'url'.")

    auth = None

    if source_type == "url" and firewall.api_username and firewall.api_password:
        auth = (firewall.api_username, firewall.api_password)

    # Capture everything the generator needs NOW: a streamed response keeps
    # producing after the request context is gone, so the generator runs in
    # a fresh application context (same DB, valid ORM session).
    app_obj = current_app._get_current_object()
    firewall_id_captured = firewall.id
    vendor_captured = (firewall.vendor or "").strip().lower() or None
    user_captured = current_user()

    def generate():
        with app_obj.app_context():
            if source_type == "url":
                yield _progress_line("connect", 5, f"Connecting to {url}...")

                try:
                    response = requests.get(url, auth=auth, stream=True, timeout=30)
                except requests.RequestException as exc:
                    yield json.dumps({"event": "error", "error": f"Network error contacting {url}: {exc}"}) + "\n"
                    return

                if response.status_code in (401, 403):
                    yield json.dumps({"event": "error", "error": "Failed to login/authenticate to firewall API."}) + "\n"
                    return

                try:
                    response.raise_for_status()
                except requests.HTTPError as exc:
                    yield json.dumps(
                        {"event": "error", "error": f"Firewall API returned HTTP {response.status_code}: {exc}"}
                    ) + "\n"
                    return

                yield _progress_line("connected", 15, "Connected — downloading configuration...")

                total_length = 0

                try:
                    total_length = int(response.headers.get("Content-Length") or 0)
                except (TypeError, ValueError):
                    total_length = 0

                chunks = []
                received = 0

                for chunk in response.iter_content(chunk_size=65536):
                    if not chunk:
                        continue

                    chunks.append(chunk)
                    received += len(chunk)

                    if total_length > 0:
                        percent = 15 + int(45 * received / total_length)
                    else:
                        percent = min(60, 15 + int(received / 65536))

                    yield _progress_line(
                        "download", min(percent, 60), f"Downloaded {received // 1024} KB..."
                    )

                raw_data = b"".join(chunks).decode("utf-8", errors="replace")
                yield from _stream_parse_and_import(
                    firewall_id_captured, vendor_captured, selected_types, raw_data, user_captured, 65, 95
                )
            else:
                raw_data = file_bytes.decode("utf-8", errors="replace")
                yield from _stream_parse_and_import(
                    firewall_id_captured, vendor_captured, selected_types, raw_data, user_captured, 25, 95
                )

    return _ndjson_response(generate())


# ---------------------------------------------------------------------------
# Connectivity
# ---------------------------------------------------------------------------

@api_bp.route("/connectivity", methods=["POST"])
def check_connectivity():
    """Check the reachability of a firewall management endpoint.

    Accepts either {"firewall_id": N} (stored firewall) or the raw wizard
    fields {management_ip, vendor, auth_mode, api_username, api_password,
    api_token} for a firewall that does not exist yet.
    """
    data = request.get_json(force=True, silent=True) or {}

    if data.get("firewall_id"):
        firewall = Firewall.query.get_or_404(int(data["firewall_id"]))
        result = _check_connectivity_data(
            firewall.management_ip,
            firewall.vendor,
            firewall.auth_mode,
            firewall.api_username,
            firewall.api_password,
            firewall.api_token,
        )
    else:
        result = _check_connectivity_data(
            (data.get("management_ip") or "").strip(),
            data.get("vendor"),
            data.get("auth_mode"),
            data.get("api_username"),
            data.get("api_password"),
            data.get("api_token"),
        )

    return jsonify(result), 200


# ---------------------------------------------------------------------------
# Object CRUD
# ---------------------------------------------------------------------------

@api_bp.route("/objects", methods=["GET"])
def list_objects():
    query = ConfigObject.query.options(db.joinedload(ConfigObject.firewall))

    include_deleted = request.args.get("include_deleted", "false").lower() in ("1", "true")
    if not include_deleted:
        query = query.filter(ConfigObject.is_deleted == False)  # noqa: E712

    project_id = request.args.get("project_id")
    firewall_id = request.args.get("firewall_id")
    object_type = request.args.get("object_type")
    name = request.args.get("name")

    if project_id:
        query = query.filter(ConfigObject.project_id == int(project_id))

    if firewall_id:
        query = query.filter(ConfigObject.firewall_id == int(firewall_id))

    if object_type:
        query = query.filter(ConfigObject.object_type == object_type)

    if name:
        query = query.filter(ConfigObject.name.ilike(f"%{name}%"))

    description = request.args.get("description")
    if description:
        query = query.filter(ConfigObject.description.ilike(f"%{description}%"))

    # JSON payload filters (normalized parser payload keys) — the object list
    # page offers any of these as the search field.
    # Requires SQLite JSON1 or PostgreSQL JSON support.
    for field in PAYLOAD_SEARCH_KEYS:
        value = request.args.get(field)
        if value:
            query = query.filter(ConfigObject.payload[field].as_string().like(f"%{value}%"))

    # Generic search across name, description and every payload field
    # ("Any field" in the object list search box).
    search = request.args.get("search")
    if search:
        term = f"%{search}%"
        clauses = [
            ConfigObject.name.ilike(term),
            ConfigObject.description.ilike(term),
        ]
        for field in PAYLOAD_SEARCH_KEYS:
            clauses.append(ConfigObject.payload[field].as_string().like(term))
        query = query.filter(or_(*clauses))

    sort_by = request.args.get("sort", "name")
    allowed_sorts = {"id", "name", "object_type", "created_at", "updated_at"}

    if sort_by not in allowed_sorts:
        sort_by = "name"

    order = request.args.get("order", "asc").lower()
    column = getattr(ConfigObject, sort_by)

    query = query.order_by(column.desc() if order == "desc" else column.asc())

    try:
        page = max(1, int(request.args.get("page", 1)))
        per_page = min(max(1, int(request.args.get("per_page", 25))), 500)
    except ValueError:
        raise ValidationError("page and per_page must be integers.")

    total = query.count()
    total_pages = max(1, -(-total // per_page))
    items = query.offset((page - 1) * per_page).limit(per_page).all()

    return jsonify(
        items=[_serialize_object(obj) for obj in items],
        total=total,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
    ), 200


@api_bp.route("/objects/export-include", methods=["POST"])
def set_export_inclusion():
    """Tag (or untag) objects as "included in the config export".

    The object list page tags the checked rows; the export wizard
    pre-selects tagged objects per object type.
    """
    data = request.get_json(force=True, silent=True) or {}
    raw_ids = data.get("object_ids") or []
    include = bool(data.get("include", True))

    object_ids = []
    for item in raw_ids:
        try:
            object_ids.append(int(item))
        except (TypeError, ValueError):
            continue

    if not object_ids:
        raise ValidationError("Select at least one object to tag.")

    objects = ConfigObject.query.filter(ConfigObject.id.in_(object_ids)).all()
    for obj in objects:
        obj.export_included = include

    db.session.commit()

    return (
        jsonify(
            status="ok",
            include=include,
            count=len(objects),
            message=(
                f"{len(objects)} object{'s' if len(objects) != 1 else ''} "
                + ("tagged for export." if include else "removed from the export.")
            ),
        ),
        200,
    )


@api_bp.route("/objects", methods=["POST"])
def create_object():
    """Create a new object (or upsert when the firewall/type/name exists)."""
    data = request.get_json(force=True, silent=True) or {}

    firewall_id = data.get("firewall_id")
    object_type = (data.get("object_type") or "").strip()
    name = (data.get("name") or "").strip()

    if not firewall_id:
        raise ValidationError("firewall_id is required.")

    if object_type not in ALLOWED_OBJECT_TYPES:
        raise ValidationError("A valid object_type is required.")

    if not name:
        raise ValidationError("name is required.")

    payload = data.get("payload") or {}

    if not isinstance(payload, dict):
        raise ValidationError("payload must be a JSON object.")

    firewall = Firewall.query.get_or_404(int(firewall_id))
    user = current_user()

    obj, action = _upsert_object(
        firewall,
        {
            "object_type": object_type,
            "name": name,
            "description": data.get("description"),
            "payload": payload,
        },
        user,
    )

    try:
        db.session.commit()
    except IntegrityError as exc:
        db.session.rollback()
        raise ValidationError("Object could not be saved (constraint violation).") from exc

    return jsonify(status="ok", action=action, item=_serialize_object(obj)), 201


@api_bp.route("/objects/commit", methods=["POST"])
def commit_objects():
    """Commit a batch of staged changes (create / update / delete) atomically.

    Used by the object list page: edits are staged client-side and applied to
    the database in a single transaction when the user clicks **Validate**.
    """
    data = request.get_json(force=True, silent=True) or {}
    changes = data.get("changes")

    if not isinstance(changes, list) or not changes:
        raise ValidationError("Provide a non-empty 'changes' list.")

    user = current_user()
    summary = {"created": 0, "updated": 0, "deleted": 0}

    try:
        for index, change in enumerate(changes):
            label = f"Change #{index + 1}"

            if not isinstance(change, dict):
                raise ValidationError(f"{label} is not an object.")

            op = (change.get("op") or "").lower()

            if op == "create":
                firewall_id = change.get("firewall_id")
                object_type = (change.get("object_type") or "").strip()
                name = (change.get("name") or "").strip()

                if not firewall_id:
                    raise ValidationError(f"{label} (create): firewall_id is required.")

                if object_type not in ALLOWED_OBJECT_TYPES:
                    raise ValidationError(f"{label} (create): a valid object_type is required.")

                if not name:
                    raise ValidationError(f"{label} (create): name is required.")

                payload = change.get("payload") or {}

                if not isinstance(payload, dict):
                    raise ValidationError(f"{label} (create): payload must be a JSON object.")

                firewall = Firewall.query.get_or_404(int(firewall_id))
                _obj, action = _upsert_object(
                    firewall,
                    {
                        "object_type": object_type,
                        "name": name,
                        "description": change.get("description"),
                        "payload": payload,
                    },
                    user,
                )
                summary["created" if action == "create" else "updated"] += 1

            elif op == "update":
                object_id = change.get("id")

                try:
                    obj = ConfigObject.query.get_or_404(int(object_id))
                except (TypeError, ValueError) as exc:
                    raise ValidationError(f"{label} (update): invalid id.") from exc

                if obj.is_deleted:
                    raise ValidationError(f"{label} (update): object {object_id} is in the trash.")

                changed_fields = []

                for field in ("name", "description"):
                    if field in change and change[field] != getattr(obj, field):
                        old_value = getattr(obj, field)
                        setattr(obj, field, change[field])
                        changed_fields.append((field, old_value, change[field]))

                if "payload" in change:
                    new_payload = change["payload"]

                    if not isinstance(new_payload, dict):
                        raise ValidationError(f"{label} (update): payload must be a JSON object.")

                    if new_payload != (obj.payload or {}):
                        changed_fields.append(("payload", obj.payload or {}, new_payload))
                        obj.payload = new_payload

                if not changed_fields:
                    continue

                for field, old_value, new_value in changed_fields:
                    log_change(
                        config_object=obj,
                        field=field,
                        old_value=old_value,
                        new_value=new_value,
                        action="update",
                        user=user,
                    )

                obj.fingerprint = _fingerprint(obj.object_type, obj.name, obj.payload or {})
                obj.updated_by = user
                summary["updated"] += 1

            elif op == "delete":
                object_id = change.get("id")

                try:
                    obj = ConfigObject.query.get_or_404(int(object_id))
                except (TypeError, ValueError) as exc:
                    raise ValidationError(f"{label} (delete): invalid id.") from exc

                if obj.is_deleted:
                    continue

                log_change(
                    config_object=obj,
                    field="payload",
                    old_value=obj.payload or {},
                    new_value=None,
                    action="delete",
                    user=user,
                )
                obj.soft_delete(user=user, reason=change.get("reason") or "Deleted from UI")
                summary["deleted"] += 1

            else:
                raise ValidationError(f"{label}: unknown op '{op}'.")

        db.session.commit()
    except (ValidationError, HTTPException):
        db.session.rollback()
        raise
    except IntegrityError as exc:
        db.session.rollback()
        raise ValidationError("Commit failed due to a database constraint violation.") from exc

    return jsonify(
        status="ok",
        message=f"Committed {sum(summary.values())} change(s) to the database.",
        summary=summary,
    ), 200


@api_bp.route("/objects/<int:object_id>", methods=["POST"])
def update_object(object_id):
    """
    Update an existing object and write modification history.

    This route uses POST to match the requested CRUD style.
    For stricter REST semantics, you can also expose PUT/PATCH.
    """
    obj = ConfigObject.query.get_or_404(object_id)

    if obj.is_deleted:
        raise ValidationError("Object is in trash. Restore it before editing.")

    data = request.get_json(force=True, silent=True) or {}
    user = current_user()

    changed_fields = []

    if "object_type" in data and data["object_type"] != obj.object_type:
        raise ValidationError("object_type cannot be changed after creation.")

    for field in ("name", "description"):
        if field in data:
            old_value = getattr(obj, field)
            new_value = data[field]

            if old_value != new_value:
                setattr(obj, field, new_value)
                changed_fields.append((field, old_value, new_value))

    if "payload" in data:
        new_payload = data["payload"]

        if not isinstance(new_payload, dict):
            raise ValidationError("payload must be a JSON object.")

        old_payload = obj.payload or {}

        if old_payload != new_payload:
            changed_fields.append(("payload", old_payload, new_payload))
            obj.payload = new_payload

    if not changed_fields:
        return jsonify(status="ok", message="No changes detected."), 200

    for field, old_value, new_value in changed_fields:
        log_change(
            config_object=obj,
            field=field,
            old_value=old_value,
            new_value=new_value,
            action="update",
            user=user,
        )

    obj.fingerprint = _fingerprint(obj.object_type, obj.name, obj.payload or {})
    obj.updated_by = user

    try:
        db.session.commit()
    except IntegrityError as exc:
        db.session.rollback()
        raise ValidationError("Update failed due to database constraint violation.") from exc

    return jsonify(status="ok", item=_serialize_object(obj)), 200


@api_bp.route("/objects/<int:object_id>", methods=["DELETE"])
def delete_object(object_id):
    obj = ConfigObject.query.get_or_404(object_id)

    if obj.is_deleted:
        raise ValidationError("Object is already in trash.")

    user = current_user()
    reason = request.args.get("reason") or "Deleted from UI"

    log_change(
        config_object=obj,
        field="payload",
        old_value=obj.payload or {},
        new_value=None,
        action="delete",
        user=user,
    )

    obj.soft_delete(user=user, reason=reason)

    try:
        db.session.commit()
    except IntegrityError as exc:
        db.session.rollback()
        raise ValidationError("Delete failed due to database constraint violation.") from exc

    return jsonify(status="ok", message="Object moved to trash."), 200


@api_bp.route("/objects/<int:object_id>/history", methods=["GET"])
def object_history(object_id):
    obj = ConfigObject.query.get_or_404(object_id)

    histories = (
        ModificationHistory.query.filter_by(config_object_id=obj.id)
        .order_by(ModificationHistory.created_at.desc())
        .all()
    )

    items = [
        {
            "id": h.id,
            "field": h.field,
            "old_value": h.old_value,
            "new_value": h.new_value,
            "action": h.action,
            "user": h.user,
            "created_at": h.created_at.isoformat() if h.created_at else None,
        }
        for h in histories
    ]

    return jsonify(items=items), 200


# ---------------------------------------------------------------------------
# Trash
# ---------------------------------------------------------------------------

@api_bp.route("/trash", methods=["GET"])
def trash_list():
    query = (
        Trash.query.filter(Trash.restored_at.is_(None))
        .options(db.joinedload(Trash.config_object))
        .order_by(Trash.deleted_at.desc())
    )

    items = []

    for trash in query.all():
        obj = trash.config_object
        if not obj:
            continue

        items.append(
            {
                "trash_id": trash.id,
                "deleted_by": trash.deleted_by,
                "deleted_at": trash.deleted_at.isoformat() if trash.deleted_at else None,
                "reason": trash.reason,
                "object": _serialize_object(obj),
            }
        )

    return jsonify(items=items), 200


@api_bp.route("/trash/<int:trash_id>/restore", methods=["POST"])
def restore_trash(trash_id):
    trash = Trash.query.get_or_404(trash_id)

    if trash.restored_at is not None:
        raise ValidationError("Object has already been restored.")

    obj = trash.config_object
    user = current_user()

    log_change(
        config_object=obj,
        field="status",
        old_value="deleted",
        new_value="active",
        action="restore",
        user=user,
    )

    obj.restore(user=user)

    try:
        db.session.commit()
    except IntegrityError as exc:
        db.session.rollback()
        raise ValidationError("Restore failed due to database constraint violation.") from exc

    return jsonify(status="ok", message="Object restored."), 200


# ---------------------------------------------------------------------------
# Export / Push
# ---------------------------------------------------------------------------

@api_bp.route("/export", methods=["POST"])
def export_config():
    data = request.get_json(force=True, silent=True) or {}

    firewall_id = data.get("firewall_id")
    object_types = _normalize_type_list(data.get("object_types"))
    tagged_only_types = _normalize_type_list(data.get("tagged_only_types"))
    fmt = (data.get("format") or "xml").strip().lower()
    mode = (data.get("mode") or "download").lower()

    if not firewall_id:
        raise ValidationError("firewall_id is required.")

    if not object_types:
        object_types = ALLOWED_OBJECT_TYPES

    invalid = [t for t in object_types if t not in ALLOWED_OBJECT_TYPES]
    if invalid:
        raise ValidationError(f"Unsupported object types: {', '.join(invalid)}")

    firewall = Firewall.query.get_or_404(int(firewall_id))

    if firewall.vendor == "paloalto" and fmt not in ("xml", "set"):
        raise ValidationError("format must be 'xml' or 'set' for Palo Alto.")

    config_text, objects, _counts = _build_config(
        firewall, object_types, tagged_only_types, format=fmt
    )

    if mode == "download":
        filename, mimetype = _export_file_name(firewall, fmt)

        return Response(
            config_text,
            mimetype=mimetype,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"'
            },
        )

    if mode == "push":
        try:
            _mock_push_config(firewall, config_text)
        except VendorAPIError as error:
            return jsonify(error=error.message), error.status

        firewall.last_sync_at = datetime.now(timezone.utc)
        db.session.commit()

        return jsonify(
            status="ok",
            message=f"Pushed {len(objects)} objects to {firewall.name}.",
        ), 200

    raise ValidationError("mode must be 'download' or 'push'.")


@api_bp.route("/export/file", methods=["POST"])
def export_file():
    """Generate a vendor configuration file and return a temporary download link.

    ``format`` (Palo Alto only): ``xml`` (PAN-OS ``<paloalto>`` document,
    .xml) or ``set`` (set/`show` format, .txt). ``tagged_only_types``
    restricts the listed types to the objects tagged "Include in the
    export".
    """
    data = request.get_json(force=True, silent=True) or {}

    firewall_id = data.get("firewall_id")
    object_types = _normalize_type_list(data.get("object_types"))
    tagged_only_types = _normalize_type_list(data.get("tagged_only_types"))
    fmt = (data.get("format") or "xml").strip().lower()

    if not firewall_id:
        raise ValidationError("firewall_id is required.")

    if not object_types:
        object_types = ALLOWED_OBJECT_TYPES

    invalid = [t for t in object_types if t not in ALLOWED_OBJECT_TYPES]
    if invalid:
        raise ValidationError(f"Unsupported object types: {', '.join(invalid)}")

    firewall = Firewall.query.get_or_404(int(firewall_id))

    if firewall.vendor == "paloalto" and fmt not in ("xml", "set"):
        raise ValidationError("format must be 'xml' or 'set' for Palo Alto.")

    config_text, objects, counts = _build_config(
        firewall, object_types, tagged_only_types, format=fmt
    )

    filename, mimetype = _export_file_name(firewall, fmt)

    _prune_artifacts()
    token = secrets.token_urlsafe(16)
    _export_artifacts[token] = (
        filename,
        config_text,
        mimetype,
        datetime.now(timezone.utc),
    )

    return (
        jsonify(
            status="ok",
            token=token,
            download_url=f"/api/export/file/{token}",
            filename=filename,
            size_bytes=len(config_text.encode("utf-8")),
            object_count=len(objects),
            counts=counts,
        ),
        200,
    )


@api_bp.route("/export/file/<token>", methods=["GET"])
def download_export_file(token):
    """Serve a previously generated export file (kept for 1 hour)."""
    artifact = _export_artifacts.get(token)

    if artifact is None:
        raise ValidationError("Download expired or unknown. Generate a new file.")

    filename, content, mimetype, _ts = artifact

    return Response(
        content,
        mimetype=mimetype,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@api_bp.route("/export/push", methods=["POST"])
def export_push_stream():
    """Push a generated configuration to the destination firewall.

    Streams NDJSON progress events (generate → connect → authenticate →
    transfer → confirm) and finishes with a done/error event. The actual
    vendor call is the existing mock (real endpoints land with the
    "Real vendor push" backlog item).
    """
    data = request.get_json(force=True, silent=True) or {}

    firewall_id = data.get("firewall_id")
    object_types = _normalize_type_list(data.get("object_types"))
    tagged_only_types = _normalize_type_list(data.get("tagged_only_types"))
    fmt = (data.get("format") or "xml").strip().lower()

    if not firewall_id:
        raise ValidationError("firewall_id is required.")

    if not object_types:
        object_types = ALLOWED_OBJECT_TYPES

    invalid = [t for t in object_types if t not in ALLOWED_OBJECT_TYPES]
    if invalid:
        raise ValidationError(f"Unsupported object types: {', '.join(invalid)}")

    Firewall.query.get_or_404(int(firewall_id))  # 404 up front

    # Streamed responses outlive the request context: capture what is needed
    # and run the DB work in a fresh application context.
    app_obj = current_app._get_current_object()

    def generate():
        with app_obj.app_context():
            firewall = Firewall.query.get_or_404(int(firewall_id))

            yield _progress_line("generate", 10, "Generating configuration...")

            try:
                config_text, objects, counts = _build_config(
                    firewall, object_types, tagged_only_types, format=fmt
                )
            except ValidationError as exc:
                yield json.dumps({"event": "error", "error": str(exc)}) + "\n"
                return

            yield _progress_line("ready", 40, f"Generated configuration for {len(objects)} objects.")
            yield _progress_line("connect", 55, f"Connecting to {firewall.name}...")
            time.sleep(0.4)
            yield _progress_line("auth", 65, "Authenticating...")
            time.sleep(0.4)
            yield _progress_line("transfer", 80, "Transferring configuration...")
            time.sleep(0.6)

            try:
                _mock_push_config(firewall, config_text)
            except VendorAPIError as error:
                yield json.dumps({"event": "error", "error": error.message}) + "\n"
                return

            yield _progress_line("confirm", 95, "Confirming...")
            time.sleep(0.3)

            firewall.last_sync_at = datetime.now(timezone.utc)
            db.session.commit()

            yield (
                json.dumps(
                    {
                        "event": "done",
                        "status": "ok",
                        "message": f"Pushed {len(objects)} objects to {firewall.name}.",
                        "object_count": len(objects),
                        "counts": counts,
                    }
                )
                + "\n"
            )

    return _ndjson_response(generate())
