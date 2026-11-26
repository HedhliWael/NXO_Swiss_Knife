"""Authentication for NXO Swiss Knife.

Session-based user/password authentication:

- Accounts live in a **separate database file** (``instance/users.db``,
  the ``User`` model bound to the ``users`` database — see
  ``app/factory.py`` and ``app/models.py``).
- Passwords are hashed with :mod:`werkzeug.security` (``scrypt`` + random
  per-password salt) — never stored or compared in plain text.
- Every page and API route is protected by the ``before_request`` login
  guard: unauthenticated browsers are redirected to ``/login`` (with
  ``next=``, so the original page is restored after signing in) and
  unauthenticated API clients get a JSON ``401``.
- Login sets a bounded session (default 8 h) in an HttpOnly,
  SameSite=Lax cookie (Secure when ``SWISSKNIFE_SESSION_SECURE=1``);
  the session is cleared before new login data is stored (no session
  fixation).
- The first start bootstraps the initial ``admin`` account
  (``ensure_admin_user``) — password from ``SWISSKNIFE_ADMIN_PASS`` or,
  when the variable is not set, a random password printed to the server
  console once.
- ``/api/users`` manages the accounts (add, list, reset password,
  enable/disable, delete) — the dashboard's Users section.
"""

import logging
import os
import re
import secrets
import time
from datetime import datetime, timezone

from flask import (
    Blueprint,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.exceptions import HTTPException
from werkzeug.security import check_password_hash, generate_password_hash

from .errors import ValidationError
from .extensions import db
from .models import User

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------


def hash_password(password: str) -> str:
    """Hash a password for storage (scrypt, random 16-byte salt)."""
    return generate_password_hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Constant-time comparison of a password with its stored hash."""
    try:
        return check_password_hash(password_hash, password)
    except Exception:  # malformed stored hash — treat as invalid
        return False


def generate_password(length: int = 12) -> str:
    """A strong one-shot password (URL-safe, 16 characters for length=12)."""
    return secrets.token_urlsafe(length)


# ---------------------------------------------------------------------------
# Authentication core (shared by the form login and the JSON API login)
# ---------------------------------------------------------------------------

# A real hash of a throw-away password: verifying against it costs the
# same time as a real check, so "user does not exist" answers take the same
# time as "wrong password" (no user enumeration by timing).
_DUMMY_HASH = generate_password_hash("timing-equalizer-dummy")

USERNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,63}$")
PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128
# Delay on failed logins — slows down online brute force for a local tool
# (there is no persistent lockout; see PROJECT.md "Known issues").
LOGIN_FAILURE_DELAY_SECONDS = 0.5


def authenticate(username, password):
    """Look up the user and verify the password.

    Returns the ``User`` on success, ``None`` otherwise. Disabled users
    are rejected with the same generic result (the hash is still checked
    first, so the answer timing does not reveal which account exists).
    """
    if not username or not password:
        return None

    user = User.query.filter_by(username=username).first()

    if user is None:
        # Burn one hash check so a missing user costs the same time as a
        # bad password (no user enumeration by timing).
        verify_password(password, _DUMMY_HASH)
        return None

    if not user.check_password(password):
        return None

    if not user.is_active:
        return None

    return user


def _login_session(user):
    """Store the login in a fresh session (no session fixation)."""
    session.clear()
    session["user_id"] = user.id
    session["username"] = user.username
    user.last_login_at = datetime.now(timezone.utc)
    db.session.commit()


def _safe_next(next_url):
    """Only relative, same-origin paths may be used as a redirect target."""
    if (
        not next_url
        or not next_url.startswith("/")
        or next_url.startswith("//")
        or "\n" in next_url
        or "\r" in next_url
    ):
        return "/"
    return next_url


# ---------------------------------------------------------------------------
# Web login / logout
# ---------------------------------------------------------------------------

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """Login page (GET) and form handler (POST)."""
    if session.get("user_id"):
        return redirect(url_for("views.dashboard"))

    next_url = _safe_next(request.args.get("next") or "")

    if request.method == "POST":
        # The form carries the original target in a hidden field (the failed
        # login re-render must not lose it), falling back to the query string.
        next_url = _safe_next(request.form.get("next") or next_url)
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""

        user = authenticate(username, password)

        if user is None:
            logger.warning(
                "Failed login attempt for user %r from %s.",
                username,
                request.remote_addr,
            )
            time.sleep(LOGIN_FAILURE_DELAY_SECONDS)
            flash("Invalid username or password.", "error")
            return render_template("login.html", next_url=next_url), 401

        _login_session(user)
        logger.info("User %r signed in from %s.", username, request.remote_addr)
        flash(f"Signed in as {user.username}.", "success")
        return redirect(next_url or url_for("views.dashboard"))

    return render_template("login.html", next_url=next_url)


@auth_bp.route("/logout", methods=["POST"])
def logout():
    """Sign out (POST only — a plain link would allow forced logout)."""
    username = session.get("username")
    session.clear()
    if username:
        logger.info("User %r signed out.", username)
    return redirect(url_for("auth.login"))


# ---------------------------------------------------------------------------
# JSON auth endpoints (API clients + the UI's own "who am I")
# ---------------------------------------------------------------------------

api_auth_bp = Blueprint("api_auth", __name__, url_prefix="/api/auth")


@api_auth_bp.route("/login", methods=["POST"])
def api_login():
    """Programmatic login (JSON body: username/password).

    Sets the same session cookie as the form login. Replaces the old
    environment-variable placeholder endpoint.
    """
    data = request.get_json(force=True, silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    user = authenticate(username, password)

    if user is None:
        logger.warning(
            "Failed API login attempt for user %r from %s.",
            username,
            request.remote_addr,
        )
        time.sleep(LOGIN_FAILURE_DELAY_SECONDS)
        return jsonify(error="Invalid username or password."), 401

    _login_session(user)
    logger.info("User %r signed in via the API from %s.", username, request.remote_addr)
    return jsonify(status="ok", user=user.username)


@api_auth_bp.route("/me")
def me():
    """The authenticated account (protected by the login guard)."""
    user_id = session.get("user_id")
    user = User.query.get(user_id) if user_id else None

    if user is None:
        return jsonify(error="Not authenticated."), 401

    data = user.to_dict()
    data["display_name"] = user.display_name or user.username
    return jsonify(data)


# ---------------------------------------------------------------------------
# User management API (dashboard → Users section)
# ---------------------------------------------------------------------------

users_bp = Blueprint("users", __name__, url_prefix="/api/users")


def _active_user_count():
    return User.query.filter_by(is_active=True).count()


@users_bp.route("")
@users_bp.route("/")
def list_users():
    """All accounts (never the password hashes), newest first by username."""
    users = User.query.order_by(User.username).all()
    return jsonify([user.to_dict() for user in users])


@users_bp.route("", methods=["POST"])
def create_user():
    """Create an account.

    Body: ``username`` (required), ``display_name`` (optional),
    ``password`` (optional — when omitted, a random password is generated
    and returned once in ``generated_password``).
    """
    data = request.get_json(force=True, silent=True) or {}
    username = (data.get("username") or "").strip()
    display_name = (data.get("display_name") or "").strip() or None
    password = data.get("password") or ""

    if not USERNAME_RE.match(username or ""):
        raise ValidationError(
            "Username must be 2-64 characters: letters, digits, '.', '_' or '-' "
            "(and must start with a letter or digit)."
        )

    if User.query.filter_by(username=username).first() is not None:
        raise ValidationError("A user with this username already exists.")

    if password:
        if len(password) < PASSWORD_MIN_LENGTH:
            raise ValidationError(
                f"Password must be at least {PASSWORD_MIN_LENGTH} characters."
            )
        if len(password) > PASSWORD_MAX_LENGTH:
            raise ValidationError(
                f"Password must be at most {PASSWORD_MAX_LENGTH} characters."
            )
        generated_password = None
    else:
        password = generate_password()
        generated_password = password

    user = User(username=username, display_name=display_name)
    user.set_password(password)
    db.session.add(user)

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise ValidationError("Could not create the user (username taken?).")

    logger.info("User %r created.", username)
    response = {"status": "ok", "user": user.to_dict()}
    if generated_password is not None:
        response["generated_password"] = generated_password
    return jsonify(response)


@users_bp.route("/<int:user_id>", methods=["PATCH"])
def update_user(user_id):
    """Update an account.

    Body (all optional): ``display_name``, ``is_active``,
    ``generate_password`` (true → a new random password is set and returned
    once in ``generated_password``) or ``password`` (explicit new password).
    """
    user = User.query.get_or_404(user_id)
    data = request.get_json(force=True, silent=True) or {}

    if "display_name" in data:
        display_name = (data.get("display_name") or "").strip()
        user.display_name = display_name or None

    if "is_active" in data:
        new_state = bool(data.get("is_active"))
        current_username = session.get("username")

        if not new_state:
            if user.username == current_username:
                raise ValidationError("You cannot disable your own account.")
            if user.is_active and _active_user_count() <= 1:
                raise ValidationError(
                    "At least one active account is required — enable another user first."
                )
        user.is_active = new_state

    generated_password = None

    if data.get("generate_password"):
        generated_password = generate_password()
        user.set_password(generated_password)
    elif data.get("password"):
        new_password = data["password"]
        if len(new_password) < PASSWORD_MIN_LENGTH:
            raise ValidationError(
                f"Password must be at least {PASSWORD_MIN_LENGTH} characters."
            )
        if len(new_password) > PASSWORD_MAX_LENGTH:
            raise ValidationError(
                f"Password must be at most {PASSWORD_MAX_LENGTH} characters."
            )
        user.set_password(new_password)

    db.session.commit()
    logger.info("User %r updated.", user.username)
    response = {"status": "ok", "user": user.to_dict()}
    if generated_password is not None:
        response["generated_password"] = generated_password
    return jsonify(response)


@users_bp.route("/<int:user_id>", methods=["DELETE"])
def delete_user(user_id):
    """Delete an account (its name can be reused afterwards)."""
    user = User.query.get_or_404(user_id)

    if user.username == session.get("username"):
        raise ValidationError("You cannot delete your own account.")

    if user.is_active and _active_user_count() <= 1:
        raise ValidationError(
            "This is the only active account — create or enable another one first."
        )

    db.session.delete(user)
    db.session.commit()
    logger.info("User %r deleted.", user.username)
    return jsonify(status="ok")


# ---------------------------------------------------------------------------
# JSON error handlers for the auth/users blueprints (mirrors the ones of
# api_bp in app/api/routes.py, which only covers that blueprint)
# ---------------------------------------------------------------------------


@api_auth_bp.errorhandler(ValidationError)
@users_bp.errorhandler(ValidationError)
def handle_validation_error(error):
    return jsonify(error=str(error)), getattr(error, "status", 400)


@api_auth_bp.errorhandler(Exception)
@users_bp.errorhandler(Exception)
def handle_unexpected_error(error):
    if isinstance(error, HTTPException):
        return jsonify(error=error.description), error.code

    db.session.rollback()
    logger.exception("Unhandled auth/users API error")
    return jsonify(error="Internal server error."), 500


# ---------------------------------------------------------------------------
# App integration: bootstrap + route guard
# ---------------------------------------------------------------------------

PUBLIC_ENDPOINTS = {"auth.login", "auth.logout", "api_auth.api_login"}


def _require_login():
    """Login guard (``app.before_request``): protects every route
    (pages and API) except the public ones."""
    endpoint = request.endpoint

    if endpoint is None or endpoint == "static" or endpoint in PUBLIC_ENDPOINTS:
        return None

    if session.get("user_id"):
        return None

    if request.path.startswith("/api/"):
        return jsonify(error="Authentication required — sign in first."), 401

    next_url = request.full_path
    if next_url.endswith("?"):
        next_url = next_url[:-1]
    return redirect(url_for("auth.login", next=next_url))


def ensure_admin_user():
    """Create the initial ``admin`` account when the user database is empty.

    Password: ``SWISSKNIFE_ADMIN_PASS`` when set, otherwise a random
    password that is printed to the console **once** (it is stored hashed,
    so it cannot be shown again — change it from the dashboard's Users
    section).
    """
    if User.query.count() > 0:
        return

    username = os.getenv("SWISSKNIFE_ADMIN_USER", "admin").strip() or "admin"
    password = os.getenv("SWISSKNIFE_ADMIN_PASS") or ""
    generated = not password

    if generated:
        password = generate_password()

    user = User(
        username=username,
        display_name="Administrator",
        is_active=True,
    )
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    if generated:
        message = (
            f"[NXO Swiss Knife] User database was empty — created the initial "
            f"account '{username}'. Its password is: {password}\n"
            f"[NXO Swiss Knife] It is stored hashed and will not be shown again. "
            f"Change it from the dashboard (Users section) — or set "
            f"SWISSKNIFE_ADMIN_PASS for a known password."
        )
        logger.warning(message)
        # flush=True: the password is shown exactly once — it must not be
        # lost in a stdout buffer if the process exits right after start.
        print(message, flush=True)
    else:
        logger.info("Created the initial account '%s'.", username)


def init_auth(app):
    """Register the auth blueprints and the login guard on the app."""
    app.before_request(_require_login)
    app.register_blueprint(auth_bp)
    app.register_blueprint(api_auth_bp)
    app.register_blueprint(users_bp)
