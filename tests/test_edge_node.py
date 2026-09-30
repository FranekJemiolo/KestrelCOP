"""Unit tests for KestrelCOP Edge Node schemas, CoT serialization, and event bus."""

import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from edge_node.cot_mapper import telemetry_to_cot_dict, telemetry_to_cot_json
from edge_node.main import TacticalEventBus, run_edge_node
from edge_node.models import BiometricEvent, DetectionEvent, LocationEvent


def test_location_event_valid() -> None:
    """Verify that a valid LocationEvent is properly instantiated."""
    loc = LocationEvent(
        source_id="operator-01",
        latitude=52.2297,
        longitude=21.0122,
        altitude_m=120.0,
        circular_error_m=2.5,
        speed_mps=1.5,
        heading_deg=180.0,
    )
    assert loc.source_id == "operator-01"
    assert loc.latitude == 52.2297
    assert loc.longitude == 21.0122
    assert loc.speed_mps == 1.5


def test_location_event_invalid_coordinates() -> None:
    """Verify that out-of-range coordinates are rejected immediately by Pydantic."""
    with pytest.raises(ValidationError):
        LocationEvent(
            source_id="bad-gps",
            latitude=95.0,  # Invalid: > 90
            longitude=21.0,
        )

    with pytest.raises(ValidationError):
        LocationEvent(
            source_id="bad-gps",
            latitude=52.0,
            longitude=195.0,  # Invalid: > 180
        )


def test_biometric_event_bounds() -> None:
    """Verify biometric values adhere to strict tactical physiological bounds."""
    bio = BiometricEvent(
        source_id="operator-01",
        heart_rate_bpm=145,
        spo2_percent=98.0,
        stress_level="elevated",
        tccc_alert=True,
    )
    assert bio.heart_rate_bpm == 145
    assert bio.tccc_alert is True

    # Reject physiologically impossible heart rates (< 20 or > 260)
    with pytest.raises(ValidationError):
        BiometricEvent(source_id="bad-bio", heart_rate_bpm=10)

    with pytest.raises(ValidationError):
        BiometricEvent(source_id="bad-bio", heart_rate_bpm=300)


def test_detection_event_confidence_bounds() -> None:
    """Verify object detection events enforce confidence in [0, 1]."""
    det = DetectionEvent(
        source_id="drone-01",
        label="unmanned_aerial_vehicle",
        confidence=0.88,
        bbox=(0.1, 0.2, 0.3, 0.4),
    )
    assert det.label == "unmanned_aerial_vehicle"
    assert det.confidence == 0.88

    with pytest.raises(ValidationError):
        DetectionEvent(source_id="bad-det", label="tank", confidence=1.5)


def test_cot_mapper_location() -> None:
    """Verify translation of LocationEvent to standardized Cursor-on-Target schema."""
    now = datetime(2026, 9, 30, 14, 0, 0, tzinfo=UTC)
    loc = LocationEvent(
        source_id="kestrel-scout-01",
        timestamp=now,
        latitude=52.229712,
        longitude=21.012234,
        altitude_m=140.5,
        circular_error_m=2.0,
        linear_error_m=4.0,
        speed_mps=2.1,
        heading_deg=90.0,
    )

    cot = telemetry_to_cot_dict(loc, stale_duration_seconds=30.0)
    event = cot["event"]

    assert event["version"] == "2.0"
    assert event["uid"] == "kestrel-scout-01"
    assert event["type"] == "a-f-G-U-C"
    assert event["how"] == "m-g"
    assert event["point"]["lat"] == 52.229712
    assert event["point"]["lon"] == 21.012234
    assert event["point"]["hae"] == 140.5
    assert event["point"]["ce"] == 2.0
    assert event["detail"]["contact"]["callsign"] == "kestrel-scout-01"
    assert event["detail"]["track"]["speed"] == 2.1


def test_cot_mapper_biometrics_with_fallback_location() -> None:
    """Verify that BiometricEvent borrows the operator's last known location."""
    now = datetime(2026, 9, 30, 14, 0, 0, tzinfo=UTC)
    last_loc = LocationEvent(
        source_id="kestrel-alpha",
        timestamp=now,
        latitude=52.2297,
        longitude=21.0122,
    )
    bio = BiometricEvent(
        source_id="kestrel-alpha",
        timestamp=now,
        heart_rate_bpm=162,
        tccc_alert=True,
    )

    cot_json_str = telemetry_to_cot_json(bio, last_known_location=last_loc)
    parsed = json.loads(cot_json_str)

    assert parsed["event"]["type"] == "b-m-p-s-m"
    assert parsed["event"]["point"]["lat"] == 52.2297
    assert parsed["event"]["detail"]["biometrics"]["heart_rate_bpm"] == 162
    assert parsed["event"]["detail"]["biometrics"]["tccc_alert"] is True


def test_cot_mapper_detection() -> None:
    """Verify detection event serialization to CoT schema."""
    det = DetectionEvent(
        source_id="recon-drone",
        label="armored_vehicle",
        confidence=0.95,
        estimated_lat=52.235,
        estimated_lon=21.025,
    )
    cot = telemetry_to_cot_dict(det)
    event = cot["event"]

    assert event["type"] == "a-u-G-E-V"
    assert event["how"] == "m-a"
    assert event["point"]["lat"] == 52.235
    assert event["detail"]["sensor_payload"]["label"] == "armored_vehicle"
    assert event["detail"]["sensor_payload"]["confidence"] == 0.95


@pytest.mark.asyncio
async def test_event_bus_bounded_eviction() -> None:
    """Verify TacticalEventBus evicts oldest items when queue capacity is reached."""
    bus = TacticalEventBus(maxsize=3)

    e1 = LocationEvent(source_id="e1", latitude=10.0, longitude=20.0)
    e2 = LocationEvent(source_id="e2", latitude=10.0, longitude=20.0)
    e3 = LocationEvent(source_id="e3", latitude=10.0, longitude=20.0)
    e4 = LocationEvent(source_id="e4", latitude=10.0, longitude=20.0)

    await bus.put(e1)
    await bus.put(e2)
    await bus.put(e3)
    assert bus.qsize == 3
    assert bus.dropped_count == 0

    # Putting 4th item on maxsize=3 queue should drop the oldest item (e1)
    await bus.put(e4)
    assert bus.qsize == 3
    assert bus.dropped_count == 1

    first_popped = await bus.get()
    # Oldest (e1) was evicted, so first popped should be e2
    assert first_popped.source_id == "e2"


@pytest.mark.asyncio
async def test_run_edge_node_brief_execution() -> None:
    """Verify edge node event loop can launch and shut down gracefully."""
    # Run the event loop for a brief fractional second
    await run_edge_node(max_iterations=1)
