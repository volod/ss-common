"""Contract sensor-reading 1.0.0, generated from odcs/sensor-reading.odcs.yaml; do not edit."""

from typing import Any, ClassVar

from pydantic import Field

from ss_contracts.base import ContractBytes, ContractModel, ContractTimestamp


class SensorReading(ContractModel):
    """One decoded LoRaWAN uplink from a field sensor node: radio statistics, the measurements the
    codec reported under known aliases, and the raw and decoded payloads. Produced by
    decode_chirpstack_uplink from a ChirpStack uplink event.
    """

    CONTRACT_ID: ClassVar[str] = "sensor-reading"
    CONTRACT_VERSION: ClassVar[str] = "1.0.0"
    SS_BINDING: ClassVar[dict[str, str]] = {
        "modality": "lorawan",
        "mqttTopic": "ss/v1/site/{site_id}/sensor/{dev_eui}/reading",
        "timeBase": "utc",
    }

    dev_eui: str = Field(
        description="LoRaWAN device EUI as reported by ChirpStack.",
        min_length=1,
    )
    application_id: str = Field(
        description="ChirpStack application id; empty when absent.",
    )
    received_at: ContractTimestamp = Field(
        description="Uplink time from the network server.",
        json_schema_extra={
            "x-ss-binding": {
                "timeBase": "utc",
            },
        },
    )
    f_cnt: int = Field(
        description="Uplink frame counter.",
        ge=0,
        le=9223372036854775807,
    )
    rssi: float | None = Field(
        default=None,
        description="RSSI of the first receiving gateway.",
        json_schema_extra={
            "x-ss-binding": {
                "unit": "dB",
            },
        },
    )
    snr: float | None = Field(
        default=None,
        description="SNR of the first receiving gateway.",
        json_schema_extra={
            "x-ss-binding": {
                "unit": "dB",
            },
        },
    )
    temperature_c: float | None = Field(
        default=None,
        description="Air temperature.",
        json_schema_extra={
            "x-ss-binding": {
                "modality": "environmental",
                "unit": "Cel",
            },
        },
    )
    humidity_pct: float | None = Field(
        default=None,
        description="Relative humidity.",
        ge=0,
        le=100,
        json_schema_extra={
            "x-ss-binding": {
                "modality": "environmental",
                "unit": "%",
            },
        },
    )
    co2_ppm: float | None = Field(
        default=None,
        description="CO2 concentration.",
        ge=0,
        json_schema_extra={
            "x-ss-binding": {
                "modality": "environmental",
                "unit": "[ppm]",
            },
        },
    )
    pressure_hpa: float | None = Field(
        default=None,
        description="Barometric pressure.",
        ge=0,
        json_schema_extra={
            "x-ss-binding": {
                "modality": "environmental",
                "unit": "hPa",
            },
        },
    )
    battery_v: float | None = Field(
        default=None,
        description="Node battery voltage.",
        ge=0,
        json_schema_extra={
            "x-ss-binding": {
                "unit": "V",
            },
        },
    )
    motion: bool | None = Field(
        default=None,
        description="Motion, PIR, occupancy, or presence flag from the codec.",
    )
    gps_lat: float | None = Field(
        default=None,
        description="Node latitude from the codec.",
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
        description="Node longitude from the codec.",
        ge=-180,
        le=180,
        json_schema_extra={
            "x-ss-binding": {
                "frame": "wgs84",
                "unit": "deg",
            },
        },
    )
    gps_alt_m: float | None = Field(
        default=None,
        description="Node altitude above the WGS84 ellipsoid from the codec.",
        json_schema_extra={
            "x-ss-binding": {
                "frame": "wgs84",
                "unit": "m",
            },
        },
    )
    raw_bytes: ContractBytes | None = Field(
        default=None,
        description="Raw uplink payload (FRMPayload).",
    )
    decoded_object: dict[str, Any] = Field(
        description="Decoded payload object from the ChirpStack codec.",
    )
