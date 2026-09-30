# 🦅 KestrelCOP

**Tactical Edge Telemetry Pipeline & Common Operating Picture (COP)**
*Offline-First • Open Data Standards (Cursor-on-Target) • COTS Hardware • Zero Cloud Lock-in*

[![CI](https://github.com/FranekJemiolo/KestrelCOP/actions/workflows/ci.yml/badge.svg)](https://github.com/FranekJemiolo/KestrelCOP/actions/workflows/ci.yml)
[![Pages](https://github.com/FranekJemiolo/KestrelCOP/actions/workflows/pages.yml/badge.svg)](https://github.com/FranekJemiolo/KestrelCOP/actions/workflows/pages.yml)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](pyproject.toml)
[![Architecture: 4-Tier](https://img.shields.io/badge/Architecture-4--Tier%20Tactical-green.svg)](docs/VISION.md)

---

## 🎯 Commander's Intent & Vision

**KestrelCOP** is an autonomous, open-source tactical telemetry pipeline and Common Operating Picture designed for **contested, degraded, and Disconnected, Intermittent, and Low-bandwidth (DIL)** environments.

Traditional military C4ISR systems rely on multi-million dollar prime contractor contracts, proprietary hardware, and fragile centralized cloud backhauls (AWS GovCloud, Azure Government). When electronic warfare, GPS denial, or physical isolation strikes, these systems fail.

KestrelCOP delivers a modern alternative:
- **Attritable & COTS-Ready:** Runs on low-cost commercial hardware (Raspberry Pi, NVIDIA Jetson, Android tablets).
- **Edge Intelligence:** Converts heavy drone video streams and sensor I/O into lightweight, standardized **Cursor-on-Target (CoT)** events locally—sending zero raw video over precious tactical radio spectrum.
- **100% Free & Open-Source:** Fully reproducible using Eclipse Mosquitto, Apache Kafka (Strimzi/k3s), PostGIS, MapLibre GL JS, and PMTiles.

👉 **Read the full operational blueprint in [docs/VISION.md](docs/VISION.md).**
🌐 **Live Architecture & Demo Portal:** [https://franekjemiolo.github.io/KestrelCOP/](https://franekjemiolo.github.io/KestrelCOP/)

---

## 🏗️ 4-Tier Architectural Topology

```mermaid
flowchart TD
    subgraph Tier1["Tier 1: Tactical Edge Node (EUD / COTS Compute)"]
        Sensors["📡 Sensors (UART GPS, BLE Heart Rate, Drone RTSP)"]
        IO_Async["⚡ asyncio Ingestion Bus (aioserial + bleak)"]
        ML_Proc["🧠 Isolated Process (multiprocessing + ONNX / YOLO)"]
        Queue["📦 asyncio.Queue (Internal Event Bus)"]
        CoTMapper["🔄 CoT Mapper (Pydantic v2 Models)"]

        Sensors --> IO_Async
        Sensors --> ML_Proc
        IO_Async --> Queue
        ML_Proc -->|IPC Queue| Queue
        Queue --> CoTMapper
    end

    subgraph Tier2["Tier 2: Tactical Transport (MANET Mesh Sim)"]
        Broker["📻 Eclipse Mosquitto (MQTT QoS 0 / QoS 1)"]
        Buffer["🛡️ Bounded Ring Buffer (collections.deque)"]
        CoTMapper --> Buffer --> Broker
    end

    subgraph Tier3["Tier 3: Command Collector (k3s Cluster)"]
        Kafka["📜 Apache Kafka via Strimzi (Immutable Log)"]
        PostGIS[("🗺️ PostgreSQL + PostGIS (Spatial Archive)")]
        Analytics["⚙️ Tactical Fusion & Analytics Workers"]

        Broker --> Kafka
        Kafka --> PostGIS
        Kafka --> Analytics
    end

    subgraph Tier4["Tier 4: Tactical Web Dashboard (React PWA)"]
        PWA["🖥️ Commander's COP Dashboard"]
        Map["🗺️ MapLibre GL JS + Offline PMTiles"]
        WS["⚡ WebSockets Real-Time Stream"]

        Kafka --> WS --> PWA
        Map --> PWA
    end

    classDef edge fill:#1e293b,stroke:#38bdf8,stroke-width:2px,color:#fff;
    classDef mesh fill:#0f172a,stroke:#34d399,stroke-width:2px,color:#fff;
    classDef collector fill:#1e1e2f,stroke:#f59e0b,stroke-width:2px,color:#fff;
    classDef pwa fill:#18181b,stroke:#a855f7,stroke-width:2px,color:#fff;

    class Tier1 edge;
    class Tier2 mesh;
    class Tier3 collector;
    class Tier4 pwa;
```

---

## 📦 System Stack Overview

| Tier | Component | Technology | Role |
| :--- | :--- | :--- | :--- |
| **Tier 1: Edge** | Ingestion & ML | `Python 3.12+`, `pydantic`, `aioserial`, `bleak`, `onnxruntime`, `opencv-python-headless` | Decoupled async I/O + multiprocessing inference; emits CoT JSON. |
| **Tier 2: Transport** | Mesh Radio | `Eclipse Mosquitto (MQTT)`, `aiomqtt`, bounded deque buffer | Reliable pub/sub across volatile MANET mesh networks. |
| **Tier 3: Collector** | Ingestion & Bus | `k3s`, `Apache Kafka (Strimzi)`, `PostgreSQL 16 + PostGIS 3.4` | High-throughput, immutable battlefield event streaming. |
| **Tier 4: Dashboard** | Geospatial COP | `React`, `TypeScript`, `MapLibre GL JS`, `PMTiles (Protomaps)` | Offline-first vector mapping and WebGL tactical symbology. |

---

## ⚡ Quickstart & Local Setup

### Prerequisites
- Python 3.12+
- [`uv`](https://github.com/astral-sh/uv) (recommended) or standard `pip`
- Git

### 1. Clone & Set Up Python Environment
```bash
git clone https://github.com/FranekJemiolo/KestrelCOP.git
cd KestrelCOP

# Install dependencies using uv
uv sync
```

### 2. Install Pre-commit Hooks
```bash
uv run pre-commit install
```

### 3. Run Quality Assurance Suite
```bash
# Run Ruff linting and formatting checks
uv run ruff check .
uv run ruff format --check .

# Run static type checking with Mypy (strict mode)
uv run mypy edge_node tests

# Execute test suite
uv run pytest
```

### 4. Run Edge Node Simulation
```bash
uv run python -m edge_node.main
```

---

## 📁 Repository Layout

```
KestrelCOP/
├── .github/
│   └── workflows/
│       ├── ci.yml              # Linting, formatting, type checking, and tests
│       └── pages.yml           # Automated deployment of docs to GitHub Pages
├── docs/
│   ├── VISION.md               # Operational Intent, Tier Specs, Validation Matrix
│   └── index.html              # GitHub Pages Interactive Tactical Dashboard
├── edge_node/
│   ├── __init__.py             # Edge Node Package
│   ├── models.py               # Pydantic Schemas (Location, Biometrics, Detection)
│   ├── cot_mapper.py           # Cursor-on-Target (CoT) JSON Serializer
│   └── main.py                 # Asyncio Event Loop & Concurrency Event Bus
├── tests/
│   ├── __init__.py
│   └── test_edge_node.py       # Unit tests for schemas, CoT mapping, and queues
├── .gitignore                  # Git hygiene rules
├── .pre-commit-config.yaml     # Ruff, Mypy, and pre-commit hooks
├── LICENSE                     # Apache License 2.0
├── pyproject.toml              # Dependencies & tool configurations
└── README.md                   # Project landing page
```

---

## 📜 License

Licensed under the **Apache License, Version 2.0**. See [LICENSE](LICENSE) for details.
