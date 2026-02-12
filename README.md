<div align="center">

# 🌍 GeoAgentBench

**A Comprehensive Benchmark for Evaluating LLM/VLM Agents in Real-World Geospatial Environments**

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688.svg)](https://fastapi.tiangolo.com/)

[Getting Started](#-getting-started) · [Task Types](#-task-types) · [Evaluation](#-evaluation) · [API Reference](#-api-reference) · [Agent Development](#-agent-development)

</div>

---

## 📖 Overview

**GeoAgentBench** is a benchmark platform for evaluating the geospatial reasoning and navigation capabilities of Large Language Model (LLM) and Vision-Language Model (VLM) agents. Agents are placed in real Google Street View environments and must complete diverse tasks — from point-to-point navigation to building height estimation and spatial reasoning — by interpreting panoramic imagery, making sequential decisions, and interacting with a structured action space.

### Key Features

- 🗺️ **Real-World Environments** — Tasks set in actual Google Street View panoramas across multiple cities
- 🧩 **5 Task Types** — Navigation, visual landmark identification, height estimation, distance estimation, and angle estimation
- 🤖 **Agent-Agnostic API** — RESTful interface compatible with any LLM/VLM (GPT, Claude, Gemini, open-source models)
- 🖥️ **Human Evaluation Mode** — Web-based UI for human baseline collection and replay
- ⚡ **Parallel Execution** — Run hundreds of agent–task combinations concurrently
- 📊 **Automated Scoring** — Unified evaluation script with task-type-specific metrics

---

## 🏗️ Architecture

```
GeoAgentBench/
├── main.py                 # FastAPI application entry point
├── api/                    # RESTful API endpoints
│   ├── routes.py           # Session, action, task, geofence endpoints
│   └── models.py           # Pydantic request/response schemas
├── engine/                 # Core benchmark engine
│   ├── session_manager.py  # Session lifecycle management
│   ├── action_executor.py  # Action validation & execution
│   ├── observation_generator.py  # Panorama rendering
│   ├── metadata_cache.py   # Panorama metadata (SQLite cache)
│   ├── direction_calculator.py   # Compass & move calculations
│   ├── geofence_checker.py # Geofence boundary enforcement
│   └── logger.py           # JSONL session logging
├── config/                 # Configuration & prompt templates
│   ├── settings.py         # Global settings
│   ├── agent_configs.json  # Per-agent API configurations
│   └── system_prompt_*.txt # Task-type-specific system prompts
├── web_ui/                 # Browser-based evaluation interface
├── scripts/                # Benchmark execution & evaluation
│   ├── run_benchmark_parallel.py  # Parallel agent runner
│   └── evaluate_all.py     # Unified evaluation & scoring
├── examples/               # Example agent implementations
│   └── vln_agent.py        # Reference VLN agent (OpenAI-compatible)
├── tasks/                  # Task definition files (JSON)
└── data/
    └── panoramas/          # Pre-downloaded panorama images
```

---

## 🚀 Getting Started

### Prerequisites

- Python 3.10+
- A Google API Key (for Street View Tiles API access)
- An LLM/VLM API key (OpenAI, Anthropic, Google, or any OpenAI-compatible endpoint)

### 1. Installation

```bash
git clone https://github.com/your-org/GeoAgentBench.git
cd GeoAgentBench

pip install -r requirements.txt
```

### 2. Configuration

Create a `.env` file in the project root:

```env
# Google API (for panorama tiles)
GOOGLE_API_KEY=your_google_api_key

# LLM/VLM API (for agent inference)
API_BASE_URL=https://api.openai.com/v1
API_KEY=your_llm_api_key
MODEL_NAME=gpt-4o
```

### 3. Download Panorama Data

Pre-downloaded panorama images are available on Hugging Face:

```bash
# Method 1: Using huggingface-cli
pip install huggingface_hub
huggingface-cli download lalayg/pano --repo-type dataset --local-dir data/panoramas

# Method 2: Manual download
# Visit https://huggingface.co/datasets/lalayg/pano/tree/main
# Download and extract to data/panoramas/
```

> [!IMPORTANT]
> The `data/panoramas/` directory must be populated before running tasks.
> Each subdirectory is named by panorama ID and contains the pre-assembled panoramic image tiles.

### 4. Start the Benchmark Server

```bash
python main.py
```

The server starts at `http://localhost:8000`:

| Endpoint | Description |
|----------|-------------|
| `http://localhost:8000/` | Web UI dashboard |
| `http://localhost:8000/docs` | Interactive API documentation (Swagger) |
| `http://localhost:8000/human_eval.html` | Human evaluation interface |

---

## 🧩 Task Types

GeoAgentBench includes **1,000 tasks** across 5 categories, testing distinct geospatial capabilities:

| Type | Prefix | Count | Description | Success Metric |
|------|--------|-------|-------------|----------------|
| **Navigation** | `nav_` | 350 | Navigate to a target POI via turn-by-turn directions | Final position within 15m of target |
| **Visual Landmark** | `vis_` | 350 | Identify a specific visual landmark by navigating to it | Final position within 15m of target |
| **Height Estimation** | `height_` | 100 | Estimate the height of a building visible in the scene | Within ±15% of ground truth |
| **Distance Estimation** | `dis_` | 100 | Estimate the distance between two POIs | Within ±20% of ground truth |
| **Angle Estimation** | `angle_` | 100 | Estimate the relative bearing angle between two POIs | Within ±30° of ground truth |

### Task File Format

Each task is a JSON file in `tasks/`:

```json
{
  "task_id": "nav_0001_target_20260124_0233_1",
  "task_type": "navigation_to_poi",
  "geofence": "list_nav_supermarket_20260124_023241",
  "spawn_point": "_3W44HNJ3pI5qaa6NHxP-Q",
  "spawn_heading": 154.4,
  "description": "Navigate to Quick Mart. Head southeast on Nyota Ln...",
  "ground_truth": {
    "target_name": "Quick Mart",
    "target_pano_id": "KrLqO7swFco2z37wZNwQow",
    "optimal_distance_meters": 120
  },
  "visual_path": [ ... ],
  "max_steps": 28
}
```

---

## 🤖 Agent Development

### Action Space

Agents interact with the environment through three actions:

| Action | Parameters | Description |
|--------|-----------|-------------|
| `move` | `move_id: int` | Move to an adjacent panorama node |
| `rotation` | `heading: float, pitch: float` | Rotate camera (heading: 0–360°, pitch: -85–85°) |
| `stop` | `answer: string` | End the task and submit an answer |

### Agent Response Format

Agents must respond with JSON:

```json
{
  "THOUGHT": "I can see the target building on my right...",
  "ACTION": "MOVE(3)"
}
```

Supported action formats: `MOVE(id)`, `ROTATION(heading, pitch)`, `STOP(answer)`

### Example Agent

A reference implementation is provided in [`examples/vln_agent.py`](examples/vln_agent.py):

```python
from examples.vln_agent import VLNAgent, AgentConfig

config = AgentConfig(
    api_base_url="https://api.openai.com/v1",
    api_key="sk-...",
    model_name="gpt-4o"
)
agent = VLNAgent(config)

result = agent.run(task_id="nav_0001_target_20260124_0233_1", max_steps=30)
print(f"Trajectory length: {len(result['trajectory'])}")
```

The reference agent supports:
- **Any OpenAI-compatible API** (OpenAI, Anthropic via proxy, Gemini, local models)
- **Continuous dialogue** with conversation history
- **Automatic JSON repair** via fallback model when parsing fails
- **Retry logic** with exponential backoff for rate limits

### Multi-Agent Config

Configure multiple agents in `config/agent_configs.json`:

```json
{
  "gpt-4o": {
    "api_base_url": "https://api.openai.com/v1",
    "api_key": "sk-..."
  },
  "claude-opus-4": {
    "api_base_url": "https://api.anthropic.com/v1",
    "api_key": "sk-ant-..."
  },
  "gemini-2.5-pro": {
    "api_base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
    "api_key": "AIza..."
  }
}
```

---

## ▶️ Running the Benchmark

### Single Agent Run

```python
from examples.vln_agent import VLNAgent, AgentConfig

config = AgentConfig.from_env()
agent = VLNAgent(config)
result = agent.run(task_id="vis_0001_target_20260124_0233_1", max_steps=25)
```

### Parallel Benchmark

Run all agents × all tasks concurrently:

```bash
python scripts/run_benchmark_parallel.py
```

Configure agents and task types in the script header:

```python
AGENTS = [
    "gpt-4o",
    "claude-opus-4",
    "gemini-2.5-pro",
]
```

Logs are saved to `logs/log_YYYYMMDD_HHMMSS/` with one JSONL file per agent–task pair.

---

## 📊 Evaluation

### Run Evaluation

```bash
# Evaluate all agents in a log directory
python scripts/evaluate_all.py --dir logs/log_20260128_xxx

# With custom tasks directory
python scripts/evaluate_all.py --dir logs/log_20260128_xxx --tasks-dir tasks
```

### Metrics

| Task Type | Metric | Threshold |
|-----------|--------|-----------|
| Navigation (`nav`) | Distance to target panorama | < 15m |
| Visual (`vis`) | Distance to target panorama | < 15m |
| Height (`height`) | Relative error | ±15% |
| Distance (`dis`) | Relative error | ±20% |
| Angle (`angle`) | Absolute error | ±30° |

### Output

The evaluation script produces per-agent, per-task-type results and a summary table:

```
╔══════════════════╦═══════╦═══════╦════════╦═══════╦═══════╦═══════╗
║ Agent            ║  Nav  ║  Vis  ║ Height ║  Dis  ║ Angle ║ Total ║
╠══════════════════╬═══════╬═══════╬════════╬═══════╬═══════╬═══════╣
║ gpt-4o           ║ 42.0% ║ 38.5% ║ 25.0%  ║ 30.0% ║ 35.0% ║ 34.1% ║
║ claude-opus-4    ║ 45.0% ║ 41.2% ║ 28.0%  ║ 32.0% ║ 37.0% ║ 36.6% ║
║ gemini-2.5-pro   ║ 40.0% ║ 36.0% ║ 22.0%  ║ 28.0% ║ 33.0% ║ 31.8% ║
╚══════════════════╩═══════╩═══════╩════════╩═══════╩═══════╩═══════╝
```

The **Total Score** is the average Success Rate across all 5 task types.

---

## 📡 API Reference

### Session Management

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/sessions` | Create a new evaluation session |
| `GET` | `/api/sessions/{id}` | Get current session state |
| `POST` | `/api/sessions/{id}/action` | Execute an action |
| `POST` | `/api/sessions/{id}/end` | End a session |
| `POST` | `/api/sessions/{id}/pause` | Pause a session (human mode) |
| `POST` | `/api/sessions/{id}/resume` | Resume a paused session |

### Task Management

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/tasks` | List all available tasks |
| `GET` | `/api/tasks/{id}` | Get task details |
| `POST` | `/api/tasks/{id}/preload` | Preload panoramas for a task |
| `GET` | `/api/tasks/{id}/preload/status` | Check preload status |

### Example: Create Session & Execute Action

```bash
# Create session
curl -X POST http://localhost:8000/api/sessions \
  -H "Content-Type: application/json" \
  -d '{"agent_id": "my_agent", "task_id": "nav_0001_target_20260124_0233_1", "mode": "agent"}'

# Execute action
curl -X POST http://localhost:8000/api/sessions/{session_id}/action \
  -H "Content-Type: application/json" \
  -d '{"type": "move", "move_id": 1}'
```

Full API documentation is available at `http://localhost:8000/docs` when the server is running.

---

## ⚙️ Configuration

All settings are managed in [`config/settings.py`](config/settings.py) and can be overridden via environment variables:

| Setting | Default | Description |
|---------|---------|-------------|
| `GOOGLE_API_KEY` | — | Google API key for Street View Tiles |
| `HOST` | `0.0.0.0` | Server bind address |
| `PORT` | `8000` | Server port |
| `PANORAMA_ZOOM_LEVEL` | `2` | Panorama quality (0–5, use 3 for benchmark) |
| `AUTO_DELETE_TEMP_IMAGES` | `true` | Delete rendered images after session ends |
| `RENDER_OUTPUT_SIZE` | `1280×800` | Agent observation image resolution |
| `RENDER_DEFAULT_FOV` | `90` | Default field of view (degrees) |
| `SESSION_DEFAULT_MAX_STEPS` | `100` | Default max steps per session |

---

## 📋 Log Format

Session logs are stored as JSONL files. Each line is a JSON event:

```jsonl
{"event": "session_start", "session_id": "...", "agent_id": "gpt-4o", "task_id": "nav_0001_...", "mode": "agent", ...}
{"event": "action", "step": 1, "action": {"type": "move", "move_id": 3}, "state": {"pano_id": "...", "heading": 154.4, ...}, ...}
{"event": "action", "step": 2, "action": {"type": "rotation", "heading": 270, "pitch": 0}, ...}
{"event": "action", "step": 3, "action": {"type": "stop", "answer": "arrived"}, ...}
```

---

## 🤝 Contributing

Contributions are welcome! Areas of interest:

- **New task types** — Propose and implement new geospatial reasoning tasks
- **Agent implementations** — Submit your agent as an example under `examples/`
- **Evaluation metrics** — Propose additional metrics or scoring methods
- **City coverage** — Extend tasks to new cities and regions

---

## 📄 License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

---

## 🙏 Acknowledgements

- [Google Street View](https://developers.google.com/maps/documentation/streetview) for panoramic imagery
- [Google Maps Platform](https://developers.google.com/maps) for geolocation and routing APIs
- [FastAPI](https://fastapi.tiangolo.com/) for the high-performance web framework

---

<div align="center">

**Built for advancing geospatial AI research** 🌐

</div>
