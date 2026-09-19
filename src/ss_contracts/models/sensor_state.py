"""Contract sensor-state 1.0.0, generated from odcs/sensor-state.odcs.yaml; do not edit."""

from typing import ClassVar

from pydantic import Field

from ss_contracts.base import ContractModel, ContractTimestamp


class SensorState(ContractModel):
    """Latest state of one LoRaWAN sensor over the rolling window: when it was last seen, how many
    readings the window holds, and the values of its most recent reading. The sensor half of the
    site state: one retained message per device, so a new subscriber sees every sensor.
    """

    CONTRACT_ID: ClassVar[str] = "sensor-state"
    CONTRACT_VERSION: ClassVar[str] = "1.0.0"
    SS_BINDING: ClassVar[dict[str, str]] = {
        "modality": "lorawan",
        "mqttTopic": "ss/v1/site/{site_id}/sensor/{dev_eui}/state",
        "timeBase": "utc",
    }

    dev_eui: str = Field(
        description="LoRaWAN device EUI.",
        min_length=1,
    )
    last_seen: ContractTimestamp = Field(
        description="Receive time of the most recent reading.",
        json_schema_extra={
            "x-ss-binding": {
                "timeBase": "utc",
            },
        },
    )
    reading_count: int = Field(
        description="Readings inside the rolling window.",
        ge=0,
        le=2147483647,
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
