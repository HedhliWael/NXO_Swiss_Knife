from datetime import datetime, timezone
from enum import Enum

from .extensions import db


class ObjectType(str, Enum):
    ADDRESS = "address"
    ADDRESS_GROUP = "address_group"
    SERVICE = "service"
    SERVICE_GROUP = "service_group"
    RULE = "rule"
    ROUTE = "route"
    ZONE = "zone"
    INTERFACE = "interface"
    IPSEC_TUNNEL = "ipsec_tunnel"


ALLOWED_OBJECT_TYPES = [t.value for t in ObjectType]


def utcnow():
    return datetime.now(timezone.utc)


class Project(db.Model):
    __tablename__ = "projects"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    description = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    firewalls = db.relationship(
        "Firewall",
        back_populates="project",
        cascade="all, delete-orphan",
    )

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class Firewall(db.Model):
    __tablename__ = "firewalls"

    id = db.Column(db.Integer, primary_key=True)
    # Nullable: a firewall can be removed from a project without being
    # deleted (it then shows up on the firewall dashboard as unassigned).
    project_id = db.Column(
        db.Integer,
        db.ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    name = db.Column(db.String(120), nullable=False)
    vendor = db.Column(db.String(32), nullable=False, index=True)
    model = db.Column(db.String(120), nullable=True)
    management_ip = db.Column(db.String(45), nullable=True)
    # "password" = login/password, "token" = API token.
    auth_mode = db.Column(db.String(16), nullable=False, default="password")
    api_username = db.Column(db.String(120), nullable=True)
    # In production, store encrypted credentials or reference a secrets manager.
    api_password = db.Column(db.Text, nullable=True)
    api_token = db.Column(db.Text, nullable=True)
    description = db.Column(db.Text, nullable=True)
    last_sync_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    project = db.relationship("Project", back_populates="firewalls")
    config_objects = db.relationship(
        "ConfigObject",
        back_populates="firewall",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        db.UniqueConstraint("project_id", "name", name="uq_firewalls_project_name"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "project_id": self.project_id,
            "name": self.name,
            "vendor": self.vendor,
            "model": self.model,
            "management_ip": self.management_ip,
            "auth_mode": self.auth_mode or "password",
            "description": self.description,
            "last_sync_at": self.last_sync_at.isoformat() if self.last_sync_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    @property
    def has_config(self):
        """True when at least one active configuration object was imported."""
        return any(not obj.is_deleted for obj in self.config_objects)

    @property
    def objects_count(self):
        """Number of active (non-deleted) configuration objects."""
        return sum(1 for obj in self.config_objects if not obj.is_deleted)

    def set_project(self, project_id):
        """Assign (or unassign) the owning project and keep the project_id of
        all of its configuration objects in sync."""
        self.project_id = project_id
        for obj in self.config_objects:
            obj.project_id = project_id


class ConfigObject(db.Model):
    __tablename__ = "config_objects"

    id = db.Column(db.Integer, primary_key=True)
    # Nullable: objects of an unassigned firewall (imported before the
    # firewall was attached to a project) have no project yet.
    project_id = db.Column(
        db.Integer,
        db.ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    firewall_id = db.Column(
        db.Integer,
        db.ForeignKey("firewalls.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    object_type = db.Column(db.String(32), nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)

    # Vendor-specific normalized data.
    payload = db.Column(db.JSON, nullable=False, default=lambda: {})

    raw_excerpt = db.Column(db.Text, nullable=True)
    fingerprint = db.Column(db.String(64), index=True)

    # Tagged from the object list page ("Include in the export"): the export
    # wizard pre-selects tagged objects per object type.
    export_included = db.Column(db.Boolean, nullable=False, default=False, index=True)

    is_deleted = db.Column(db.Boolean, nullable=False, default=False)
    deleted_at = db.Column(db.DateTime(timezone=True), nullable=True)

    created_by = db.Column(db.String(120), nullable=True)
    updated_by = db.Column(db.String(120), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    firewall = db.relationship("Firewall", back_populates="config_objects")
    history = db.relationship(
        "ModificationHistory",
        back_populates="config_object",
        cascade="all, delete-orphan",
    )
    trash_record = db.relationship(
        "Trash",
        uselist=False,
        back_populates="config_object",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        # Natural identity: one object per firewall/type/name.
        db.UniqueConstraint(
            "firewall_id",
            "object_type",
            "name",
            name="uq_config_objects_firewall_type_name",
        ),
        db.Index("ix_config_objects_firewall_type", "firewall_id", "object_type"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "project_id": self.project_id,
            "firewall_id": self.firewall_id,
            "object_type": self.object_type,
            "name": self.name,
            "description": self.description,
            "payload": self.payload or {},
            "raw_excerpt": self.raw_excerpt,
            "fingerprint": self.fingerprint,
            "export_included": bool(self.export_included),
            "is_deleted": bool(self.is_deleted),
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
            "created_by": self.created_by,
            "updated_by": self.updated_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def soft_delete(self, user="system", reason=None):
        now = utcnow()
        self.is_deleted = True
        self.deleted_at = now
        self.updated_by = user

        if self.trash_record is None:
            db.session.add(
                Trash(
                    config_object_id=self.id,
                    deleted_by=user,
                    deleted_at=now,
                    reason=reason,
                )
            )
        else:
            trash = self.trash_record
            trash.restored_at = None
            trash.deleted_by = user
            trash.deleted_at = now
            trash.reason = reason

    def restore(self, user="system"):
        self.is_deleted = False
        self.deleted_at = None
        self.updated_by = user

        if self.trash_record is not None:
            self.trash_record.restored_at = utcnow()


class ModificationHistory(db.Model):
    __tablename__ = "modification_history"

    id = db.Column(db.Integer, primary_key=True)
    config_object_id = db.Column(
        db.Integer,
        db.ForeignKey("config_objects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id = db.Column(
        db.Integer,
        db.ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
    )
    firewall_id = db.Column(
        db.Integer,
        db.ForeignKey("firewalls.id", ondelete="SET NULL"),
        nullable=True,
    )

    field = db.Column(db.String(120), nullable=False)
    old_value = db.Column(db.JSON, nullable=True)
    new_value = db.Column(db.JSON, nullable=True)
    action = db.Column(db.String(32), nullable=False)
    user = db.Column(db.String(120), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    config_object = db.relationship("ConfigObject", back_populates="history")

    __table_args__ = (
        db.Index(
            "ix_mod_history_object_created",
            "config_object_id",
            "created_at",
        ),
    )


class Trash(db.Model):
    __tablename__ = "trash"

    id = db.Column(db.Integer, primary_key=True)
    config_object_id = db.Column(
        db.Integer,
        db.ForeignKey("config_objects.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    deleted_by = db.Column(db.String(120), nullable=True)
    deleted_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    reason = db.Column(db.Text, nullable=True)
    restored_at = db.Column(db.DateTime(timezone=True), nullable=True)

    config_object = db.relationship("ConfigObject", back_populates="trash_record")


def log_change(config_object, field, old_value, new_value, action, user):
    """
    Write a modification history row.

    Scalar values are wrapped as {"value": ...} so the JSON column remains consistent.
    """

    def _wrap(value):
        if value is None:
            return None
        if isinstance(value, (dict, list)):
            return value
        return {"value": value}

    db.session.add(
        ModificationHistory(
            config_object_id=config_object.id,
            project_id=config_object.project_id,
            firewall_id=config_object.firewall_id,
            field=field,
            old_value=_wrap(old_value),
            new_value=_wrap(new_value),
            action=action,
            user=user,
        )
    )
