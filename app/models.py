from __future__ import annotations

from datetime import date, datetime
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Race(Base):
    __tablename__ = "races"

    race_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    race_date: Mapped[date] = mapped_column(Date)
    race_timezone: Mapped[str] = mapped_column(String(100))

    race_parts: Mapped[list["RacePart"]] = relationship(
        "RacePart", back_populates="race", cascade="all, delete-orphan"
    )
    participants: Mapped[list["Participant"]] = relationship(
        "Participant", back_populates="race", cascade="all, delete-orphan"
    )
    organisers: Mapped[list["OrganiserRace"]] = relationship(
        "OrganiserRace", back_populates="race", cascade="all, delete-orphan"
    )


class RacePart(Base):
    __tablename__ = "race_parts"
    __table_args__ = (UniqueConstraint("race_id", "race_part_id", name="uq_race_part"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    race_id: Mapped[str] = mapped_column(ForeignKey("races.race_id"))
    race_part_id: Mapped[str] = mapped_column(String(100))
    race_order: Mapped[int] = mapped_column(Integer, default=0)
    is_overall: Mapped[bool] = mapped_column(Boolean, default=False)

    race: Mapped[Race] = relationship("Race", back_populates="race_parts")


class Participant(Base):
    __tablename__ = "participants"
    __table_args__ = (UniqueConstraint("race_id", "participant_id", name="uq_participant"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    race_id: Mapped[str] = mapped_column(ForeignKey("races.race_id"))
    participant_id: Mapped[int] = mapped_column(Integer)
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    group: Mapped[str] = mapped_column(String(50))
    club: Mapped[str] = mapped_column(String(100), default="")
    sex: Mapped[str] = mapped_column(String(10), default="")

    race: Mapped[Race] = relationship("Race", back_populates="participants")


class Organiser(Base):
    __tablename__ = "organisers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(150), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))

    races: Mapped[list["OrganiserRace"]] = relationship(
        "OrganiserRace", back_populates="organiser", cascade="all, delete-orphan"
    )


class OrganiserRace(Base):
    __tablename__ = "organiser_races"
    __table_args__ = (UniqueConstraint("organiser_id", "race_id", name="uq_org_race"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organiser_id: Mapped[int] = mapped_column(ForeignKey("organisers.id"))
    race_id: Mapped[str] = mapped_column(ForeignKey("races.race_id"))

    organiser: Mapped[Organiser] = relationship("Organiser", back_populates="races")
    race: Mapped[Race] = relationship("Race", back_populates="organisers")


class TimingEvent(Base):
    __tablename__ = "timing_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    race_id: Mapped[str] = mapped_column(ForeignKey("races.race_id"))
    race_part_id: Mapped[str] = mapped_column(String(100))
    participant_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    group: Mapped[str | None] = mapped_column(String(50), nullable=True)
    client_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    server_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

