"""Tactical MQTT Publisher with Offline Resilient Buffering.

Manages connection to local or MANET Eclipse Mosquitto broker via aiomqtt.
Implements bounded collections.deque offline buffering when RF link is lost,
and aggressively enforces stale-data expiration upon link reconnection so
obsolete tracks never saturate restored tactical bandwidth.
"""

import asyncio
import json
import logging
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from edge_node.cot_mapper import telemetry_to_cot_dict
from edge_node.models import BiometricEvent, DetectionEvent, LocationEvent, TelemetryEvent

if TYPE_CHECKING:
    from edge_node.main import TacticalEventBus

logger = logging.getLogger("edge_node.publisher")


@dataclass(frozen=True)
class BufferedCoTPayload:
    """CoT payload stored in offline buffer with expiration metadata."""

    payload_json: str
    topic: str
    qos: int
    stale_time: datetime
    event_type: str
    source_id: str


class MqttTacticalPublisher:
    """Asynchronous MQTT publisher with bounded offline buffer and stale track pruning."""

    def __init__(
        self,
        broker_host: str = "127.0.0.1",
        broker_port: int = 1883,
        topic_prefix: str = "tactical/kestrel",
        buffer_max_size: int = 1000,
        reconnect_interval_seconds: float = 3.0,
    ) -> None:
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.topic_prefix = topic_prefix
        self.reconnect_interval = reconnect_interval_seconds

        # Bounded ring buffer for DIL environments
        self.offline_buffer: deque[BufferedCoTPayload] = deque(maxlen=buffer_max_size)

        # Operational telemetry counters
        self.messages_published: int = 0
        self.messages_buffered: int = 0
        self.stale_dropped_count: int = 0
        self.reconnect_count: int = 0
        self.is_connected: bool = False

    def package_event(
        self,
        event: TelemetryEvent,
        last_known_loc: LocationEvent | None = None,
        stale_duration: float = 30.0,
    ) -> BufferedCoTPayload:
        """Serialize event to CoT and construct buffered packet."""
        cot_dict = telemetry_to_cot_dict(
            event=event,
            last_known_location=last_known_loc,
            stale_duration_seconds=stale_duration,
        )
        payload_str = json.dumps(cot_dict)
        stale_iso = cot_dict["event"]["stale"]

        # Parse stale ISO string into UTC datetime
        try:
            stale_time = datetime.fromisoformat(stale_iso.replace("Z", "+00:00"))
        except ValueError:
            stale_time = datetime.now(UTC)

        # Tactical QoS policy: Life-safety alerts (TCCC) or high-priority detections use QoS 1
        qos = 0
        if isinstance(event, BiometricEvent) and event.tccc_alert:
            qos = 1
        elif isinstance(event, DetectionEvent) and event.confidence > 0.85:
            qos = 1

        topic = f"{self.topic_prefix}/{event.source_id}/cot"

        return BufferedCoTPayload(
            payload_json=payload_str,
            topic=topic,
            qos=qos,
            stale_time=stale_time,
            event_type=type(event).__name__,
            source_id=event.source_id,
        )

    async def _flush_offline_buffer(self, client: Any) -> int:
        """Flush unsent events across restored link, pruning stale data."""
        flushed_count = 0
        now = datetime.now(UTC)

        while self.offline_buffer:
            packet = self.offline_buffer.popleft()

            # Enforce stale data expiration
            if now > packet.stale_time:
                self.stale_dropped_count += 1
                logger.warning(
                    "PRUNED STALE TELEMETRY: %s for %s expired at %s (Total dropped: %d)",
                    packet.event_type,
                    packet.source_id,
                    packet.stale_time.isoformat(),
                    self.stale_dropped_count,
                )
                continue

            # Publish valid fresh buffered packet
            await client.publish(packet.topic, payload=packet.payload_json, qos=packet.qos)
            self.messages_published += 1
            flushed_count += 1

        return flushed_count

    async def run(
        self,
        bus: "TacticalEventBus",
        shutdown_event: asyncio.Event,
        mock_publish: bool = False,
    ) -> None:
        """Main publisher task draining TacticalEventBus and transmitting to broker."""
        logger.info(
            "Tactical MQTT Publisher active (target: %s:%d, mock=%s)",
            self.broker_host,
            self.broker_port,
            mock_publish,
        )
        last_known_location: LocationEvent | None = None

        while not shutdown_event.is_set() or bus.qsize > 0:
            if mock_publish:
                # Local mock mode (prints and verifies CoT serialization without live broker)
                try:
                    event = await asyncio.wait_for(bus.get(), timeout=1.0)
                except TimeoutError:
                    continue

                if isinstance(event, LocationEvent):
                    last_known_location = event

                packet = self.package_event(event, last_known_loc=last_known_location)
                bus.task_done()
                self.messages_published += 1
                logger.info(
                    "[MOCK-MQTT] Published %s -> %s (QoS %d, pub count: %d)",
                    packet.event_type,
                    packet.topic,
                    packet.qos,
                    self.messages_published,
                )
                continue

            # Live aiomqtt connection loop
            try:
                import aiomqtt

                self.reconnect_count += 1
                logger.info(
                    "Attempting MQTT connection to %s:%d (attempt #%d)...",
                    self.broker_host,
                    self.broker_port,
                    self.reconnect_count,
                )

                async with aiomqtt.Client(
                    hostname=self.broker_host,
                    port=self.broker_port,
                ) as client:
                    self.is_connected = True
                    logger.info(
                        "Connected to tactical MQTT broker at %s:%d",
                        self.broker_host,
                        self.broker_port,
                    )

                    # Flush any offline buffered packets first
                    flushed = await self._flush_offline_buffer(client)
                    if flushed > 0:
                        logger.info("Flushed %d telemetry packets from offline buffer.", flushed)

                    while not shutdown_event.is_set() or bus.qsize > 0:
                        try:
                            event = await asyncio.wait_for(bus.get(), timeout=1.0)
                        except TimeoutError:
                            continue

                        if isinstance(event, LocationEvent):
                            last_known_location = event

                        packet = self.package_event(event, last_known_loc=last_known_location)
                        bus.task_done()

                        # Publish to broker
                        await client.publish(
                            packet.topic,
                            payload=packet.payload_json,
                            qos=packet.qos,
                        )
                        self.messages_published += 1
                        logger.debug("PUBLISHED [MQTT]: %s -> %s", packet.event_type, packet.topic)

            except (aiomqtt.MqttError, OSError, TimeoutError) as net_err:
                self.is_connected = False
                logger.warning(
                    "Tactical link disconnected (%s). Diverting to offline ring buffer...",
                    net_err,
                )

                # Drain available items from bus into offline buffer
                while bus.qsize > 0:
                    try:
                        event = bus.get_nowait()
                        if isinstance(event, LocationEvent):
                            last_known_location = event

                        packet = self.package_event(event, last_known_loc=last_known_location)
                        bus.task_done()
                        self.offline_buffer.append(packet)
                        self.messages_buffered += 1
                    except asyncio.QueueEmpty:
                        break

                await asyncio.sleep(self.reconnect_interval)

            except Exception as unk_err:
                logger.error("Unexpected error in MQTT publisher loop: %s", unk_err)
                await asyncio.sleep(self.reconnect_interval)

        logger.info("Tactical MQTT Publisher halted cleanly.")
