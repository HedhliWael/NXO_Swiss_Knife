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
    # Soft delete: deleted projects land in the Trash (restorable) instead
    # of being removed from the database. The attached firewalls and their
    # objects follow into the trash (see soft_delete / restore).
    is_deleted = db.Column(db.Boolean, nullable=False, default=False, index=True)
    deleted_at = db.Column(db.DateTime(timezone=True), nullable=True)
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
    trash_record = db.relationship(
        "Trash",
        uselist=False,
        back_populates="project",
        cascade="all, delete-orphan",
    )

    @property
    def active_firewalls(self):
        """Attached firewalls that are not in the trash."""
        return [fw for fw in self.firewalls if not fw.is_deleted]

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "is_deleted": bool(self.is_deleted),
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def soft_delete(self, user="system", reason=None):
        """Move the project to the trash (its firewalls + objects follow)."""
        now = utcnow()
        self.is_deleted = True
        self.deleted_at = now

        if self.trash_record is None:
            db.session.add(
                Trash(
                    item_type="project",
                    project_id=self.id,
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

        for firewall in self.firewalls:
            if not firewall.is_deleted:
                firewall.soft_delete(user=user, reason=f"Project '{self.name}' deleted")

    def restore(self, user="system"):
        """Restore the project from the trash (its firewalls + objects follow)."""
        self.is_deleted = False
        self.deleted_at = None

        if self.trash_record is not None:
            self.trash_record.restored_at = utcnow()

        for firewall in self.firewalls:
            if firewall.is_deleted:
                firewall.restore(user=user)


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
    # Soft delete: deleted firewalls land in the Trash (restorable) instead
    # of being removed from the database. Their objects follow into the
    # trash individually (see soft_delete / restore).
    is_deleted = db.Column(db.Boolean, nullable=False, default=False, index=True)
    deleted_at = db.Column(db.DateTime(timezone=True), nullable=True)
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
    trash_record = db.relationship(
        "Trash",
        uselist=False,
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
            "is_deleted": bool(self.is_deleted),
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
            "last_sync_at": self.last_sync_at.isoformat() if self.last_sync_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def soft_delete(self, user="system", reason=None):
        """Move the firewall to the trash (its objects follow individually)."""
        now = utcnow()
        self.is_deleted = True
        self.deleted_at = now

        if self.trash_record is None:
            db.session.add(
                Trash(
                    item_type="firewall",
                    firewall_id=self.id,
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

        # Every object goes to the trash individually: it shows up in the
        # trash's object section and can be restored on its own.
        for obj in self.config_objects:
            if not obj.is_deleted:
                obj.soft_delete(user=user, reason=f"Firewall '{self.name}' deleted")

    def restore(self, user="system"):
        """Restore the firewall from the trash (its objects follow)."""
        self.is_deleted = False
        self.deleted_at = None

        if self.trash_record is not None:
            self.trash_record.restored_at = utcnow()

        for obj in self.config_objects:
            if obj.is_deleted:
                obj.restore(user=user)

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

    # The import run that created this object (import history): a new import
    # replaces the previous one — the previous import's objects are deleted
    # before the new configuration is applied. NULL for manually created
    # objects and for objects imported before the history existed.
    import_id = db.Column(
        db.Integer,
        db.ForeignKey("import_records.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

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
    import_record = db.relationship("ImportRecord")
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
            "import_id": self.import_id,
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
    """A trash entry for a soft-deleted entity.

    ``item_type`` marks the kind of deleted entity ("object", "project",
    "firewall"); exactly one of ``config_object_id`` / ``project_id`` /
    ``firewall_id`` is set, matching the item type. Restored entries keep
    ``restored_at`` set and disappear from the trash lists.
    """

    __tablename__ = "trash"

    id = db.Column(db.Integer, primary_key=True)
    # "object" | "project" | "firewall"
    item_type = db.Column(db.String(16), nullable=False, default="object")
    config_object_id = db.Column(
        db.Integer,
        db.ForeignKey("config_objects.id", ondelete="CASCADE"),
        unique=True,
        nullable=True,
    )
    project_id = db.Column(
        db.Integer,
        db.ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    firewall_id = db.Column(
        db.Integer,
        db.ForeignKey("firewalls.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    deleted_by = db.Column(db.String(120), nullable=True)
    deleted_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    reason = db.Column(db.Text, nullable=True)
    restored_at = db.Column(db.DateTime(timezone=True), nullable=True)

    config_object = db.relationship("ConfigObject", back_populates="trash_record")
    project = db.relationship("Project", back_populates="trash_record")
    firewall = db.relationship("Firewall", back_populates="trash_record")


class ImportRecord(db.Model):
    """One import run against a firewall (the import history).

    Every configuration import (file or URL) writes one record; the objects
    created by that import carry ``ConfigObject.import_id`` back to it. A new
    import replaces the previous one: the previous import's objects are removed
    before the new configuration is applied. The record is kept when the
    firewall is deleted (history, not a live reference).
    """

    __tablename__ = "import_records"

    id = db.Column(db.Integer, primary_key=True)
    # SET NULL: the record stays when the firewall is deleted.
    firewall_id = db.Column(
        db.Integer,
        db.ForeignKey("firewalls.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # "file" = uploaded file, "url" = downloaded from a remote URL.
    source_type = db.Column(db.String(16), nullable=False, default="file")
    source_name = db.Column(db.String(512), nullable=True)
    object_count = db.Column(db.Integer, nullable=False, default=0)
    counts = db.Column(db.JSON, nullable=False, default=lambda: {})
    warnings = db.Column(db.JSON, nullable=False, default=lambda: [])
    user = db.Column(db.String(120), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    firewall = db.relationship("Firewall")

    def to_dict(self):
        return {
            "id": self.id,
            "firewall_id": self.firewall_id,
            "firewall_name": self.firewall.name if self.firewall else None,
            "source_type": self.source_type,
            "source_name": self.source_name,
            "object_count": self.object_count,
            "counts": self.counts or {},
            "user": self.user,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class ExportRecord(db.Model):
    """A configuration file generated (``file``) or pushed (``push``).

    The configuration text is kept on disk (``instance/exports/``) so the
    project page can list the previous generated or pushed files and offer
    them for download.
    """

    __tablename__ = "export_records"

    id = db.Column(db.Integer, primary_key=True)
    # SET NULL: the record stays when the project or the destination
    # firewall is deleted (it is history, not a live reference).
    project_id = db.Column(
        db.Integer,
        db.ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    firewall_id = db.Column(
        db.Integer,
        db.ForeignKey("firewalls.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # "file" = generated download, "push" = pushed to the firewall (the
    # pushed text is kept on disk as well, so it stays downloadable).
    method = db.Column(db.String(16), nullable=False)
    destination_name = db.Column(db.String(120), nullable=True)
    filename = db.Column(db.String(255), nullable=False)
    # Stored file name inside instance/exports/ (record id + filename).
    file_path = db.Column(db.String(512), nullable=False, default="")
    object_count = db.Column(db.Integer, nullable=False, default=0)
    counts = db.Column(db.JSON, nullable=False, default=lambda: {})
    size_bytes = db.Column(db.Integer, nullable=False, default=0)
    user = db.Column(db.String(120), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    project = db.relationship("Project")
    firewall = db.relationship("Firewall")

    def to_dict(self):
        return {
            "id": self.id,
            "project_id": self.project_id,
            "firewall_id": self.firewall_id,
            "method": self.method,
            "destination_name": self.destination_name,
            "filename": self.filename,
            "file_path": self.file_path,
            "object_count": self.object_count,
            "counts": self.counts or {},
            "size_bytes": self.size_bytes,
            "user": self.user,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


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
