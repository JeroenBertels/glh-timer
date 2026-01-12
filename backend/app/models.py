from __future__ import annotations

from datetime import datetime
from sqlalchemy import String, Integer, Date, DateTime, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False, default="organizer")  # admin | organizer
    race_id: Mapped[str | None] = mapped_column(String, nullable=True)  # for organizers; admin has None
    is_active: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class Race(Base):
    __tablename__ = "races"
    race_id: Mapped[str] = mapped_column(String, primary_key=True)
    race_date: Mapped[datetime] = mapped_column(Date, nullable=False)
    race_timezone: Mapped[str] = mapped_column(String, nullable=False, default="Europe/Brussels")

    parts: Mapped[list["RacePart"]] = relationship(back_populates="race", cascade="all, delete-orphan")
    participants: Mapped[list["Participant"]] = relationship(back_populates="race", cascade="all, delete-orphan")

class RacePart(Base):
    __tablename__ = "race_parts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    race_part_id: Mapped[str] = mapped_column(String, nullable=False)
    race_id: Mapped[str] = mapped_column(ForeignKey("races.race_id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    # duration | end_time | overall
    time_event_type: Mapped[str] = mapped_column(String, nullable=False)

    race: Mapped["Race"] = relationship(back_populates="parts")
    timing_events: Mapped[list["TimingEvent"]] = relationship(back_populates="race_part", cascade="all, delete-orphan")
    start_times: Mapped[list["RacePartStartTime"]] = relationship(back_populates="race_part", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("race_id", "race_part_id", name="uq_race_part"),
        Index("ix_race_parts_race", "race_id"),
    )

class Participant(Base):
    __tablename__ = "participants"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    participant_id: Mapped[str] = mapped_column(String, nullable=False)  # bib
    race_id: Mapped[str] = mapped_column(ForeignKey("races.race_id", ondelete="CASCADE"), nullable=False)

    firstname: Mapped[str] = mapped_column(String, nullable=False)
    lastname: Mapped[str] = mapped_column(String, nullable=False)
    sex: Mapped[str] = mapped_column(String, nullable=True, default="")
    group_name: Mapped[str] = mapped_column(String, nullable=True, default="")
    club_name: Mapped[str] = mapped_column(String, nullable=True, default="")

    race: Mapped["Race"] = relationship(back_populates="participants")
    timing_events: Mapped[list["TimingEvent"]] = relationship(back_populates="participant")

    __table_args__ = (
        UniqueConstraint("race_id", "participant_id", name="uq_participant_per_race"),
        Index("ix_participants_race", "race_id"),
    )

class TimingEvent(Base):
    __tablename__ = "timing_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    race_id: Mapped[str] = mapped_column(String, nullable=False)
    race_part_id: Mapped[str] = mapped_column(String, nullable=False)
    participant_id: Mapped[str] = mapped_column(String, nullable=False)

    # For duration events (store seconds)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # For end-time events
    end_time_utc: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    client_timestamp_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at_utc: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    race_part_fk: Mapped[int] = mapped_column(ForeignKey("race_parts.id", ondelete="CASCADE"), nullable=False)
    race_part: Mapped["RacePart"] = relationship(back_populates="timing_events")

    participant_fk: Mapped[int | None] = mapped_column(ForeignKey("participants.id", ondelete="SET NULL"), nullable=True)
    participant: Mapped["Participant"] = relationship(back_populates="timing_events")

    Index("ix_timing_race_part", "race_id", "race_part_id")

class RacePartStartTime(Base):
    __tablename__ = "race_part_start_times"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    race_id: Mapped[str] = mapped_column(String, nullable=False)
    race_part_id: Mapped[str] = mapped_column(String, nullable=False)
    group_name: Mapped[str] = mapped_column(String, nullable=False, default="DEFAULT")
    # stored as HH:MM:SS
    start_time_hms: Mapped[str] = mapped_column(String, nullable=False)

    race_part_fk: Mapped[int] = mapped_column(ForeignKey("race_parts.id", ondelete="CASCADE"), nullable=False)
    race_part: Mapped["RacePart"] = relationship(back_populates="start_times")

    __table_args__ = (
        UniqueConstraint("race_id", "race_part_id", "group_name", name="uq_start_time_group"),
        Index("ix_start_times_race_part", "race_id", "race_part_id"),
    )
