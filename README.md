# Sentinel

Automated infrastructure remediation engine that ingests Prometheus alerts and executes container-level recovery actions using an agent-based investigation workflow and a custom Docker SDK remediation toolkit.

## Tech Stack

Python · FastAPI · Celery · Redis · Docker SDK · PostgreSQL · Prometheus · Slack API · LangGraph · FastEmbed · cAdvisor

## Overview

Sentinel receives alert webhooks from Prometheus/Alertmanager, runs a multi-step investigation workflow powered by agents, and proposes container-level remediations (restart, network isolation, resource scaling, rollback). A Slack-based approval gate ensures human-in-the-loop safeguards before any infrastructure changes are executed.

**Key capabilities:**

- **Automated remediation engine** — Ingest Prometheus alerts and execute container-level recovery actions (restart, network isolation, dynamic resource scaling, rollback) via a Docker SDK–based toolkit.
- **Non-blocking alert pipeline** — FastAPI + Celery + Redis for high-volume incident bursts without API timeouts; reliable background execution of remediation workflows.
- **Stateful multi-step workflows** — LangGraph with persistent execution history in PostgreSQL; safe resumption of long-running tasks after worker failures.
- **RAG + HITL** — Retrieval-augmented generation (pgvector) for historical incident retrieval; Slack approval gate for human-in-the-loop safeguards.

## Alert Scenarios

| Scenario | Alert | Remediation |
|---------|-------|-------------|
| CPU runaway | HighCPUUsage | `restart_container` |
| Network flood | HighNetworkTx | `network_disconnect` |
| Memory pressure | HighMemoryUsage | `update_container_resources` |
| Bad deploy | HighErrorRate | `rollback_container` |

The victim service exposes `/break/cpu`, `/break/network`, `/break/memory`, and `/break/bad_deploy` to simulate each failure mode.

## Architecture

- **Prometheus + cAdvisor** — Scrape container and application metrics; fire alerts per rules in `monitoring/alerts.rules.yml`.
- **Alertmanager** — Sends webhooks to Sentinel API on alert fire/resolve.
- **Sentinel API** — Receives webhooks, enqueues `run_investigation`; handles Slack interactive events, enqueues `resume_investigation`.
- **Celery + Redis** — Task queue; background execution of investigation workflows.
- **LangGraph** — Triage → Investigator → Operator agent loop; PostgresSaver for checkpointing and resume.
- **Slack** — Single HITL: approve or deny proposed tool calls before execution.
- **Docker SDK** — Operator tools (restart, network disconnect/connect, update resources, rollback, logs, stats, inspect).

## Setup

**Prerequisites:** Docker, Docker Compose, Groq API key, Slack app (bot token, channel ID, signing secret).

Create `.env` in the repo root:

```
GROQ_API_KEY=...
SLACK_BOT_TOKEN=...
SLACK_CHANNEL_ID=...
SLACK_SIGNING_SECRET=...
```

**Run:**

```bash
docker compose up --build
```

## Triggering Scenarios

With the stack running:

```bash
# CPU runaway → restart
curl -X POST http://localhost:8001/break/cpu

# Network flood → network isolation
curl -X POST http://localhost:8001/break/network

# Memory pressure → resource scaling
curl -X POST http://localhost:8001/break/memory

# Bad deploy → rollback
curl -X POST http://localhost:8001/break/bad_deploy
```

Each scenario fires a Prometheus alert; Sentinel runs the investigation workflow and sends a Slack message listing proposed tool calls. Approve or deny to execute or abort.
