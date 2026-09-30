"""Data models for KestrelCOP Edge Node.

Defines strictly typed Pydantic models for internal sensor telemetry events.
These models ensure immediate schema validation at the edge, rejecting
malformed sensor packets before they reach the Cursor-on-Target serialization layer.
"""

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field


class BaseTelemetryEvent(BaseModel):
    """Base schema for all edge telemetry events."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str = Field(
        ...,
        description="Unique identifier of device or sensor (e.g., 'kestrel-alpha-01')",
        min_length=1,
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="UTC timestamp of the observation",
    )


class LocationEvent(BaseTelemetryEvent):
    """Geospatial fix ingested from GPS/NMEA serial receiver."""

    latitude: float = Field(
        ...,
        ge=-90.0,
        le=90.0,
        description="WGS84 latitude coordinate in decimal degrees",
    )
    longitude: float = Field(
        ...,
        ge=-180.0,
        le=180.0,
        description="WGS84 longitude coordinate in decimal degrees",
    )
    altitude_m: float = Field(
        default=0.0,
        description="Height above ellipsoid (HAE) or mean sea level in meters",
    )
    circular_error_m: float = Field(
        default=5.0,
        ge=0.0,
        description="Circular Error Probable (CE) 1-sigma horizontal accuracy in meters",
    )
    linear_error_m: float = Field(
        default=10.0,
        ge=0.0,
        description="Linear Error (LE) 1-sigma vertical accuracy in meters",
    )
    speed_mps: float | None = Field(
        default=None,
        ge=0.0,
        description="Ground speed in meters per second",
    )
    heading_deg: float | None = Field(
        default=None,
        ge=0.0,
        le=360.0,
        description="True course heading in degrees (0-360)",
    )


class BiometricEvent(BaseTelemetryEvent):
    """Physiological vitals ingested from Bluetooth Low Energy (BLE) peripherals."""

    heart_rate_bpm: int = Field(
        ...,
        ge=20,
        le=260,
        description="Current heart rate in beats per minute",
    )
    spo2_percent: float | None = Field(
        default=None,
        ge=50.0,
        le=100.0,
        description="Peripheral capillary oxygen saturation percentage",
    )
    skin_temp_c: float | None = Field(
        default=None,
        ge=20.0,
        le=45.0,
        description="Skin temperature in degrees Celsius",
    )
    stress_level: str | None = Field(
        default=None,
        description="Heuristic stress classification (e.g. 'nominal', 'elevated', 'critical')",
    )
    tccc_alert: bool = Field(
        default=False,
        description="Tactical Combat Casualty Care emergency casualty flag",
    )


class DetectionEvent(BaseTelemetryEvent):
    """Computer vision inference classification from edge YOLO / ONNX runtime."""

    label: str = Field(
        ...,
        min_length=1,
        description="Classification label (e.g. 'personnel', 'vehicle', 'drone', 'weapon')",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Detector model confidence score between 0.0 and 1.0",
    )
    bbox: tuple[float, float, float, float] | None = Field(
        default=None,
        description="Normalized bounding box coordinates (xmin, ymin, xmax, ymax)",
    )
    estimated_lat: float | None = Field(
        default=None,
        ge=-90.0,
        le=90.0,
        description="Geolocated target latitude if gimbal/dem calculation was performed",
    )
    estimated_lon: float | None = Field(
        default=None,
        ge=-180.0,
        le=180.0,
        description="Geolocated target longitude if gimbal/dem calculation was performed",
    )
    bearing_deg: float | None = Field(
        default=None,
        ge=0.0,
        le=360.0,
        description="Relative or true line-of-bearing to detected object in degrees",
    )
    range_m: float | None = Field(
        default=None,
        ge=0.0,
        description="Estimated laser rangefinder or optical range in meters",
    )


# Union type for all supported telemetry event types
type TelemetryEvent = LocationEvent | BiometricEvent | DetectionEvent
