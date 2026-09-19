"""Contract mission-bundle 1.0.0, generated from odcs/mission-bundle.odcs.yaml; do not edit."""

from typing import ClassVar

from pydantic import Field

from ss_contracts.base import ContractModel, ContractRecord, ContractTimestamp


class Platform(ContractRecord):
    """The recording platform."""

    robot_id: str = Field(
        description="Platform that recorded the mission (missions.robot_id; robot_0 by default).",
        min_length=1,
    )
    camera_model: str | None = Field(
        default=None,
        description="Camera or vehicle model from the video container tags; unset when absent.",
        min_length=1,
    )


class GeoOrigin(ContractRecord):
    """GPS origin of the mission ENU frame: the first GPS fix of the first video, as platform
    fusion and the missions gps_origin_json choose it; unset without GPS.
    """

    lat: float = Field(
        description="Latitude of the origin.",
        ge=-90,
        le=90,
        json_schema_extra={
            "x-ss-binding": {
                "frame": "wgs84",
                "unit": "deg",
            },
        },
    )
    lon: float = Field(
        description="Longitude of the origin.",
        ge=-180,
        le=180,
        json_schema_extra={
            "x-ss-binding": {
                "frame": "wgs84",
                "unit": "deg",
            },
        },
    )
    alt: float = Field(
        description="Altitude of the origin; 0 when the fix has none.",
        json_schema_extra={
            "x-ss-binding": {
                "frame": "wgs84",
                "unit": "m",
            },
        },
    )


class BundleVideo(ContractRecord):
    """One video file of the mission."""

    video_id: str = Field(
        description="Video identifier: the file stem.",
        min_length=1,
    )
    path: str = Field(
        description="POSIX path relative to the directory holding the manifest; no absolute paths, backslashes, or segments starting with a dot.",
        pattern="^([^/\\\\.][^/\\\\]*/)*[^/\\\\.][^/\\\\]*$",
    )
    sha256: str = Field(
        description="SHA-256 of the file content, lowercase hex.",
        pattern="^[0-9a-f]{64}$",
    )
    size_bytes: int = Field(
        description="File size.",
        ge=0,
        le=9223372036854775807,
        json_schema_extra={
            "x-ss-binding": {
                "unit": "By",
            },
        },
    )
    duration_sec: float | None = Field(
        default=None,
        description="Container duration.",
        ge=0,
        json_schema_extra={
            "x-ss-binding": {
                "unit": "s",
            },
        },
    )
    fps: float | None = Field(
        default=None,
        description="Average frame rate of the video stream.",
        gt=0,
        json_schema_extra={
            "x-ss-binding": {
                "unit": "Hz",
            },
        },
    )
    width: int | None = Field(
        default=None,
        description="Frame width.",
        ge=1,
        le=2147483647,
        json_schema_extra={
            "x-ss-binding": {
                "unit": "{pixel}",
            },
        },
    )
    height: int | None = Field(
        default=None,
        description="Frame height.",
        ge=1,
        le=2147483647,
        json_schema_extra={
            "x-ss-binding": {
                "unit": "{pixel}",
            },
        },
    )
    gps_source: str | None = Field(
        default=None,
        description="Where GPS for this video comes from: srt (DJI sidecar) or atom (ISO 6709 container tag); unset when the video has no GPS.",
        pattern="^(srt|atom)$",
    )


class BundleSidecar(ContractRecord):
    """One sensor sidecar file of a video."""

    video_id: str = Field(
        description="Video this sidecar belongs to.",
        min_length=1,
    )
    kind: str = Field(
        description="Sensor kind from the file name <video>.<kind>.jsonl (imu, baro, wind, env, gas, adsb, acoustic_events, ...); gps for a DJI .srt file.",
        pattern="^[a-z][a-z0-9_]*$",
    )
    format: str = Field(
        description="File format: jsonl rows or a DJI srt file.",
        pattern="^(jsonl|srt)$",
    )
    path: str = Field(
        description="POSIX path relative to the directory holding the manifest; no absolute paths, backslashes, or segments starting with a dot.",
        pattern="^([^/\\\\.][^/\\\\]*/)*[^/\\\\.][^/\\\\]*$",
    )
    sha256: str = Field(
        description="SHA-256 of the file content, lowercase hex.",
        pattern="^[0-9a-f]{64}$",
    )
    size_bytes: int = Field(
        description="File size.",
        ge=0,
        le=9223372036854775807,
        json_schema_extra={
            "x-ss-binding": {
                "unit": "By",
            },
        },
    )
    row_count: int = Field(
        description="Rows the loader reads: JSON objects in a jsonl file, GPS fixes in an srt file.",
        ge=0,
        le=9223372036854775807,
    )
    t_start_sec: float | None = Field(
        default=None,
        description="Earliest row time in the bundle time base; unset when no row has one.",
        json_schema_extra={
            "x-ss-binding": {
                "unit": "s",
            },
        },
    )
    t_end_sec: float | None = Field(
        default=None,
        description="Latest row time in the bundle time base; unset when no row has one.",
        json_schema_extra={
            "x-ss-binding": {
                "unit": "s",
            },
        },
    )


class MissionBundle(ContractModel):
    """The files of one recorded mission as offline and deep analysis consume them: videos, their
    sensor sidecars, the time base of sidecar rows, the GPS origin of the local ENU frame, and
    the platform that recorded them. Written as mission.json at the bundle root by ss-video and
    validated by ss-sens and ss-fusion before they read the bundle.
    """

    CONTRACT_ID: ClassVar[str] = "mission-bundle"
    CONTRACT_VERSION: ClassVar[str] = "1.0.0"

    mission_id: str = Field(
        description="Mission identifier: the missions row id, or the video stem for a local run.",
        min_length=1,
    )
    created_at: ContractTimestamp = Field(
        description="Time the manifest was built.",
        json_schema_extra={
            "x-ss-binding": {
                "timeBase": "utc",
            },
        },
    )
    time_base: str = Field(
        description="Time base of sidecar row times (the t or timestamp key) and video offsets; media means seconds from the start of the video the sidecar belongs to.",
        pattern="^(utc|gps|tai|monotonic|media)$",
    )
    start_time: ContractTimestamp | None = Field(
        default=None,
        description="Wall-clock time of media offset 0 of the first video, from its container creation time; unset when the container carries none.",
        json_schema_extra={
            "x-ss-binding": {
                "timeBase": "utc",
            },
        },
    )
    platform: Platform = Field(
        description="The recording platform.",
    )
    origin: GeoOrigin | None = Field(
        default=None,
        description="GPS origin of the mission ENU frame: the first GPS fix of the first video, as platform fusion and the missions gps_origin_json choose it; unset without GPS.",
    )
    videos: list[BundleVideo] = Field(
        description="Videos of the mission.",
        min_length=1,
    )
    sidecars: list[BundleSidecar] = Field(
        description="Sensor sidecars of the videos; empty when the mission has none.",
    )
