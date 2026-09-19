"""Contract scene-caption 1.0.0, generated from odcs/scene-caption.odcs.yaml; do not edit."""

from typing import Any, ClassVar

from pydantic import Field

from ss_contracts.base import ContractModel, ContractTimestamp


class SceneCaption(ContractModel):
    """A caption of one keyframe from a live or mission video stream, with the structured scene
    facts when the vision-language model produced them and the GPS position when known. One row
    of the scene_timeline table, written by RtspCaptioner.
    """

    CONTRACT_ID: ClassVar[str] = "scene-caption"
    CONTRACT_VERSION: ClassVar[str] = "1.0.0"
    SS_BINDING: ClassVar[dict[str, str]] = {
        "modality": "camera",
        "mqttTopic": "ss/v1/site/{site_id}/mission/{mission_id}/scene-caption",
    }

    mission_id: str = Field(
        description="Mission or live-stream session the frame belongs to.",
        min_length=1,
    )
    frame_id: str = Field(
        description="Keyframe id within the mission.",
        min_length=1,
    )
    gps_lat: float | None = Field(
        default=None,
        description="Camera latitude.",
        ge=-90,
        le=90,
        json_schema_extra={
            "x-ss-binding": {
                "frame": "wgs84",
                "unit": "deg",
            },
        },
    )
    gps_lon: float | None = Field(
        default=None,
        description="Camera longitude.",
        ge=-180,
        le=180,
        json_schema_extra={
            "x-ss-binding": {
                "frame": "wgs84",
                "unit": "deg",
            },
        },
    )
    gps_alt: float | None = Field(
        default=None,
        description="Camera altitude.",
        json_schema_extra={
            "x-ss-binding": {
                "frame": "wgs84",
                "unit": "m",
            },
        },
    )
    t_sec: float | None = Field(
        default=None,
        description="Frame offset into the stream.",
        ge=0,
        json_schema_extra={
            "x-ss-binding": {
                "timeBase": "media",
                "unit": "s",
            },
        },
    )
    caption: str | None = Field(
        default=None,
        description="Caption text; unset when no captioner answered.",
    )
    facts_json: dict[str, Any] | None = Field(
        default=None,
        description="Structured scene facts from the vision-language model.",
    )
    created_at: ContractTimestamp = Field(
        description="Time the row was written.",
        json_schema_extra={
            "x-ss-binding": {
                "timeBase": "utc",
            },
        },
    )
