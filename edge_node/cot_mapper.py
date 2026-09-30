"""Cursor-on-Target (CoT) JSON Serialization Layer.

Translates internal strongly-typed Pydantic telemetry models into
the standardized Cursor-on-Target (CoT) JSON schema for interoperability
with TAK servers, ATAK clients, and the KestrelCOP collector bus.
"""

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from edge_node.models import (
    BiometricEvent,
    DetectionEvent,
    LocationEvent,
    TelemetryEvent,
)


def format_cot_timestamp(dt: datetime) -> str:
    """Format datetime into ISO-8601 UTC timestamp expected by Cursor-on-Target."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def telemetry_to_cot_dict(
    event: TelemetryEvent,
    last_known_location: LocationEvent | None = None,
    stale_duration_seconds: float = 30.0,
    callsign: str | None = None,
) -> dict[str, Any]:
    """Convert a TelemetryEvent into a standardized Cursor-on-Target dictionary.

    Args:
        event: The incoming strongly-typed sensor event.
        last_known_location: Fallback location for events lacking native coordinates
            (e.g., biometric readings from a wearable).
        stale_duration_seconds: How long before this track should be considered stale.
        callsign: Human-readable tactical callsign override (default: source_id).

    Returns:
        A dictionary conforming to the standard JSON Cursor-on-Target (CoT) schema.
    """
    effective_callsign = callsign or event.source_id
    event_time = event.timestamp
    stale_time = event_time + timedelta(seconds=stale_duration_seconds)

    # Base Point defaults (null-island fallback if completely unknown)
    lat = 0.0
    lon = 0.0
    hae = 0.0
    ce = 999999.0
    le = 999999.0

    cot_type = "u-d"  # Unknown / Data default
    how = "m-g"  # Machine-generated
    detail: dict[str, Any] = {
        "contact": {"callsign": effective_callsign},
    }

    if isinstance(event, LocationEvent):
        cot_type = "a-f-G-U-C"  # Friendly Ground Unit
        lat = event.latitude
        lon = event.longitude
        hae = event.altitude_m
        ce = event.circular_error_m
        le = event.linear_error_m
        how = "m-g"

        loc_detail: dict[str, Any] = {}
        if event.speed_mps is not None:
            loc_detail["speed"] = event.speed_mps
        if event.heading_deg is not None:
            loc_detail["course"] = event.heading_deg
        if loc_detail:
            detail["track"] = loc_detail

    elif isinstance(event, BiometricEvent):
        # Tactical Combat Casualty Care (TCCC) / Biometrics type
        cot_type = "b-m-p-s-m"
        how = "m-g"

        if last_known_location is not None:
            lat = last_known_location.latitude
            lon = last_known_location.longitude
            hae = last_known_location.altitude_m
            ce = last_known_location.circular_error_m
            le = last_known_location.linear_error_m

        bio_data: dict[str, Any] = {
            "heart_rate_bpm": event.heart_rate_bpm,
            "tccc_alert": event.tccc_alert,
        }
        if event.spo2_percent is not None:
            bio_data["spo2_percent"] = event.spo2_percent
        if event.skin_temp_c is not None:
            bio_data["skin_temp_c"] = event.skin_temp_c
        if event.stress_level is not None:
            bio_data["stress_level"] = event.stress_level

        detail["biometrics"] = bio_data

    elif isinstance(event, DetectionEvent):
        # Unknown or Hostile entity detected by computer vision
        cot_type = "a-u-G-E-V"  # Unknown Ground Vehicle / Entity
        how = "m-a"  # Machine-algorithm

        if event.estimated_lat is not None and event.estimated_lon is not None:
            lat = event.estimated_lat
            lon = event.estimated_lon
            ce = 15.0  # Estimated geolocation error
        elif last_known_location is not None:
            lat = last_known_location.latitude
            lon = last_known_location.longitude
            hae = last_known_location.altitude_m
            ce = last_known_location.circular_error_m

        detection_data: dict[str, Any] = {
            "label": event.label,
            "confidence": event.confidence,
        }
        if event.bbox is not None:
            detection_data["bbox"] = list(event.bbox)
        if event.bearing_deg is not None:
            detection_data["bearing_deg"] = event.bearing_deg
        if event.range_m is not None:
            detection_data["range_m"] = event.range_m

        detail["sensor_payload"] = detection_data

    return {
        "event": {
            "version": "2.0",
            "uid": event.source_id,
            "type": cot_type,
            "how": how,
            "time": format_cot_timestamp(event_time),
            "start": format_cot_timestamp(event_time),
            "stale": format_cot_timestamp(stale_time),
            "point": {
                "lat": round(lat, 7),
                "lon": round(lon, 7),
                "hae": round(hae, 2),
                "ce": round(ce, 2),
                "le": round(le, 2),
            },
            "detail": detail,
        }
    }


def telemetry_to_cot_json(
    event: TelemetryEvent,
    last_known_location: LocationEvent | None = None,
    stale_duration_seconds: float = 30.0,
    callsign: str | None = None,
    indent: int | None = None,
) -> str:
    """Serialize a TelemetryEvent directly into a Cursor-on-Target JSON string."""
    cot_dict = telemetry_to_cot_dict(
        event=event,
        last_known_location=last_known_location,
        stale_duration_seconds=stale_duration_seconds,
        callsign=callsign,
    )
    return json.dumps(cot_dict, indent=indent)
