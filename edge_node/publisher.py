"""Tactical MQTT Publisher with Offline Resilient Buffering.

Manages connection to local or MANET Eclipse Mosquitto broker via aiomqtt.
Implements bounded collections.deque offline buffering when RF link is lost,
and aggressively enforces stale-data expiration upon link reconnection so
obsolete tracks never saturate restored tactical bandwidth.
"""

import asyncio
import json
import logging
import random
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
    """Asynchronous MQTT publisher with exponential backoff and offline buffering."""

    def __init__(
        self,
        broker_host: str = "127.0.0.1",
        broker_port: int = 1883,
        topic_prefix: str = "tactical/kestrel",
        buffer_max_size: int = 1000,
        reconnect_interval_seconds: float = 1.0,
        max_reconnect_interval_seconds: float = 30.0,
        backoff_factor: float = 2.0,
        jitter_ratio: float = 0.1,
    ) -> None:
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.topic_prefix = topic_prefix

        # Exponential backoff parameters
        self.initial_backoff = reconnect_interval_seconds
        self.max_backoff = max_reconnect_interval_seconds
        self.backoff_factor = backoff_factor
        self.jitter_ratio = jitter_ratio
        self.current_backoff = self.initial_backoff

        # Bounded ring buffer for DIL environments
        self.offline_buffer: deque[BufferedCoTPayload] = deque(maxlen=buffer_max_size)

        # Operational telemetry counters
        self.messages_published: int = 0
        self.messages_buffered: int = 0
        self.stale_dropped_count: int = 0
        self.reconnect_count: int = 0
        self.is_connected: bool = False

    @property
    def reconnect_interval(self) -> float:
        """Current backoff interval in seconds."""
        return self.current_backoff

    @reconnect_interval.setter
    def reconnect_interval(self, value: float) -> None:
        self.initial_backoff = value
        self.current_backoff = value

    def calculate_backoff(self) -> float:
        """Compute the next exponential backoff delay with random jitter."""
        jitter = 1.0 + random.uniform(-self.jitter_ratio, self.jitter_ratio)
        delay = min(self.max_backoff, self.current_backoff * jitter)
        # Advance exponential backoff for subsequent failures
        self.current_backoff = min(self.max_backoff, self.current_backoff * self.backoff_factor)
        return max(0.1, delay)

    def reset_backoff(self) -> None:
        """Reset exponential backoff delay back to initial value upon successful connection."""
        self.current_backoff = self.initial_backoff

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
                    self.reset_backoff()
                    logger.info(
                        "Connected to tactical MQTT broker at %s:%d (backoff reset to %.1fs)",
                        self.broker_host,
                        self.broker_port,
                        self.initial_backoff,
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
                backoff_delay = self.calculate_backoff()
                logger.warning(
                    "Link down (%s). Backing off %.2fs (next base: %.2fs). Buffering offline...",
                    net_err,
                    backoff_delay,
                    self.current_backoff,
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

                await asyncio.sleep(backoff_delay)

            except Exception as unk_err:
                self.is_connected = False
                backoff_delay = self.calculate_backoff()
                logger.error(
                    "Unexpected error in MQTT publisher loop: %s. Backing off for %.2fs...",
                    unk_err,
                    backoff_delay,
                )
                await asyncio.sleep(backoff_delay)

        logger.info("Tactical MQTT Publisher halted cleanly.")
