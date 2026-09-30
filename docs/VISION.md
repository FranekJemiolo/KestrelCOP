# Project KestrelCOP: Commander's Intent & Architectural Vision

> **Tactical Edge Telemetry Pipeline & Common Operating Picture (COP)**
> *Offline-First • Zero-Vendor-Lockin • Dual-Use COTS Hardware • Open Standards*

---

## 1. Executive Summary & Intent

Modern military conflict and disaster-response operations have shifted decisively away from multi-billion-dollar monolithic defense programs toward **attritable, software-defined, commercial off-the-shelf (COTS) mass**. However, tactical operators, dismounted teams, and field commanders remain shackled to fragile, proprietary, and exorbitantly priced communications infrastructure.

When units operate in **contested, degraded, and Disconnected, Intermittent, and Low-bandwidth (DIL)** environments:
- Proprietary cloud-connected command platforms (AWS GovCloud, Azure Government, Datadog, Palantir) are rendered useless by electronic warfare, GPS jamming, and physical backhaul severance.
- Legacy defense systems rely on bulky, fragile proprietary hardware terminals with licensing walls and rigid update cycles.
- High-bandwidth sensor feeds (RTSP video from micro-UAVs, RF spectrum captures, multi-point acoustic signals) saturate scarce tactical tactical radio spectrum.

**KestrelCOP** is engineered to eliminate these vulnerabilities. It is an autonomous, fully local, open-source Tactical Common Operating Picture and telemetry pipeline designed to run on low-power COTS edge computers (Raspberry Pi 5, NVIDIA Jetson Orin Nano, ruggedized Android EUDs) and air-gapped local clusters.

```
                              ┌─────────────────────────────────────────────────────────┐
                              │                    OPERATIONAL THEATER                  │
                              └─────────────────────────────────────────────────────────┘
                                                           │
        ┌──────────────────────────────────────────────────┴──────────────────────────────────────────────────┐
        ▼                                                  ▼                                                  ▼
 ╔═════════════════════════════╗                    ╔═════════════════════════════╗                    ╔═════════════════════════════╗
 ║     TIER 1: EDGE NODE       ║                    ║     TIER 2: TRANSPORT       ║                    ║    TIER 3 & 4: COLLECTOR    ║
 ║  • Asynchronous GPS/NMEA    ║    MANET Mesh      ║  • Eclipse Mosquitto (MQTT) ║   High-Throughput  ║  • Strimzi Apache Kafka     ║
 ║  • BLE Tactical Biometrics  ║  ◄───────────────► ║  • Topic-based Sharding     ║  ◄───────────────► ║  • PostgreSQL / PostGIS     ║
 ║  • Isolated YOLOv8 / ONNX   ║    QoS 0 / QoS 1   ║  • Offline Bounded Buffers  ║    Event Ingest    ║  • MapLibre GL JS PWA       ║
 ║  • CoT JSON Normalization   ║                    ║  • Vector Telemetry Router  ║                    ║  • PMTiles Offline Maps     ║
 ╚═════════════════════════════╝                    ╚═════════════════════════════╝                    ╚═════════════════════════════╝
```

---

## 2. Core Architectural Tiers

KestrelCOP enforces strict physical and logical boundaries between four operational tiers:

### Tier 1: The Tactical Edge Node (End User Device / EUD)
The Edge Node operates directly in the operator's kit (e.g., chest-mounted ruggedized unit or payload computer on a micro-drone).
- **Hybrid Concurrency Model:** To overcome CPython GIL limitations during real-time multi-sensor ingestion, I/O-bound sensor workers (GPS serial UART via `aioserial`, BLE GATT biometrics via `bleak`) run on an asynchronous event loop (`asyncio`), while CPU-intensive computer vision inference (RTSP video capture via `OpenCV` and YOLO object detection via `onnxruntime`) executes in an isolated `multiprocessing.Process`.
- **Zero Raw Video Over the Air:** Constrained tactical links cannot sustain 1080p RTSP streaming. Tier 1 executes edge intelligence locally, extracting target bounding boxes, classifications, and estimated coordinates, transmitting only lightweight semantic events.
- **Normalization to Cursor-on-Target (CoT):** All sensor telemetry is mapped into the open Cursor-on-Target schema (standardized JSON/XML answering *Who/What*, *Where*, and *When*), enabling native interoperability with the wider TAK (ATAK/WinTAK/iTAK) ecosystem.

### Tier 2: The Tactical Mesh Transport Layer (MANET Radio Emulation)
Tactical networks are inherently volatile peer-to-peer radio meshes (e.g., Silvus, TrellisWare, Doodle Labs, or LoRa/Meshtastic mesh).
- **Eclipse Mosquitto (MQTT over TCP/UDP):** Provides lightweight pub/sub routing with Quality of Service tiers:
  - `QoS 0` (At most once / fire-and-forget): High-frequency telemetry such as continuous GPS position tracks and raw heart-rate ticks.
  - `QoS 1` (At least once / verified receipt): Critical events including casualty alerts (TCCC), enemy contact detections, and target designations.
- **Topic Sharding:** Telemetry is geographically and hierarchically partitioned (e.g., `tactical/{squad_id}/telemetry/{sensor_type}`) preventing channel saturation.
- **Bounded Ring Buffering:** When entering RF-denied zones (bunkers, tunnels, active jamming), an in-memory ring buffer (`collections.deque(maxlen=1000)`) buffers unsent telemetry, dropping the oldest non-critical tracking data to guarantee that when RF link returns, the freshest tactical state is transmitted first.

### Tier 3: The Command Collector Backend
The central state coordinator situated at a Company/Battalion Tactical Operations Center (TOC) or inside a mobile command vehicle.
- **Single-Binary Edge Kubernetes (`k3s`):** Runs on ruggedized x86/ARM edge servers without external dependencies or cloud connectivity.
- **Immutable Battlefield Log (Apache Kafka via Strimzi Operator):** Every CoT message arriving from the field is committed to an append-only distributed log. Multiple analytical consumers (threat triangulation, predictive logistics, tactical replay) consume this log concurrently without blocking real-time ingestion.
- **Geospatial & Time-Series Storage (PostgreSQL + PostGIS):** Persists full operational history, tactical geofences, and spatial indices for fast range/bounding-box spatial queries.

### Tier 4: The Commander's Dashboard (Tactical Web COP)
- **Zero-Install Progressive Web App (PWA):** Built using React and TypeScript, fully responsive for ruggedized tablets and TOC tactical multi-monitors. Installable directly to home screens without app store reliance.
- **Offline Mapping via MapLibre GL JS & PMTiles:** Complete vector mapping capability independent of external tile servers. OpenStreetMap vector tiles for entire operational areas are stored in a single PMTiles archive served directly from the local collector or cached client-side in IndexedDB.
- **Sub-16ms Real-Time Visualization:** Live entities are streamed over WebSockets and rendered via WebGL at 60 FPS, with distinct tactical symbology (MIL-STD-2525D / APP-6 compatible friendly, hostile, neutral, and unknown designations).

---

## 3. Operational Intent & Milestone Validation Matrix

To prevent architectural drift and guarantee operational readiness under combat conditions, every system milestone satisfies an unambiguous **Commander's Intent** verified against explicit acceptance criteria:

| Milestone | Component | Tactical Intent | Definitive Acceptance Test |
| :--- | :--- | :--- | :--- |
| **M1** | Schemas & Event Bus | **Data Integrity:** Prevent corrupted sensor packets from crashing the node or contaminating the COP. | Inject truncated, malformed, and out-of-spec NMEA/JSON telemetry at 1,000 pkts/sec. Node must reject corrupt records, log a single structured warning, and maintain the main loop without interruption. |
| **M2** | Asynchronous GPS & BLE | **Continuous Awareness:** Maintain operator position and vital metrics despite physical connection volatility. | Sever physical USB GPS antenna and disable BLE wearable for 5 minutes during live operation. Reconnect hardware. Software must restore live CoT streaming within < 3 seconds without manual intervention. |
| **M3** | Isolated ML Pipeline | **Edge Intelligence without Latency:** Extract detections from video feeds without throttling life-safety telemetry. | Saturate drone video inference process to 100% CPU load. Trigger simulated operator heart rate anomaly. Biometric alert must reach event bus in < 15ms, proving zero GIL or event loop starvation. |
| **M4** | Tactical Network Link | **DIL Network Resilience:** Survive prolonged RF disconnects without flooding restored bandwidth with stale data. | Sever MQTT broker connection for 10 minutes while sensors continue firing. Reconnect link. Edge node must immediately transmit latest coordinates and critical detections first; stale tracks (>30s old) are discarded. |
| **M5** | Edge Observability | **Field Deployability:** Zero-touch operational capability deployable by field operators, not DevOps engineers. | Cold boot entire edge node container stack on a Raspberry Pi 5 with Wi-Fi disabled via a single command (`docker compose up -d`). System must reach green operational state in < 15 seconds. |
| **M6** | Command Collector | **Immutable Source of Truth:** Zero loss of battlefield events during multi-squad contact bursts. | Stream 10,000 CoT payloads/second against ingestion endpoint. All messages must be validated and written to Kafka topic with zero packet loss and sub-10ms write latency. |
| **M7** | Tactical Web Dashboard | **Zero-Friction Command:** Instantaneous geospatial situational awareness with zero external dependencies. | Disconnect client device from local network. Dashboard must continue panning/zooming cached vector tiles smoothly. Re-establish Wi-Fi; WebSockets must reconnect within 500ms and reconcile entity states. |
| **M8** | Strategic Sync | **Post-Mission Forensic Audit:** Reconcile edge mission history with command archives once wide-area backhaul is established. | Disconnect TOC collector for 24 hours while field operations proceed. Connect high-bandwidth satellite uplink. Historical events must stream to permanent storage without stalling live tactical operations. |

---

## 4. Cursor-on-Target (CoT) Data Standard

KestrelCOP adheres to the **Cursor-on-Target** standard (JSON profile), facilitating native cross-platform interop:

```json
{
  "event": {
    "version": "2.0",
    "uid": "kestrel-bravo-02",
    "type": "a-f-G-U-C",
    "time": "2026-09-30T14:35:00.000Z",
    "start": "2026-09-30T14:35:00.000Z",
    "stale": "2026-09-30T14:35:30.000Z",
    "how": "m-g",
    "point": {
      "lat": 52.229712,
      "lon": 21.012234,
      "hae": 142.5,
      "ce": 3.2,
      "le": 4.1
    },
    "detail": {
      "contact": {
        "callsign": "BRAVO-2",
        "endpoint": "192.168.10.45:4242"
      },
      "biometrics": {
        "heart_rate_bpm": 142,
        "spo2_percent": 97,
        "stress_indicator": "elevated"
      },
      "sensor_payload": {
        "detection_class": "unmanned_aerial_vehicle",
        "confidence": 0.94,
        "bearing_deg": 128.4
      }
    }
  }
}
```

---

## 5. Technology Stack Summary (100% Free & Open Source)

| Component | Selected Technology | Licensing | Rationale |
| :--- | :--- | :--- | :--- |
| **Edge Language** | Python 3.12+ (uv-managed) | PSF | Fast iteration, extensive hardware library bindings, rapid async I/O. |
| **Sensor Parsing** | Pydantic v2 + aioserial + bleak | MIT / BSD | Strict compile-time typing, high-speed C-core data validation. |
| **Edge ML Engine** | ONNX Runtime + OpenCV Headless | MIT / Apache-2.0 | CPU/NPU hardware-accelerated local neural net inference. |
| **Edge Broker** | Eclipse Mosquitto | EPL-2.0 / EDL-1.0 | Micro-footprint, ultra-low memory MQTT pub/sub message broker. |
| **Collector Bus** | Apache Kafka (Strimzi Operator on k3s) | Apache-2.0 | Distributed, persistent, battle-tested event-streaming backbone. |
| **Database** | PostgreSQL 16 + PostGIS 3.4 | PostgreSQL / GPL-2 | Spatial indexing, geofence computations, zero proprietary lock-in. |
| **Frontend Map** | MapLibre GL JS + PMTiles | BSD-3-Clause / BSD | Hardware-accelerated offline vector tile rendering without cloud APIs. |
| **Edge Metrics** | Vector (Timber.io) + Prometheus | MPL-2.0 / Apache-2.0 | Local telemetry aggregation and metric buffering in air-gapped zones. |

---

## 6. Strategic Takeaways & Defense Value Proposition

1. **Elimination of Prime Contractor Monopoly:** Traditional C4ISR platforms demand eight-figure development contracts and months for simple feature changes. KestrelCOP proves that modern open-source stacks outperform legacy military software in agility, security, and developer ergonomics.
2. **True Survivability in Contested Environments:** If internet access, GPS, or cellular infrastructure is neutralized by adversaries, KestrelCOP units continue sensing, computing, and mapping autonomously.
3. **Radical Cost Reduction (Attritable Tech):** Operating on $100 COTS micro-computers allows edge nodes to be expendable on loitering munitions, micro-recon drones, or dismounted scouts without risking proprietary defense hardware captures.
