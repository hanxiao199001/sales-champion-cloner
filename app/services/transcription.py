"""
ASR transcription service.

Uses Alibaba Cloud Speech API (or compatible hosted ASR) for:
1. Speech-to-text transcription (Chinese Mandarin)
2. Speaker diarization (boss vs client)

Quality gate: if ASR confidence < threshold, reject the recording.
"""

import httpx

from app.config import (
    ASR_CONFIDENCE_THRESHOLD,
)


class TranscriptionError(Exception):
    pass


class LowConfidenceError(TranscriptionError):
    """ASR confidence below threshold."""

    def __init__(self, confidence: float, threshold: int):
        self.confidence = confidence
        self.threshold = threshold
        super().__init__(
            f"ASR confidence {confidence:.1f}% is below threshold {threshold}%. "
            "Recording quality may be insufficient."
        )


async def transcribe_audio(audio_url: str) -> dict:
    """
    Transcribe audio file and return structured transcript with speaker diarization.

    Returns:
        {
            "confidence": float (0-100),
            "segments": [
                {"speaker": "speaker_1"|"speaker_2", "text": str, "start": float, "end": float},
                ...
            ]
        }

    Raises:
        LowConfidenceError: if confidence < ASR_CONFIDENCE_THRESHOLD
        TranscriptionError: on API failure
    """
    # TODO: Replace with actual Alibaba Cloud Speech API call.
    # This is a placeholder showing the expected interface.
    # Actual implementation requires:
    #   1. Submit transcription task via Alibaba Cloud API
    #   2. Poll for completion
    #   3. Parse results with speaker labels
    #
    # API docs: https://help.aliyun.com/document_detail/China Speech API
    #
    # For development/testing, you can use:
    #   - Manual transcription via 通义听悟 / 飞书妙记
    #   - Local FunASR for offline testing

    try:
        result = await _call_asr_api(audio_url)
    except httpx.TimeoutException:
        raise TranscriptionError("ASR service timed out. Please retry.")
    except httpx.HTTPError as e:
        raise TranscriptionError(f"ASR service error: {e}")

    confidence = result.get("confidence", 0)
    if confidence < ASR_CONFIDENCE_THRESHOLD:
        raise LowConfidenceError(confidence, ASR_CONFIDENCE_THRESHOLD)

    return result


async def _call_asr_api(audio_url: str) -> dict:
    """
    Call the hosted ASR API.

    TODO: Implement actual API call. This placeholder raises NotImplementedError
    to make it clear this needs real integration.
    """
    raise NotImplementedError(
        "ASR API integration not yet implemented. "
        "Configure ALIBABA_ACCESS_KEY_ID and ALIBABA_ACCESS_KEY_SECRET, "
        "then implement the actual API call here."
    )


def label_speakers(segments: list[dict]) -> list[dict]:
    """
    Label speakers as 'boss' or 'client' based on diarization output.

    Heuristic: the speaker who talks more is likely the boss (sales person).
    This can be refined later with the boss's voice profile.
    """
    speaker_durations: dict[str, float] = {}
    for seg in segments:
        speaker = seg["speaker"]
        duration = seg["end"] - seg["start"]
        speaker_durations[speaker] = speaker_durations.get(speaker, 0) + duration

    if not speaker_durations:
        return segments

    boss_speaker = max(speaker_durations, key=speaker_durations.get)

    labeled = []
    for seg in segments:
        labeled.append(
            {
                **seg,
                "speaker": "boss" if seg["speaker"] == boss_speaker else "client",
            }
        )
    return labeled
