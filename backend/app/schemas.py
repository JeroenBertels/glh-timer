from __future__ import annotations
from pydantic import BaseModel, Field

class RaceCreate(BaseModel):
    race_id: str
    race_date: str  # YYYY-MM-DD
    race_timezone: str

class RacePartCreate(BaseModel):
    race_id: str
    race_part_id: str
    name: str
    time_event_type: str  # duration | end_time

class ParticipantCreate(BaseModel):
    race_id: str
    participant_id: str
    firstname: str
    lastname: str
    sex: str = ""
    group_name: str = ""
    club_name: str = ""

class TimingEventCreate(BaseModel):
    race_id: str
    race_part_id: str
    participant_id: str
    duration: str = ""  # optional; if present => duration event
    client_timestamp_ms: str | None = None

class StartTimeUpsert(BaseModel):
    race_id: str
    race_part_id: str
    group_name: str = Field(default="DEFAULT")
    start_time_hms: str  # HH:MM:SS
