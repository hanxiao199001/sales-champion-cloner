"""
Supabase database operations.

Tables required in Supabase:
- recordings: id, filename, storage_path, status, created_at, updated_at,
              transcript, analysis, asr_confidence, error_message
- playbook_patterns: id, category, name, frequency, example_quotes, description,
                     source_recording_ids, boss_annotation, created_at, updated_at
"""

from datetime import datetime, timezone
from typing import Optional
from supabase import create_client, Client

from app.config import SUPABASE_URL, SUPABASE_KEY
from app.models import RecordingStatus, PROCESSING_STATUSES

_client: Optional[Client] = None


def get_client() -> Client:
    global _client
    if _client is None:
        _client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _client


def create_recording(filename: str, storage_path: str) -> dict:
    client = get_client()
    now = datetime.now(timezone.utc).isoformat()
    data = {
        "filename": filename,
        "storage_path": storage_path,
        "status": RecordingStatus.UPLOADED.value,
        "created_at": now,
        "updated_at": now,
    }
    result = client.table("recordings").insert(data).execute()
    return result.data[0]


def update_recording(recording_id: str, **kwargs) -> dict:
    client = get_client()
    kwargs["updated_at"] = datetime.now(timezone.utc).isoformat()
    result = client.table("recordings").update(kwargs).eq("id", recording_id).execute()
    return result.data[0]


def get_recording(recording_id: str) -> Optional[dict]:
    client = get_client()
    result = client.table("recordings").select("*").eq("id", recording_id).execute()
    return result.data[0] if result.data else None


def list_recordings() -> list[dict]:
    client = get_client()
    result = (
        client.table("recordings")
        .select("*")
        .order("created_at", desc=True)
        .execute()
    )
    return result.data


def get_completed_recordings() -> list[dict]:
    client = get_client()
    result = (
        client.table("recordings")
        .select("*")
        .eq("status", RecordingStatus.DONE.value)
        .order("created_at", desc=True)
        .execute()
    )
    return result.data


def get_stale_processing_recordings(timeout_minutes: int) -> list[dict]:
    """Find recordings stuck in processing state beyond the timeout."""
    client = get_client()
    cutoff = datetime.now(timezone.utc)
    results = []
    for status in PROCESSING_STATUSES:
        result = (
            client.table("recordings")
            .select("*")
            .eq("status", status.value)
            .execute()
        )
        for rec in result.data:
            updated = datetime.fromisoformat(rec["updated_at"].replace("Z", "+00:00"))
            elapsed = (cutoff - updated).total_seconds() / 60
            if elapsed > timeout_minutes:
                results.append(rec)
    return results


def get_playbook_patterns() -> list[dict]:
    client = get_client()
    result = (
        client.table("playbook_patterns")
        .select("*")
        .order("frequency", desc=True)
        .execute()
    )
    return result.data


def upsert_playbook_pattern(pattern: dict) -> dict:
    client = get_client()
    pattern["updated_at"] = datetime.now(timezone.utc).isoformat()
    if "created_at" not in pattern:
        pattern["created_at"] = pattern["updated_at"]
    result = (
        client.table("playbook_patterns")
        .upsert(pattern, on_conflict="category,name")
        .execute()
    )
    return result.data[0]
