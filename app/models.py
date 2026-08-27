"""
Database models and types for the Sales Champion Cloner.

Recording state machine:
    uploaded → transcribing → analyzing → done
                   |              |
                   v              v
                 failed        failed
                   |              |
                   └──── retry ───┘

Playbook update strategy: incremental (new recordings add patterns, never rewrite existing).
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class RecordingStatus(str, Enum):
    UPLOADED = "uploaded"
    TRANSCRIBING = "transcribing"
    ANALYZING = "analyzing"
    DONE = "done"
    FAILED = "failed"


RETRYABLE_STATUSES = {RecordingStatus.FAILED}
PROCESSING_STATUSES = {RecordingStatus.TRANSCRIBING, RecordingStatus.ANALYZING}


@dataclass
class TranscriptSegment:
    speaker: str  # "boss" or "client"
    text: str
    start_time: float
    end_time: float


@dataclass
class CallAnalysis:
    call_phases: list[dict]
    objections_handled: list[dict]
    closing_techniques: list[dict]
    patterns: list[dict]
    key_quotes: list[dict]
    summary: str


@dataclass
class PlaybookPattern:
    category: str  # "opening", "objection_handling", "closing", "discovery"
    name: str
    frequency: int
    example_quotes: list[str]
    description: str
    source_recording_ids: list[str]
    boss_annotation: Optional[str] = None


@dataclass
class Recording:
    id: str
    filename: str
    storage_path: str
    status: RecordingStatus
    created_at: datetime
    updated_at: datetime
    transcript: Optional[list[dict]] = None
    analysis: Optional[dict] = None
    asr_confidence: Optional[float] = None
    error_message: Optional[str] = None
