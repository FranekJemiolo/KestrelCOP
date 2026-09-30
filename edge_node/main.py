"""KestrelCOP Edge Node Main Daemon.

Integrates:
  - Asynchronous GPS NMEA ingestion (aioserial / mock parser)
  - Asynchronous BLE Biometrics ingestion (bleak / mock GATT parser)
  - Isolated Multiprocessing ML Drone Vision inference (cv2 + onnxruntime)
  - Resilient Cursor-on-Target serialization and MQTT mesh publisher (aiomqtt)
"""

import argparse
import asyncio
import logging
import os
import signal
import sys

from edge_node.ble_worker import run_ble_worker
from edge_node.gps_worker import run_gps_worker
from edge_node.ml_worker import TacticalMlPipeline
from edge_node.models import TelemetryEvent
from edge_node.publisher import MqttTacticalPublisher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("edge_node")


class TacticalEventBus:
    """Bounded in-memory event bus decoupling multi-sensor ingestion from network broadcast."""

    def __init__(self, maxsize: int = 500) -> None:
        self.queue: asyncio.Queue[TelemetryEvent] = asyncio.Queue(maxsize=maxsize)
        self.dropped_count: int = 0

    async def put(self, event: TelemetryEvent) -> None:
        """Enqueue an event; if full, drops oldest to preserve fresh tactical state."""
        if self.queue.full():
            try:
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

    def get_nowait(self) -> TelemetryEvent:
        """Retrieve next event without awaiting."""
        return self.queue.get_nowait()

    def task_done(self) -> None:
        """Mark event task as done."""
        self.queue.task_done()

    @property
    def qsize(self) -> int:
        return self.queue.qsize()


async def run_edge_node(
    broker_host: str = "127.0.0.1",
    broker_port: int = 1883,
    mock_mode: bool = True,
    duration_seconds: float | None = None,
    serial_port: str | None = None,
    ble_address: str | None = None,
    video_source: str | int | None = None,
    model_path: str | None = None,
) -> None:
    """Launch and manage the complete KestrelCOP Edge Node lifecycle."""
    logger.info("Initializing KestrelCOP Tactical Edge Node [v0.1.0]...")
    logger.info(
        "Config: mock_mode=%s, broker=%s:%d, video_source=%s",
        mock_mode,
        broker_host,
        broker_port,
        video_source or "synthetic",
    )

    bus = TacticalEventBus(maxsize=500)
    shutdown_event = asyncio.Event()

    loop = asyncio.get_running_loop()

    def signal_handler() -> None:
        logger.info("Received termination signal; initiating graceful tactical shutdown...")
        shutdown_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, signal_handler)
        except NotImplementedError:
            pass

    # 1. Initialize and launch isolated Multiprocessing ML Pipeline
    ml_pipeline = TacticalMlPipeline(
        bus=bus,
        video_source=video_source,
        model_path=model_path,
        source_id="kestrel-drone-overwatch",
        fps_limit=2.0,
    )
    ml_pipeline.start()

    # 2. Initialize Tactical MQTT Publisher
    publisher = MqttTacticalPublisher(
        broker_host=broker_host,
        broker_port=broker_port,
        topic_prefix="tactical/kestrel",
        buffer_max_size=1000,
    )

    # 3. Assemble concurrent asynchronous worker tasks
    tasks = [
        asyncio.create_task(
            run_gps_worker(
                bus=bus,
                shutdown_event=shutdown_event,
                port=serial_port,
                source_id="kestrel-alpha-01",
                poll_interval_seconds=1.0,
                mock_mode=mock_mode,
            ),
            name="GPSWorker",
        ),
        asyncio.create_task(
            run_ble_worker(
                bus=bus,
                shutdown_event=shutdown_event,
                device_address=ble_address,
                source_id="kestrel-alpha-01",
                poll_interval_seconds=2.0,
                mock_mode=mock_mode,
            ),
            name="BLEWorker",
        ),
        asyncio.create_task(
            ml_pipeline.run_async_bridge(shutdown_event),
            name="MLBridge",
        ),
        asyncio.create_task(
            publisher.run(bus=bus, shutdown_event=shutdown_event, mock_publish=mock_mode),
            name="MQTTPublisher",
        ),
    ]

    try:
        if duration_seconds is not None:
            logger.info("Running for specified duration: %.1f seconds...", duration_seconds)
            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=duration_seconds)
            except TimeoutError:
                logger.info("Duration elapsed; triggering shutdown...")
                shutdown_event.set()
        else:
            await shutdown_event.wait()

    finally:
        logger.info("Stopping all edge node tasks...")
        shutdown_event.set()

        # Stop isolated ML subprocess first
        ml_pipeline.stop()

        # Await completion of all async tasks
        await asyncio.gather(*tasks, return_exceptions=True)
        logger.info(
            "Edge node stopped. Published: %d, buffered: %d, stale dropped: %d",
            publisher.messages_published,
            publisher.messages_buffered,
            publisher.stale_dropped_count,
        )


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="KestrelCOP Tactical Edge Node Daemon")
    parser.add_argument(
        "--mock",
        action="store_true",
        default=os.getenv("KESTREL_MOCK_MODE", "true").lower() in ("true", "1", "yes"),
        help="Run in mock/simulation mode (no physical hardware required)",
    )
    parser.add_argument(
        "--broker-host",
        default=os.getenv("KESTREL_BROKER_HOST", "127.0.0.1"),
        help="MQTT broker host address",
    )
    parser.add_argument(
        "--broker-port",
        type=int,
        default=int(os.getenv("KESTREL_BROKER_PORT", "1883")),
        help="MQTT broker port number",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=None,
        help="Optional runtime duration in seconds",
    )
    parser.add_argument(
        "--serial-port",
        default=os.getenv("KESTREL_SERIAL_PORT", None),
        help="Serial port for GPS receiver (e.g., /dev/ttyUSB0)",
    )
    parser.add_argument(
        "--ble-address",
        default=os.getenv("KESTREL_BLE_ADDRESS", None),
        help="Bluetooth MAC or UUID of heart rate sensor",
    )
    parser.add_argument(
        "--video-source",
        default=os.getenv("KESTREL_VIDEO_SOURCE", None),
        help="Path to test MP4 video file or RTSP stream URL",
    )
    return parser.parse_args()


def main() -> None:
    """Command line entrypoint."""
    args = parse_args()
    try:
        asyncio.run(
            run_edge_node(
                broker_host=args.broker_host,
                broker_port=args.broker_port,
                mock_mode=args.mock,
                duration_seconds=args.duration,
                serial_port=args.serial_port,
                ble_address=args.ble_address,
                video_source=args.video_source,
            )
        )
    except KeyboardInterrupt:
        logger.info("Terminated by keyboard interrupt.")
        sys.exit(0)


if __name__ == "__main__":
    main()
