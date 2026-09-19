"""Contract acoustic-observation 1.0.0, generated from odcs/acoustic-observation.odcs.yaml; do not edit."""

from typing import Any, ClassVar

from pydantic import Field

from ss_contracts.base import ContractModel, ContractTimestamp


class AcousticObservation(ContractModel):
    """One analysed audio chunk from a camera's live stream: level, silence, classified acoustic
    events, and a speech transcript. Produced by SoundAnalyzer for each chunk.
    """

    CONTRACT_ID: ClassVar[str] = "acoustic-observation"
    CONTRACT_VERSION: ClassVar[str] = "1.0.0"
    SS_BINDING: ClassVar[dict[str, str]] = {
        "modality": "acoustic",
        "mqttTopic": "ss/v1/site/{site_id}/camera/{camera}/acoustic",
        "timeBase": "utc",
    }

    camera: str = Field(
        description="Camera whose audio stream was analysed.",
        min_length=1,
    )
    recorded_at: ContractTimestamp = Field(
        description="Time the chunk was analysed.",
        json_schema_extra={
            "x-ss-binding": {
                "timeBase": "utc",
            },
        },
    )
    chunk_duration_sec: float = Field(
        description="Chunk length.",
        gt=0,
        json_schema_extra={
            "x-ss-binding": {
                "unit": "s",
            },
        },
    )
    speech_transcript: str | None = Field(
        default=None,
        description="Speech recognized in the chunk; unset when none.",
    )
    acoustic_events: list[dict[str, Any]] = Field(
        description="Classified acoustic events, each an object with an 'event' label and an 'energy_ratio' in 0-1; empty when silent.",
    )
    rms_db: float = Field(
        description="RMS level of the chunk in dB full scale.",
        json_schema_extra={
            "x-ss-binding": {
                "unit": "dB",
            },
        },
    )
    silence: bool = Field(
        description="The chunk is below the silence threshold.",
    )
