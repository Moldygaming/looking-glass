import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    entra_oid: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(320), index=True)
    display_name: Mapped[str] = mapped_column(String(256))
    roles: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    entra_group_ids: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    status: Mapped[str] = mapped_column(String(16), default="active", server_default="active")
    notes: Mapped[str] = mapped_column(Text, default="", server_default="")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    privilege_grants: Mapped[list["UserPrivilege"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    role_links: Mapped[list["UserRole"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class AccessGroup(Base):
    __tablename__ = "access_groups"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    members: Mapped[list["AccessGroupMember"]] = relationship(
        back_populates="group", cascade="all, delete-orphan"
    )
    scopes: Mapped[list["AccessGroupScope"]] = relationship(
        back_populates="group", cascade="all, delete-orphan"
    )
    privilege_grants: Mapped[list["GroupPrivilege"]] = relationship(
        back_populates="group", cascade="all, delete-orphan"
    )
    role_links: Mapped[list["GroupRole"]] = relationship(
        back_populates="group", cascade="all, delete-orphan"
    )


class AccessGroupMember(Base):
    __tablename__ = "access_group_members"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("access_groups.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    entra_oid: Mapped[str | None] = mapped_column(String(64))
    entra_group_id: Mapped[str | None] = mapped_column(String(64))
    email: Mapped[str | None] = mapped_column(String(320))

    group: Mapped[AccessGroup] = relationship(back_populates="members")


class AccessGroupScope(Base):
    __tablename__ = "access_group_scopes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("access_groups.id", ondelete="CASCADE")
    )
    tag_key: Mapped[str] = mapped_column(String(128))
    tag_value: Mapped[str] = mapped_column(String(256))
    provider: Mapped[str | None] = mapped_column(String(16))
    connection_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("connections.id", ondelete="SET NULL")
    )

    group: Mapped[AccessGroup] = relationship(back_populates="scopes")


class GroupPrivilege(Base):
    __tablename__ = "group_privileges"
    __table_args__ = (UniqueConstraint("group_id", "privilege_key", name="uq_group_privilege"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("access_groups.id", ondelete="CASCADE"), index=True
    )
    privilege_key: Mapped[str] = mapped_column(String(64), index=True)

    group: Mapped[AccessGroup] = relationship(back_populates="privilege_grants")


class UserPrivilege(Base):
    __tablename__ = "user_privileges"
    __table_args__ = (UniqueConstraint("user_id", "privilege_key", name="uq_user_privilege"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    privilege_key: Mapped[str] = mapped_column(String(64), index=True)

    user: Mapped[User] = relationship(back_populates="privilege_grants")


class AccessRole(Base):
    __tablename__ = "access_roles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    privilege_grants: Mapped[list["RolePrivilege"]] = relationship(
        back_populates="role", cascade="all, delete-orphan"
    )
    group_links: Mapped[list["GroupRole"]] = relationship(
        back_populates="role", cascade="all, delete-orphan"
    )
    user_links: Mapped[list["UserRole"]] = relationship(
        back_populates="role", cascade="all, delete-orphan"
    )


class RolePrivilege(Base):
    __tablename__ = "role_privileges"
    __table_args__ = (UniqueConstraint("role_id", "privilege_key", name="uq_role_privilege"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("access_roles.id", ondelete="CASCADE"), index=True
    )
    privilege_key: Mapped[str] = mapped_column(String(64), index=True)

    role: Mapped[AccessRole] = relationship(back_populates="privilege_grants")


class GroupRole(Base):
    __tablename__ = "group_roles"
    __table_args__ = (UniqueConstraint("group_id", "role_id", name="uq_group_role"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("access_groups.id", ondelete="CASCADE"), index=True
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("access_roles.id", ondelete="CASCADE"), index=True
    )

    group: Mapped[AccessGroup] = relationship(back_populates="role_links")
    role: Mapped[AccessRole] = relationship(back_populates="group_links")


class UserRole(Base):
    __tablename__ = "user_roles"
    __table_args__ = (UniqueConstraint("user_id", "role_id", name="uq_user_role"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("access_roles.id", ondelete="CASCADE"), index=True
    )

    user: Mapped[User] = relationship(back_populates="role_links")
    role: Mapped[AccessRole] = relationship(back_populates="user_links")


class Connection(Base):
    __tablename__ = "connections"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(128))
    provider: Mapped[str] = mapped_column(String(16), index=True)
    status: Mapped[str] = mapped_column(String(24), default="pending")
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    secrets: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    secret_ref: Mapped[str | None] = mapped_column(String(512))
    last_ingest_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CostLineItem(Base):
    __tablename__ = "cost_line_items"
    __table_args__ = (
        Index("ix_cost_date", "usage_date"),
        Index("ix_cost_provider", "provider"),
        Index("ix_cost_account", "account_id"),
        Index("ix_cost_tags", "tags", postgresql_using="gin"),
        Index("ix_cost_connection_date", "connection_id", "usage_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    usage_date: Mapped[date] = mapped_column(Date, nullable=False)
    connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("connections.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(String(16))
    account_id: Mapped[str] = mapped_column(String(256))
    account_name: Mapped[str] = mapped_column(String(256))
    resource_group: Mapped[str] = mapped_column(String(256), default="")
    org_id: Mapped[str] = mapped_column(String(256), default="")
    org_name: Mapped[str] = mapped_column(String(256), default="")
    resource_id: Mapped[str] = mapped_column(String(1024))
    resource_name: Mapped[str] = mapped_column(String(256))
    resource_type: Mapped[str] = mapped_column(String(128))
    service: Mapped[str] = mapped_column(String(128))
    category: Mapped[str] = mapped_column(String(64))
    meter: Mapped[str] = mapped_column(String(256))
    region: Mapped[str] = mapped_column(String(64))
    tags: Mapped[dict[str, str]] = mapped_column(JSONB, default=dict)
    cost: Mapped[float] = mapped_column(Float)
    amortized_cost: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(8), default="GBP")
    usage_quantity: Mapped[float] = mapped_column(Float, default=0)
    usage_unit: Mapped[str] = mapped_column(String(64), default="")


class Dashboard(Base):
    __tablename__ = "dashboards"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(Text, default="")
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    visibility: Mapped[str] = mapped_column(String(16), default="private")
    shared_group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("access_groups.id", ondelete="SET NULL")
    )
    widgets: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Recommendation(Base):
    __tablename__ = "recommendations"
    __table_args__ = (
        UniqueConstraint(
            "connection_id",
            "resource_id",
            "category",
            name="uq_recommendation_resource_category",
        ),
        Index("ix_rec_tags", "tags", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("connections.id", ondelete="CASCADE")
    )
    provider: Mapped[str] = mapped_column(String(16))
    account_id: Mapped[str] = mapped_column(String(256))
    resource_id: Mapped[str] = mapped_column(String(1024))
    resource_name: Mapped[str] = mapped_column(String(256))
    category: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(256))
    description: Mapped[str] = mapped_column(Text)
    monthly_savings: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(8), default="GBP")
    status: Mapped[str] = mapped_column(String(16), default="open")
    tags: Mapped[dict[str, str]] = mapped_column(JSONB, default=dict)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
