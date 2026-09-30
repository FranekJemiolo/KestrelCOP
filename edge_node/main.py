"""KestrelCOP Edge Node Main Daemon.

Scaffolds the central asynchronous event bus (asyncio.Queue), sensor producers,
and the Cursor-on-Target serialization consumer.
"""

import asyncio
import logging
import signal
import sys
from collections import deque
from datetime import UTC, datetime

from edge_node.cot_mapper import telemetry_to_cot_json
from edge_node.models import (
    BiometricEvent,
    DetectionEvent,
    LocationEvent,
    TelemetryEvent,
)

# Configure structured tactical logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("edge_node")


class TacticalEventBus:
    """Bounded in-memory event bus decoupling ingestion from transmission."""

    def __init__(self, maxsize: int = 500) -> None:
        self.queue: asyncio.Queue[TelemetryEvent] = asyncio.Queue(maxsize=maxsize)
        self.dropped_count: int = 0

    async def put(self, event: TelemetryEvent) -> None:
        """Enqueue an event; if full, drops oldest to preserve fresh state."""
        if self.queue.full():
            try:
                # Evict oldest item to ensure freshest telemetry takes precedence
                _ = self.queue.get_nowait()
                self.queue.task_done()
                self.dropped_count += 1
                logger.warning(
                    "Tactical event queue saturated; evicted stale event (total dropped: %d)",
                    self.dropped_count,
                )
            except asyncio.QueueEmpty:
                pass

        await self.queue.put(event)

    async def get(self) -> TelemetryEvent:
        """Retrieve the next telemetry event."""
        return await self.queue.get()

    def task_done(self) -> None:
        """Mark event task as done."""
        self.queue.task_done()

    @property
    def qsize(self) -> int:
        return self.queue.qsize()


async def mock_gps_producer(
    bus: TacticalEventBus,
    shutdown_event: asyncio.Event,
    interval_seconds: float = 2.0,
) -> None:
    """Simulate asynchronous UART NMEA GPS ingestion (aioserial worker placeholder)."""
    logger.info("GPS Ingestion Worker initialized (target: 0.5 Hz)")
    lat, lon = 52.2297, 21.0122

    while not shutdown_event.is_set():
        try:
            # Simulate slight tactical troop displacement
            lat += 0.00005
            lon += 0.00003

            event = LocationEvent(
                source_id="kestrel-alpha-01",
                timestamp=datetime.now(UTC),
                latitude=lat,
                longitude=lon,
                altitude_m=135.2,
                circular_error_m=1.8,
                speed_mps=1.4,
                heading_deg=45.0,
            )
            await bus.put(event)
            logger.debug("Emitted LocationEvent: lat=%.6f, lon=%.6f", lat, lon)

            await asyncio.wait_for(shutdown_event.wait(), timeout=interval_seconds)
        except TimeoutError:
            continue
        except Exception as exc:
            logger.error("Error in GPS ingestion worker: %s", exc)

    logger.info("GPS Ingestion Worker terminated cleanly.")


async def mock_biometrics_producer(
    bus: TacticalEventBus,
    shutdown_event: asyncio.Event,
    interval_seconds: float = 3.5,
) -> None:
    """Simulate asynchronous BLE Heart Rate ingestion (bleak worker placeholder)."""
    logger.info("BLE Biometric Worker initialized")
    current_hr = 78

    while not shutdown_event.is_set():
        try:
            # Fluctuate heart rate slightly
            current_hr = min(175, max(65, current_hr + 2))
            is_alert = current_hr > 150

            event = BiometricEvent(
                source_id="kestrel-alpha-01",
                timestamp=datetime.now(UTC),
                heart_rate_bpm=current_hr,
                spo2_percent=98.5,
                skin_temp_c=36.4,
                stress_level="nominal" if not is_alert else "elevated",
                tccc_alert=is_alert,
            )
            await bus.put(event)
            logger.debug("Emitted BiometricEvent: HR=%d bpm", current_hr)

            await asyncio.wait_for(shutdown_event.wait(), timeout=interval_seconds)
        except TimeoutError:
            continue
        except Exception as exc:
            logger.error("Error in Biometric worker: %s", exc)

    logger.info("BLE Biometric Worker terminated cleanly.")


async def mock_detection_producer(
    bus: TacticalEventBus,
    shutdown_event: asyncio.Event,
    interval_seconds: float = 5.0,
) -> None:
    """Simulate computer vision detections bridging from multiprocessing ML process."""
    logger.info("YOLO/ONNX IPC Receiver Worker initialized")

    while not shutdown_event.is_set():
        try:
            event = DetectionEvent(
                source_id="kestrel-drone-overwatch",
                timestamp=datetime.now(UTC),
                label="armored_recon_vehicle",
                confidence=0.935,
                bbox=(0.25, 0.35, 0.65, 0.75),
                bearing_deg=132.5,
                range_m=340.0,
                estimated_lat=52.2341,
                estimated_lon=21.0198,
            )
            await bus.put(event)
            logger.debug("Emitted DetectionEvent: %s (conf: %.2f)", event.label, event.confidence)

            await asyncio.wait_for(shutdown_event.wait(), timeout=interval_seconds)
        except TimeoutError:
            continue
        except Exception as exc:
            logger.error("Error in Detection receiver worker: %s", exc)

    logger.info("YOLO/ONNX IPC Receiver Worker terminated cleanly.")


async def cot_assembly_consumer(
    bus: TacticalEventBus,
    shutdown_event: asyncio.Event,
) -> None:
    """Consume events from the bus, serialize into CoT JSON, and simulate MQTT broadcast."""
    logger.info("Cursor-on-Target (CoT) Assembler & Publisher Consumer initialized")
    last_known_location: LocationEvent | None = None
    recent_events_buffer: deque[str] = deque(maxlen=100)

    while not shutdown_event.is_set() or bus.qsize > 0:
        try:
            try:
                event = await asyncio.wait_for(bus.get(), timeout=1.0)
            except TimeoutError:
                continue

            if isinstance(event, LocationEvent):
                last_known_location = event

            # Transform into CoT JSON
            cot_json = telemetry_to_cot_json(
                event=event,
                last_known_location=last_known_location,
                stale_duration_seconds=30.0,
            )

            recent_events_buffer.append(cot_json)
            bus.task_done()

            # Mock transmission log (simulating MQTT publish to tactical mesh)
            event_type = type(event).__name__
            logger.info(
                "TRANSMIT [CoT]: %s for %s (Queue remaining: %d)",
                event_type,
                event.source_id,
                bus.qsize,
            )

        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.error("Error during CoT serialization/broadcast: %s", exc)

    logger.info("CoT Assembler Consumer drained remaining events and stopped.")


async def run_edge_node(max_iterations: int | None = None) -> None:
    """Run the edge node application loop.

    Args:
        max_iterations: Optional cutoff for testing or benchmarks.
    """
    logger.info("Starting KestrelCOP Tactical Edge Node v0.1.0...")

    bus = TacticalEventBus(maxsize=100)
    shutdown_event = asyncio.Event()

    loop = asyncio.get_running_loop()

    def handle_signal() -> None:
        logger.info("Received termination signal; initiating graceful tactical shutdown...")
        shutdown_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, handle_signal)
        except NotImplementedError:
            # Fallback for environments without signal handler support (e.g. Windows)
            pass

    # Launch background worker tasks
    producer_tasks = [
        asyncio.create_task(mock_gps_producer(bus, shutdown_event)),
        asyncio.create_task(mock_biometrics_producer(bus, shutdown_event)),
        asyncio.create_task(mock_detection_producer(bus, shutdown_event)),
    ]
    consumer_task = asyncio.create_task(cot_assembly_consumer(bus, shutdown_event))

    if max_iterations is not None:
        # If running in benchmark/limited mode
        await asyncio.sleep(max_iterations)
        shutdown_event.set()

    # Await until shutdown signal is triggered
    await shutdown_event.wait()
    logger.info("Stopping producer tasks...")

    # Wait for producers to exit
    await asyncio.gather(*producer_tasks, return_exceptions=True)

    # Wait for consumer to drain remaining events
    await consumer_task
    logger.info("KestrelCOP Edge Node shutdown complete.")


def main() -> None:
    """Entry point for command line invocation."""
    try:
        asyncio.run(run_edge_node())
    except KeyboardInterrupt:
        logger.info("Process halted by operator keyboard interrupt.")
        sys.exit(0)


if __name__ == "__main__":
    main()
