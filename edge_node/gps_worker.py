"""GPS Ingestion Worker.

Reads NMEA sentences asynchronously from serial interfaces (aioserial) or
provides synthetic NMEA streams for development and testing. Converts validated
fixes into LocationEvent objects and publishes them onto the tactical bus.
"""

import asyncio
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from edge_node.models import LocationEvent
from edge_node.nmea_parser import parse_nmea_sentence

if TYPE_CHECKING:
    from edge_node.main import TacticalEventBus

logger = logging.getLogger("edge_node.gps")


def calculate_nmea_checksum(sentence_body: str) -> str:
    """Compute 2-character hex NMEA XOR checksum."""
    c = 0
    for char in sentence_body:
        c ^= ord(char)
    return f"{c:02X}"


def generate_mock_gpgga(lat: float, lon: float, alt: float = 120.5, hdop: float = 1.2) -> str:
    """Generate a valid synthetic $GPGGA sentence with correct checksum."""
    lat_deg = int(abs(lat))
    lat_min = (abs(lat) - lat_deg) * 60.0
    lat_dir = "N" if lat >= 0 else "S"
    lat_str = f"{lat_deg:02d}{lat_min:07.4f}"

    lon_deg = int(abs(lon))
    lon_min = (abs(lon) - lon_deg) * 60.0
    lon_dir = "E" if lon >= 0 else "W"
    lon_str = f"{lon_deg:03d}{lon_min:07.4f}"

    time_str = datetime.now(UTC).strftime("%H%M%S.00")
    # Fix quality: 1 (GPS fix), Satellites: 08
    body = (
        f"GPGGA,{time_str},{lat_str},{lat_dir},{lon_str},{lon_dir},"
        f"1,08,{hdop:.1f},{alt:.1f},M,0.0,M,,"
    )
    checksum = calculate_nmea_checksum(body)
    return f"${body}*{checksum}"


async def run_gps_worker(
    bus: "TacticalEventBus",
    shutdown_event: asyncio.Event,
    port: str | None = None,
    baudrate: int = 9600,
    source_id: str = "kestrel-alpha-01",
    poll_interval_seconds: float = 1.0,
    mock_mode: bool = True,
) -> None:
    """Main GPS ingestion task.

    Attempts serial connection if port is specified and mock_mode is False.
    Falls back gracefully to mock NMEA generation if requested or on connection loss.
    """
    logger.info(
        "Starting GPS worker (port=%s, mock_mode=%s, interval=%.1fs)",
        port,
        mock_mode,
        poll_interval_seconds,
    )
    sim_lat = 52.229712
    sim_lon = 21.012234

    while not shutdown_event.is_set():
        if mock_mode or not port:
            try:
                # Advance simulated coordinates (patrol route)
                sim_lat += 0.00003
                sim_lon += 0.00002

                nmea_str = generate_mock_gpgga(sim_lat, sim_lon, alt=135.0, hdop=1.1)
                parsed = parse_nmea_sentence(nmea_str)
                if parsed:
                    event = LocationEvent(
                        source_id=source_id,
                        timestamp=parsed.timestamp,
                        latitude=parsed.latitude,
                        longitude=parsed.longitude,
                        altitude_m=parsed.altitude_m,
                        circular_error_m=parsed.circular_error_m,
                        linear_error_m=round(parsed.circular_error_m * 1.5, 2),
                        speed_mps=1.35,
                        heading_deg=45.0,
                    )
                    await bus.put(event)
                    logger.debug(
                        "Ingested GPS fix: %f, %f (CE: %.1fm)",
                        sim_lat,
                        sim_lon,
                        parsed.circular_error_m,
                    )

                await asyncio.wait_for(shutdown_event.wait(), timeout=poll_interval_seconds)
            except TimeoutError:
                continue
            except Exception as exc:
                logger.error("Error in mock GPS generator: %s", exc)
                await asyncio.sleep(1.0)
        else:
            # Physical aioserial connection loop
            try:
                import aioserial  # Lazy import for hardware serial access

                logger.info("Opening serial port %s at %d baud...", port, baudrate)
                async with aioserial.AioSerial(
                    port=port,
                    baudrate=baudrate,
                    timeout=2.0,
                ) as serial_conn:
                    while not shutdown_event.is_set():
                        raw_line = await serial_conn.readline_async()
                        line = raw_line.decode("ascii", errors="replace").strip()
                        if line.startswith("$"):
                            parsed = parse_nmea_sentence(line)
                            if parsed:
                                event = LocationEvent(
                                    source_id=source_id,
                                    timestamp=parsed.timestamp,
                                    latitude=parsed.latitude,
                                    longitude=parsed.longitude,
                                    altitude_m=parsed.altitude_m,
                                    circular_error_m=parsed.circular_error_m,
                                    linear_error_m=round(parsed.circular_error_m * 1.5, 2),
                                    speed_mps=parsed.speed_mps,
                                    heading_deg=parsed.heading_deg,
                                )
                                await bus.put(event)
            except Exception as exc:
                logger.warning("GPS serial error on %s: %s. Reconnecting in 3s...", port, exc)
                await asyncio.sleep(3.0)

    logger.info("GPS worker stopped cleanly.")
