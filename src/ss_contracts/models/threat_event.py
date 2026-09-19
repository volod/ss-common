"""Contract threat-event 1.0.0, generated from odcs/threat-event.odcs.yaml; do not edit."""

from typing import Any, ClassVar

from pydantic import Field

from ss_contracts.base import ContractModel, ContractTimestamp


class ThreatEvent(ContractModel):
    """A detection the realtime threat runtime scores as a possible threat, placed in a sector; the
    payload carries threat_type, score, label, and the source details
    (coop_ingest.camera_event_to_threat).
    """

    CONTRACT_ID: ClassVar[str] = "threat-event"
    CONTRACT_VERSION: ClassVar[str] = "1.0.0"
    SS_BINDING: ClassVar[dict[str, str]] = {
        "mqttTopic": "ss/v1/site/{site_id}/sector/{sector_id}/threat",
        "timeBase": "utc",
    }

    event_kind: str = Field(
        description="Event discriminator, always 'threat'.",
        pattern="^threat$",
    )
    event_time: ContractTimestamp = Field(
        description="Time the observation happened.",
        json_schema_extra={
            "x-ss-binding": {
                "timeBase": "utc",
            },
        },
    )
    ingest_time: ContractTimestamp = Field(
        description="Time the realtime runtime ingested it.",
        json_schema_extra={
            "x-ss-binding": {
                "timeBase": "utc",
            },
        },
    )
    node_id: str = Field(
        description="Reporting node, lowercase (a DevEUI or 'frigate:<camera>').",
        min_length=1,
    )
    sensor_type: str = Field(
        description="Reporting sensor type, lowercase (lorawan, camera, rf).",
        min_length=1,
    )
    sector_id: str = Field(
        description="Threat sector, a 'grid:<lat>:<lon>' cell or 'unknown'.",
        min_length=1,
    )
    payload: dict[str, Any] = Field(
        description="Modality-specific measurements or detection details.",
    )
    freshness_sec: float = Field(
        description="Age of the observation when ingested.",
        ge=0,
        json_schema_extra={
            "x-ss-binding": {
                "unit": "s",
            },
        },
    )
