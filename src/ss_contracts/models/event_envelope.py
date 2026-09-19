"""Contract event-envelope 1.0.0, generated from odcs/event-envelope.odcs.yaml; do not edit."""

from typing import Any, ClassVar

from pydantic import Field

from ss_contracts.base import ContractModel, ContractTimestamp


class EventEnvelope(ContractModel):
    """A sensor event from any modality submitted to the site event ingest: when and where it
    happened, which sensor saw it, how confident it is, and an optional artifact. The modality
    is the last topic level (and the path parameter of POST /api/v1/events).
    """

    CONTRACT_ID: ClassVar[str] = "event-envelope"
    CONTRACT_VERSION: ClassVar[str] = "1.0.0"
    SS_BINDING: ClassVar[dict[str, str]] = {
        "mqttTopic": "ss/v1/site/{site_id}/zone/{zone_id}/event/{modality}",
        "timeBase": "utc",
    }

    ts: ContractTimestamp = Field(
        description="Event time.",
        json_schema_extra={
            "x-ss-binding": {
                "timeBase": "utc",
            },
        },
    )
    zone_id: str = Field(
        description="Site zone the event belongs to.",
        min_length=1,
    )
    sensor_id: str = Field(
        description="Reporting sensor id.",
        min_length=1,
    )
    confidence: float = Field(
        description="Detection confidence.",
        ge=0,
        le=1,
    )
    payload: dict[str, Any] | None = Field(
        default=None,
        description="Modality-specific details; empty when unset.",
    )
    artifact_uri: str | None = Field(
        default=None,
        description="Path of a stored artifact (clip, image, audio) inside the allowed index paths.",
    )
