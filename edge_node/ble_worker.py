"""Bluetooth Low Energy (BLE) Biometric Ingestion Worker.

Subscribes to standard GATT Heart Rate Measurement characteristics (UUID 0x2A37)
using bleak or synthesizes biometric signals for testing. Parses GATT byte payloads
and pushes BiometricEvent objects to the tactical event bus.
"""

import asyncio
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from edge_node.models import BiometricEvent

if TYPE_CHECKING:
    from edge_node.main import TacticalEventBus

logger = logging.getLogger("edge_node.ble")

# Standard Bluetooth SIG Assigned Numbers for Heart Rate Service
HEART_RATE_MEASUREMENT_UUID = "00002a37-0000-1000-8000-00805f9b34fb"


def parse_gatt_heart_rate(payload: bytes) -> tuple[int, bool]:
    """Parse raw bytes from Bluetooth SIG GATT characteristic 0x2A37.

    Specification:
        Byte 0: Flags
            Bit 0: 0 = uint8 Heart Rate, 1 = uint16 Heart Rate
            Bit 1-2: Sensor Contact Status
            Bit 3: Energy Expended Status
            Bit 4: RR-Intervals Present
    Returns:
        tuple[int, bool]: (heart_rate_bpm, sensor_contact_detected)
    """
    if not payload:
        raise ValueError("Empty GATT payload")

    flags = payload[0]
    is_uint16 = bool(flags & 0x01)
    sensor_contact = bool(flags & 0x06)

    if is_uint16:
        if len(payload) < 3:
            raise ValueError("Payload too short for uint16 heart rate")
        hr_value = int.from_bytes(payload[1:3], byteorder="little")
    else:
        if len(payload) < 2:
            raise ValueError("Payload too short for uint8 heart rate")
        hr_value = payload[1]

    return hr_value, sensor_contact


def generate_mock_gatt_payload(bpm: int) -> bytes:
    """Generate a standard 2-byte uint8 GATT 0x2A37 payload for testing."""
    clamped_bpm = min(255, max(0, bpm))
    # Flags = 0x06 (sensor contact detected, uint8 format)
    return bytes([0x06, clamped_bpm])


async def run_ble_worker(
    bus: "TacticalEventBus",
    shutdown_event: asyncio.Event,
    device_address: str | None = None,
    source_id: str = "kestrel-alpha-01",
    poll_interval_seconds: float = 2.0,
    mock_mode: bool = True,
) -> None:
    """Main BLE biometric worker loop.

    Connects to physical BLE strap using bleak if device_address is set and mock_mode is False.
    Otherwise, simulates physiological vitals and TCCC stress alerts.
    """
    logger.info(
        "Starting BLE worker (device=%s, mock_mode=%s, interval=%.1fs)",
        device_address,
        mock_mode,
        poll_interval_seconds,
    )
    current_bpm = 74
    spo2 = 98.0

    while not shutdown_event.is_set():
        if mock_mode or not device_address:
            try:
                # Fluctuate heart rate realistically (patrol stress curve)
                current_bpm = min(178, max(60, current_bpm + 2))
                is_stress = current_bpm > 140
                is_tccc_alert = current_bpm > 165

                # Generate and parse standard GATT payload
                raw_bytes = generate_mock_gatt_payload(current_bpm)
                bpm, _ = parse_gatt_heart_rate(raw_bytes)

                if is_tccc_alert:
                    stress_desc = "critical"
                elif is_stress:
                    stress_desc = "elevated"
                else:
                    stress_desc = "nominal"
                event = BiometricEvent(
                    source_id=source_id,
                    timestamp=datetime.now(UTC),
                    heart_rate_bpm=bpm,
                    spo2_percent=spo2,
                    skin_temp_c=36.5,
                    stress_level=stress_desc,
                    tccc_alert=is_tccc_alert,
                )
                await bus.put(event)
                logger.debug("Ingested BLE Biometric: HR=%d, alert=%s", bpm, is_tccc_alert)

                await asyncio.wait_for(shutdown_event.wait(), timeout=poll_interval_seconds)
            except TimeoutError:
                continue
            except Exception as exc:
                logger.error("Error in mock BLE generator: %s", exc)
                await asyncio.sleep(1.0)
        else:
            # Physical bleak connection loop
            try:
                from bleak import BleakClient

                logger.info("Connecting to BLE peripheral %s...", device_address)

                def notification_handler(_sender: Any, data: bytearray) -> None:
                    try:
                        hr, _ = parse_gatt_heart_rate(bytes(data))
                        bio_event = BiometricEvent(
                            source_id=source_id,
                            timestamp=datetime.now(UTC),
                            heart_rate_bpm=hr,
                            spo2_percent=98.0,
                            skin_temp_c=36.5,
                            stress_level="elevated" if hr > 140 else "nominal",
                            tccc_alert=hr > 165,
                        )
                        asyncio.create_task(bus.put(bio_event))
                    except Exception as err:
                        logger.warning("Failed parsing BLE notification: %s", err)

                async with BleakClient(device_address, timeout=10.0) as client:
                    logger.info(
                        "BLE connected to %s; subscribing to HR characteristic...",
                        device_address,
                    )
                    await client.start_notify(HEART_RATE_MEASUREMENT_UUID, notification_handler)

                    while not shutdown_event.is_set() and client.is_connected:
                        await asyncio.sleep(1.0)

                    await client.stop_notify(HEART_RATE_MEASUREMENT_UUID)

            except Exception as exc:
                logger.warning("BLE peripheral connection dropped (%s). Retrying in 5s...", exc)
                await asyncio.sleep(5.0)

    logger.info("BLE worker stopped cleanly.")
