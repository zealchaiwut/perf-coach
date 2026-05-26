import uuid
from sqlalchemy import Column, String, Numeric, Date, DateTime, ForeignKey, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    name = Column(String(100), nullable=False, unique=True)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))


class WeightEntry(Base):
    __tablename__ = "weight_entries"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    weight_kg = Column(Numeric(5, 2), nullable=False)
    recorded_date = Column(Date, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))

    __table_args__ = (UniqueConstraint("user_id", "recorded_date", name="uq_weight_entries_user_date"),)
