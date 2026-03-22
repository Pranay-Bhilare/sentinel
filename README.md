# Sentinel

Automated infrastructure remediation engine that ingests Prometheus alerts and performs autonomous Root Cause Analysis (RCA) using distributed tracing and container-level telemetry. It proposes recovery actions through an agent-based workflow with a custom Docker SDK remediation toolkit.

## Tech Stack

Python · FastAPI · Celery · Redis · Docker SDK · PostgreSQL · Prometheus · OpenTelemetry · Jaeger · Slack API · LangGraph · cAdvisor

## Overview

Sentinel receives alert webhooks from Prometheus/Alertmanager and initiates a multi-step investigation. Powered by dynamic agents, it analyzes distributed traces and system logs to pinpoint the underlying issue before proposing container-level remediations (restart, resource scaling, or rollback). A Slack-based approval gate ensures human-in-the-loop safeguards before any changes are executed.

**Key capabilities:**

- **Autonomous RCA Engine** — Analyzes OpenTelemetry traces and container logs to identify code-level or infrastructure-level bottlenecks.
- **Automated Remediation** — Executes recovery actions (restart, dynamic resource scaling, rollback) via a Docker SDK–based toolkit.
- **Non-blocking Pipeline** — FastAPI + Celery + Redis architecture to handle high-volume incident bursts reliably in the background.
- **Stateful Workflows** — LangGraph with PostgreSQL persistence for resilient execution and human-in-the-loop approval gates.

## Architecture

- **Prometheus + cAdvisor** — Monitors container metrics and fires alerts based on predefined rules.
- **OpenTelemetry + Jaeger** — Provides distributed tracing for deep inspection of application requests.
- **Sentinel API** — Ingests alerts and coordinates the investigation; handles Slack interactions.
- **Celery Workers** — Executes background investigation and remediation tasks.
- **LangGraph Agents** — Triage → Investigator → Operator loop for structured decision-making.
- **Slack** — Provides a centralized interface for incident notification and manual approval.

## Setup

**Prerequisites:** Docker, Docker Compose, Groq API key, Slack app credentials.

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

## Internal Testing

The system can be tested by interacting with the internal endpoints of the monitored service (e.g., triggering a cache warmup job or generating heavy reports) and observing the autonomous investigation flow in Slack and Jaeger.

Each alert triggers the Sentinel workflow, which post its findings and proposed solutions to the configured Slack channel.

