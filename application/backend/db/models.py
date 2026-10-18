import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    public_ref: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    users: Mapped[list["AppUser"]] = relationship(back_populates="organization")
    dashboard_accounts: Mapped[list["DashboardAccount"]] = relationship(back_populates="organization")


class AppUser(Base):
    __tablename__ = "app_users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    public_ref: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    alias: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    organization: Mapped["Organization"] = relationship(back_populates="users")
    oauth_connections: Mapped[list["OAuthConnection"]] = relationship(back_populates="user")
    dashboard_account: Mapped["DashboardAccount | None"] = relationship(back_populates="user", uselist=False)


class DashboardAccount(Base):
    __tablename__ = "dashboard_accounts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    login: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    role: Mapped[str] = mapped_column(String(32))
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_users.id", ondelete="CASCADE"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    organization: Mapped["Organization"] = relationship(back_populates="dashboard_accounts")
    user: Mapped["AppUser | None"] = relationship(back_populates="dashboard_account")


class OAuthConnection(Base):
    __tablename__ = "oauth_connections"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_users.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(32), default="google")
    encrypted_refresh_token: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["AppUser"] = relationship(back_populates="oauth_connections")


class SalesReferential(Base):
    __tablename__ = "sales_referentials"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(128))
    version: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict] = mapped_column(JSONB)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MeetingClassification(Base):
    __tablename__ = "meeting_classifications"
    __table_args__ = (UniqueConstraint("google_event_id", "user_id", name="uq_event_user"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    google_event_id: Mapped[str] = mapped_column(String(256))
    calendar_id: Mapped[str] = mapped_column(String(256), default="primary")
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_users.id", ondelete="CASCADE"))
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    referential_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sales_referentials.id"), nullable=True)
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL", name="fk_meeting_classifications_account"),
        nullable=True,
        index=True,
    )
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("opportunities.id", ondelete="SET NULL", name="fk_meeting_classifications_opportunity"),
        nullable=True,
    )
    title: Mapped[str] = mapped_column(String(512))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    category_id: Mapped[str] = mapped_column(String(64))
    category_label: Mapped[str] = mapped_column(String(128))
    confidence: Mapped[float] = mapped_column(Float)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_event: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    classified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Account(Base):
    """Compte cible (prospect à conquérir) ou client existant (à développer)."""

    __tablename__ = "accounts"
    __table_args__ = (Index("ix_accounts_org_owner", "organization_id", "owner_user_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("app_users.id", ondelete="SET NULL"), nullable=True
    )
    public_ref: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(256))
    industry: Mapped[str | None] = mapped_column(String(64), nullable=True)
    segment: Mapped[str] = mapped_column(String(32), default="mid_market")
    tier: Mapped[str] = mapped_column(String(1), default="B")
    kind: Mapped[str] = mapped_column(String(16), default="prospect")
    status: Mapped[str] = mapped_column(String(16), default="active")
    source: Mapped[str] = mapped_column(String(32), default="outbound")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    first_touch_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Activity(Base):
    """Action de prospection unitaire (appel, email, message LinkedIn) et son résultat."""

    __tablename__ = "activities"
    __table_args__ = (
        Index("ix_activities_org_occurred", "organization_id", "occurred_at"),
        Index("ix_activities_user_occurred", "user_id", "occurred_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_users.id", ondelete="CASCADE"))
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    type: Mapped[str] = mapped_column(String(16))
    outcome: Mapped[str] = mapped_column(String(24))
    is_hunting: Mapped[bool] = mapped_column(Boolean, default=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(String(16), default="crm")


class Opportunity(Base):
    __tablename__ = "opportunities"
    __table_args__ = (Index("ix_opportunities_org_user_stage", "organization_id", "user_id", "stage"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_users.id", ondelete="CASCADE"))
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    public_ref: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(256))
    stage: Mapped[str] = mapped_column(String(16))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    source: Mapped[str] = mapped_column(String(32), default="outbound")
    is_new_logo: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expected_close_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_stage_change_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_step: Mapped[str | None] = mapped_column(String(256), nullable=True)
    next_step_due: Mapped[date | None] = mapped_column(Date, nullable=True)
    lost_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)


class OpportunityStageEvent(Base):
    """Historique des changements d'étape : base des taux de conversion et des cycles de vente."""

    __tablename__ = "opportunity_stage_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    opportunity_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("opportunities.id", ondelete="CASCADE"), index=True)
    from_stage: Mapped[str | None] = mapped_column(String(16), nullable=True)
    to_stage: Mapped[str] = mapped_column(String(16))
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SalesTarget(Base):
    """Objectif par indicateur : défaut équipe (user_id NULL) ou surcharge individuelle (ramp-up, quota)."""

    __tablename__ = "sales_targets"
    __table_args__ = (
        UniqueConstraint("organization_id", "user_id", "metric", "period", "valid_from", name="uq_target"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_users.id", ondelete="CASCADE"), nullable=True)
    metric: Mapped[str] = mapped_column(String(48))
    period: Mapped[str] = mapped_column(String(16))
    target_value: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    valid_from: Mapped[date] = mapped_column(Date)


class Challenge(Base):
    __tablename__ = "challenges"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    metric: Mapped[str] = mapped_column(String(48))
    scope: Mapped[str] = mapped_column(String(16), default="individual")
    target_value: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    starts_on: Mapped[date] = mapped_column(Date)
    ends_on: Mapped[date] = mapped_column(Date)
    reward_points: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CoachingAction(Base):
    """Action de coaching assignée à un commercial (nudge, 1:1, écoute d'appels, reconnaissance)."""

    __tablename__ = "coaching_actions"
    __table_args__ = (Index("ix_coaching_org_status", "organization_id", "status"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_users.id", ondelete="CASCADE"))
    created_by: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(24))
    title: Mapped[str] = mapped_column(String(256))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    related_metric: Mapped[str | None] = mapped_column(String(48), nullable=True)
    due_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
