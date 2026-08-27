"""
Background task orchestration.

Handles the async processing pipeline:
  upload → transcribe → analyze → update playbook

Also handles timeout detection for stuck recordings.
"""

import logging

from app import database as db
from app.models import RecordingStatus
from app.config import PROCESSING_TIMEOUT_MINUTES, PLAYBOOK_MIN_RECORDINGS
from app.services.transcription import (
    transcribe_audio,
    label_speakers,
    TranscriptionError,
    LowConfidenceError,
)
from app.services.analysis import (
    analyze_call,
    update_playbook_incremental,
    AnalysisError,
)

logger = logging.getLogger(__name__)


async def process_transcript(recording_id: str, segments: list[dict]):
    """
    Semi-auto mode: transcript already provided, only run Claude analysis.
    Skips ASR entirely.
    """
    try:
        db.update_recording(recording_id, status=RecordingStatus.ANALYZING.value)

        try:
            analysis = await analyze_call(segments)
        except AnalysisError as e:
            db.update_recording(
                recording_id,
                status=RecordingStatus.FAILED.value,
                error_message=str(e),
            )
            logger.error(f"Recording {recording_id}: analysis failed: {e}")
            return

        db.update_recording(
            recording_id,
            status=RecordingStatus.DONE.value,
            analysis=analysis,
        )
        logger.info(f"Recording {recording_id}: transcript analysis complete")

        completed = db.get_completed_recordings()
        if len(completed) >= PLAYBOOK_MIN_RECORDINGS:
            await _update_playbook(analysis, recording_id)

    except Exception as e:
        logger.exception(f"Recording {recording_id}: unexpected error")
        db.update_recording(
            recording_id,
            status=RecordingStatus.FAILED.value,
            error_message=f"Unexpected error: {e}",
        )


async def process_recording(recording_id: str, audio_url: str):
    """
    Full processing pipeline for a single recording.

    State transitions:
        uploaded → transcribing → analyzing → done
                      |               |
                      v               v
                    failed          failed
    """
    try:
        # Step 1: Transcribe
        db.update_recording(recording_id, status=RecordingStatus.TRANSCRIBING.value)

        try:
            transcript_result = await transcribe_audio(audio_url)
        except LowConfidenceError as e:
            db.update_recording(
                recording_id,
                status=RecordingStatus.FAILED.value,
                asr_confidence=e.confidence,
                error_message=str(e),
            )
            logger.warning(f"Recording {recording_id}: low confidence ({e.confidence}%)")
            return
        except TranscriptionError as e:
            db.update_recording(
                recording_id,
                status=RecordingStatus.FAILED.value,
                error_message=str(e),
            )
            logger.error(f"Recording {recording_id}: transcription failed: {e}")
            return

        segments = label_speakers(transcript_result["segments"])
        confidence = transcript_result["confidence"]

        db.update_recording(
            recording_id,
            transcript=segments,
            asr_confidence=confidence,
        )

        # Step 2: Analyze
        db.update_recording(recording_id, status=RecordingStatus.ANALYZING.value)

        try:
            analysis = await analyze_call(segments)
        except AnalysisError as e:
            db.update_recording(
                recording_id,
                status=RecordingStatus.FAILED.value,
                error_message=str(e),
            )
            logger.error(f"Recording {recording_id}: analysis failed: {e}")
            return

        db.update_recording(
            recording_id,
            status=RecordingStatus.DONE.value,
            analysis=analysis,
        )
        logger.info(f"Recording {recording_id}: processing complete")

        # Step 3: Update playbook incrementally (if enough recordings)
        completed = db.get_completed_recordings()
        if len(completed) >= PLAYBOOK_MIN_RECORDINGS:
            await _update_playbook(analysis, recording_id)

    except Exception as e:
        logger.exception(f"Recording {recording_id}: unexpected error")
        db.update_recording(
            recording_id,
            status=RecordingStatus.FAILED.value,
            error_message=f"Unexpected error: {e}",
        )


async def _update_playbook(new_analysis: dict, recording_id: str):
    """Incrementally update the playbook with patterns from a new analysis."""
    try:
        existing_patterns = db.get_playbook_patterns()
        updates = await update_playbook_incremental(existing_patterns, new_analysis)

        for pattern in updates.get("new_patterns", []):
            pattern["source_recording_ids"] = [recording_id]
            db.upsert_playbook_pattern(pattern)

        for update in updates.get("updated_patterns", []):
            for existing in existing_patterns:
                if existing["name"] == update["name"]:
                    existing["frequency"] = existing.get("frequency", 0) + update.get(
                        "frequency_increment", 1
                    )
                    quotes = existing.get("example_quotes", [])
                    quotes.extend(update.get("additional_quotes", []))
                    existing["example_quotes"] = quotes
                    sources = existing.get("source_recording_ids", [])
                    if recording_id not in sources:
                        sources.append(recording_id)
                    existing["source_recording_ids"] = sources
                    db.upsert_playbook_pattern(existing)
                    break

        logger.info(
            f"Playbook updated: {len(updates.get('new_patterns', []))} new, "
            f"{len(updates.get('updated_patterns', []))} updated"
        )
    except Exception as e:
        logger.error(f"Playbook update failed (non-blocking): {e}")


async def check_stale_recordings():
    """
    Timeout detection: mark recordings stuck in processing as failed.
    Should be called periodically (e.g., every minute).
    """
    stale = db.get_stale_processing_recordings(PROCESSING_TIMEOUT_MINUTES)
    for rec in stale:
        logger.warning(
            f"Recording {rec['id']} stuck in {rec['status']} for >"
            f"{PROCESSING_TIMEOUT_MINUTES} minutes. Marking as failed."
        )
        db.update_recording(
            rec["id"],
            status=RecordingStatus.FAILED.value,
            error_message=f"Processing timed out after {PROCESSING_TIMEOUT_MINUTES} minutes. Please retry.",
        )
    return len(stale)
