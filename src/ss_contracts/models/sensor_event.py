"""Contract sensor-event 1.0.0, generated from odcs/sensor-event.odcs.yaml; do not edit."""

from typing import Any, ClassVar

from pydantic import Field

from ss_contracts.base import ContractModel, ContractTimestamp


class SensorEvent(ContractModel):
    """A field observation normalized for the realtime threat runtime: which node reported it, in
    which sector, with its measurements in the payload. Published by the sensor mesh and
    consumed by the fusion runtime (coop_ingest.sensor_reading_to_event).
    """

    CONTRACT_ID: ClassVar[str] = "sensor-event"
    CONTRACT_VERSION: ClassVar[str] = "1.0.0"
    SS_BINDING: ClassVar[dict[str, str]] = {
        "mqttTopic": "ss/v1/site/{site_id}/node/{node_id}/sensor-event",
        "timeBase": "utc",
    }

    event_kind: str = Field(
        description="Event discriminator, always 'sensor'.",
        pattern="^sensor$",
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
