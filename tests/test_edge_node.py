"""Comprehensive unit & integration test suite for KestrelCOP Edge Node.

Covers:
  - NMEA sentence parsing, checksum calculation, and coordinate conversion
  - BLE GATT characteristic 0x2A37 binary parsing
  - Isolated Multiprocessing ML pipeline & IPC bridge
  - Tactical MQTT publisher, bounded offline buffering, and stale data expiration
  - Full async lifecycle and graceful shutdown
"""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from edge_node.ble_worker import generate_mock_gatt_payload, parse_gatt_heart_rate
from edge_node.cot_mapper import telemetry_to_cot_dict, telemetry_to_cot_json
from edge_node.gps_worker import generate_mock_gpgga
from edge_node.main import TacticalEventBus, run_edge_node
from edge_node.ml_worker import TacticalMlPipeline
from edge_node.models import BiometricEvent, DetectionEvent, LocationEvent
from edge_node.nmea_parser import parse_nmea_sentence, verify_nmea_checksum
from edge_node.publisher import MqttTacticalPublisher

# ==========================================
# 1. Models & Validations
# ==========================================


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
    """Verify out-of-range coordinates are rejected immediately by Pydantic."""
    with pytest.raises(ValidationError):
        LocationEvent(source_id="bad-gps", latitude=95.0, longitude=21.0)

    with pytest.raises(ValidationError):
        LocationEvent(source_id="bad-gps", latitude=52.0, longitude=195.0)


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


# ==========================================
# 2. NMEA GPS Parsing & Checksum Tests
# ==========================================


def test_nmea_checksum_validation() -> None:
    """Verify NMEA XOR checksum verification."""
    # Checksum calculation: XOR of all characters between '$' and '*'
    body = "GPGGA,092750.000,5321.6802,N,00630.3372,W,1,8,1.03,61.7,M,55.2,M,,"
    c = 0
    for char in body:
        c ^= ord(char)
    expected_hex = f"{c:02X}"
    assert verify_nmea_checksum(f"${body}*{expected_hex}") is True
    assert verify_nmea_checksum(f"${body}*00") is False


def test_parse_gpgga_sentence() -> None:
    """Verify parsing of synthetic and real GPGGA strings."""
    nmea = generate_mock_gpgga(lat=52.229712, lon=21.012234, alt=142.5, hdop=1.2)
    assert verify_nmea_checksum(nmea) is True

    fix = parse_nmea_sentence(nmea)
    assert fix is not None
    assert pytest.approx(fix.latitude, rel=1e-4) == 52.2297
    assert pytest.approx(fix.longitude, rel=1e-4) == 21.0122
    assert fix.altitude_m == 142.5
    assert fix.circular_error_m == 3.0  # 1.2 * 2.5


def test_parse_gprmc_sentence() -> None:
    """Verify parsing of valid GPRMC sentence."""
    body = "GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W"
    c = 0
    for char in body:
        c ^= ord(char)
    sentence = f"${body}*{c:02X}"

    fix = parse_nmea_sentence(sentence)
    assert fix is not None
    assert pytest.approx(fix.latitude, rel=1e-4) == 48.1173
    assert pytest.approx(fix.longitude, rel=1e-4) == 11.5166
    assert fix.speed_mps == round(22.4 * 0.514444, 2)
    assert fix.heading_deg == 84.4


# ==========================================
# 3. BLE GATT Characteristic Tests
# ==========================================


def test_ble_gatt_uint8_heart_rate() -> None:
    """Verify parsing of uint8 BLE Heart Rate Measurement payload."""
    raw = generate_mock_gatt_payload(bpm=82)
    bpm, contact = parse_gatt_heart_rate(raw)
    assert bpm == 82
    assert contact is True


def test_ble_gatt_uint16_heart_rate() -> None:
    """Verify parsing of uint16 BLE Heart Rate Measurement payload."""
    # Flag: bit 0 set (0x01) -> uint16, sensor contact (0x06) -> 0x07
    # 180 bpm in 2-byte little endian: 0x00B4 -> [0xB4, 0x00]
    payload = bytes([0x07, 0xB4, 0x00])
    bpm, contact = parse_gatt_heart_rate(payload)
    assert bpm == 180
    assert contact is True


def test_ble_gatt_invalid_payload() -> None:
    """Verify error on truncated BLE GATT payload."""
    with pytest.raises(ValueError):
        parse_gatt_heart_rate(b"")

    with pytest.raises(ValueError):
        parse_gatt_heart_rate(bytes([0x01]))  # uint16 flag but only 1 byte


# ==========================================
# 4. CoT Serialization & QoS Policy Tests
# ==========================================


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


# ==========================================
# 5. Publisher, Offline Buffering & Stale Pruning Tests
# ==========================================


def test_publisher_qos_prioritization() -> None:
    """Verify publisher applies QoS 1 to life-safety alerts and QoS 0 to routine tracks."""
    publisher = MqttTacticalPublisher()

    loc = LocationEvent(source_id="alpha", latitude=10.0, longitude=20.0)
    routine_bio = BiometricEvent(source_id="alpha", heart_rate_bpm=75, tccc_alert=False)
    critical_bio = BiometricEvent(source_id="alpha", heart_rate_bpm=170, tccc_alert=True)
    det = DetectionEvent(source_id="drone", label="vehicle", confidence=0.95)

    assert publisher.package_event(loc).qos == 0
    assert publisher.package_event(routine_bio).qos == 0
    assert publisher.package_event(critical_bio).qos == 1
    assert publisher.package_event(det).qos == 1


@pytest.mark.asyncio
async def test_publisher_offline_buffer_and_stale_pruning() -> None:
    """Verify offline buffer drops stale records when network link returns."""
    publisher = MqttTacticalPublisher(buffer_max_size=10)

    # 1. Create a stale packet (expired in the past)
    stale_event = LocationEvent(
        source_id="stale-node",
        timestamp=datetime.now(UTC) - timedelta(seconds=60),
        latitude=52.0,
        longitude=21.0,
    )
    stale_packet = publisher.package_event(stale_event, stale_duration=10.0)

    # 2. Create a fresh packet (expires 60s in the future)
    fresh_event = LocationEvent(
        source_id="fresh-node",
        timestamp=datetime.now(UTC),
        latitude=52.001,
        longitude=21.001,
    )
    fresh_packet = publisher.package_event(fresh_event, stale_duration=60.0)

    # Add both to offline buffer
    publisher.offline_buffer.append(stale_packet)
    publisher.offline_buffer.append(fresh_packet)
    assert len(publisher.offline_buffer) == 2

    # Mock MQTT client
    mock_client = AsyncMock()
    mock_client.publish = AsyncMock()

    # Flush buffer
    flushed = await publisher._flush_offline_buffer(mock_client)

    # Stale packet was discarded; fresh packet was published
    assert flushed == 1
    assert publisher.stale_dropped_count == 1
    assert publisher.messages_published == 1
    mock_client.publish.assert_called_once_with(
        fresh_packet.topic,
        payload=fresh_packet.payload_json,
        qos=0,
    )


# ==========================================
# 6. Event Bus & ML Multiprocessing Tests
# ==========================================


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

    await bus.put(e4)
    assert bus.qsize == 3
    assert bus.dropped_count == 1

    first_popped = await bus.get()
    assert first_popped.source_id == "e2"


@pytest.mark.asyncio
async def test_tactical_ml_pipeline_lifecycle() -> None:
    """Verify ML worker process starts, outputs detections via IPC, and stops cleanly."""
    bus = TacticalEventBus(maxsize=50)
    pipeline = TacticalMlPipeline(bus=bus, fps_limit=5.0)

    pipeline.start()
    assert pipeline.process is not None
    assert pipeline.process.is_alive()

    shutdown = asyncio.Event()
    bridge_task = asyncio.create_task(pipeline.run_async_bridge(shutdown))

    # Wait dynamically for ML process to emit detections through IPC queue
    for _ in range(30):
        if bus.qsize > 0:
            break
        await asyncio.sleep(0.1)

    shutdown.set()
    await bridge_task
    pipeline.stop()

    assert not pipeline.process.is_alive()
    # Ensure detections arrived on the bus
    assert bus.qsize > 0
    first_event = await bus.get()
    assert isinstance(first_event, DetectionEvent)
    assert first_event.source_id == "kestrel-drone-overwatch"


@pytest.mark.asyncio
async def test_run_edge_node_full_pipeline_brief_execution() -> None:
    """Verify full edge node pipeline starts all workers and shuts down cleanly."""
    await run_edge_node(mock_mode=True, duration_seconds=1.2)


def test_publisher_exponential_backoff() -> None:
    """Verify MQTT publisher calculates exponential backoff and resets on connect."""
    pub = MqttTacticalPublisher(
        reconnect_interval_seconds=1.0,
        max_reconnect_interval_seconds=8.0,
        backoff_factor=2.0,
        jitter_ratio=0.05,
    )
    assert pub.current_backoff == 1.0

    # Step 1: ~1.0s (within 0.95 to 1.05), advances to 2.0
    d1 = pub.calculate_backoff()
    assert 0.9 <= d1 <= 1.1
    assert pub.current_backoff == 2.0

    # Step 2: ~2.0s, advances to 4.0
    d2 = pub.calculate_backoff()
    assert 1.8 <= d2 <= 2.2
    assert pub.current_backoff == 4.0

    # Step 3: ~4.0s, advances to 8.0
    d3 = pub.calculate_backoff()
    assert 3.6 <= d3 <= 4.4
    assert pub.current_backoff == 8.0

    # Step 4: capped at max_backoff (8.0)
    d4 = pub.calculate_backoff()
    assert 7.2 <= d4 <= 8.0
    assert pub.current_backoff == 8.0

    # Reset backoff
    pub.reset_backoff()
    assert pub.current_backoff == 1.0


def test_ml_worker_corrupted_frame_resilience() -> None:
    """Verify ML worker process handles corrupted video frame source without crashing."""
    import multiprocessing as mp
    import time

    from edge_node.ml_worker import run_ml_inference_process

    ipc_queue: mp.Queue[DetectionEvent] = mp.Queue()
    stop_event = mp.Event()

    p = mp.Process(
        target=run_ml_inference_process,
        kwargs={
            "ipc_queue": ipc_queue,
            "stop_event": stop_event,
            "video_source": "/dev/null/nonexistent_corrupted_stream.mp4",
            "fps_limit": 10.0,
        },
    )
    p.start()
    time.sleep(0.5)
    stop_event.set()
    p.join(timeout=3.0)
    assert not p.is_alive()
    assert p.exitcode == 0
