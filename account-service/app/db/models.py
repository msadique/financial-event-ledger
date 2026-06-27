from datetime import datetime, timezone
from decimal import Decimal
import uuid
from sqlalchemy import DateTime, ForeignKey, Index, JSON, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column
from app.db.session import Base


def utcnow():
    return datetime.now(timezone.utc)


class Account(Base):
    __tablename__ = "accounts"
    account_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    balance: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False, default=Decimal("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class Transaction(Base):
    __tablename__ = "transactions"
    event_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.account_id"), nullable=False)
    type: Mapped[str] = mapped_column(String(6), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    event_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    __table_args__ = (Index("ix_transactions_account_time", "account_id", "event_timestamp", "event_id"),)


class AuditRecord(Base):
    __tablename__ = "audit_records"
    audit_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    trace_id: Mapped[str] = mapped_column(String(128), nullable=False)
    event_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    account_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    details_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
