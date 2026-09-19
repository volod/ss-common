"""Contract camera-event 1.0.0, generated from odcs/camera-event.odcs.yaml; do not edit."""

from typing import Any, ClassVar

from pydantic import Field

from ss_contracts.base import ContractModel, ContractTimestamp


class CameraEvent(ContractModel):
    """One object-detection lifecycle event from the NVR (Frigate): the tracked object, its scores,
    its normalized bounding region, and the media available for it. Produced by
    FrigateEventConsumer.decode from a frigate/events message.
    """

    CONTRACT_ID: ClassVar[str] = "camera-event"
    CONTRACT_VERSION: ClassVar[str] = "1.0.0"
    SS_BINDING: ClassVar[dict[str, str]] = {
        "modality": "camera",
        "mqttTopic": "ss/v1/site/{site_id}/camera/{camera}/event",
        "timeBase": "utc",
    }

    event_id: str = Field(
        description="NVR event id of the tracked object; empty when absent.",
    )
    camera: str = Field(
        description="Camera name.",
        min_length=1,
    )
    label: str = Field(
        description="Detected object label.",
        min_length=1,
    )
    score: float = Field(
        description="Current detection score.",
        ge=0,
        le=1,
    )
    top_score: float = Field(
        description="Highest score over the object's life.",
        ge=0,
        le=1,
    )
    event_type: str = Field(
        description="Lifecycle stage: new, update, or end.",
        pattern="^(new|update|end)$",
    )
    started_at: ContractTimestamp = Field(
        description="Time the object was first detected.",
        json_schema_extra={
            "x-ss-binding": {
                "timeBase": "utc",
            },
        },
    )
    ended_at: ContractTimestamp | None = Field(
        default=None,
        description="Time the object left the frame; unset while active.",
        json_schema_extra={
            "x-ss-binding": {
                "timeBase": "utc",
            },
        },
    )
    has_snapshot: bool = Field(
        description="A snapshot image is available.",
    )
    has_clip: bool = Field(
        description="A recorded clip is available.",
    )
    region: dict[str, Any] = Field(
        description="Normalized detection region: numeric x, y, width, height in 0-1.",
        json_schema_extra={
            "x-ss-binding": {
                "frame": "image",
            },
        },
    )
    raw: dict[str, Any] = Field(
        description="The complete NVR event message, passed through.",
    )
