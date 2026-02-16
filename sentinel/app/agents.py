"""GROQ-powered agents: Supervisor, Investigator, Operator."""
import logging
import os
import re
from typing import Literal

from groq import Groq

from app.rag import search_past_incidents

logger = logging.getLogger(__name__)
_client = None
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-70b-versatile")


def _get_client() -> Groq:
    global _client
    if _client is None:
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ValueError("GROQ_API_KEY environment variable is required")
        _client = Groq(api_key=api_key)
    return _client


def supervisor_route(alert_name: str, severity: str) -> Literal["investigator", "operator"]:
    """Decide which agent handles the alert."""
    try:
        client = _get_client()
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "You are a routing agent for infrastructure alerts. Reply with ONLY one word: investigator or operator. Send to investigator for diagnostics (CPU, memory, logs). Send to operator for critical fires that need immediate action.",
                },
                {
                    "role": "user",
                    "content": f"Alert: {alert_name}, severity: {severity}. Route to investigator or operator?",
                },
            ],
            max_tokens=20,
        )
        out = (response.choices[0].message.content or "").strip().lower()
        route = "operator" if "operator" in out else "investigator"
        logger.info("Supervisor decision: route to %s (alert=%s, severity=%s)", route, alert_name, severity)
        return route
    except Exception as e:
        logger.warning("Supervisor GROQ failed, defaulting to investigator: %s", e)
        return "investigator"


def investigator_analyze(
    alert_name: str, container: str, logs: str, stats_summary: str
) -> str:
    """Analyze evidence and produce a recommendation, using RAG for past incidents."""
    try:
        query = f"{alert_name} {container} {stats_summary} {logs[-1000:] if logs else ''}"
        past = search_past_incidents(query, limit=3)
        past_str = ""
        if past:
            past_str = "\n\nPast similar incidents:\n" + "\n".join(
                f"- Error: {p['error_text']} -> Fix: {p['fix_text']}" for p in past
            )

        client = _get_client()
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "You are an infrastructure investigator. Given container logs and stats, diagnose the issue and recommend an action. Use past similar incidents to guide your decision when relevant. Available actions:\n- RESTART: Restart the container\n- STOP: Stop the container\n- NETWORK_DISCONNECT: Isolate container from network (containment)\n- UPDATE_RESOURCES: memory=2048 (increase memory in MB) or cpu=2.0 (CPU cores)\n- ROLLBACK: Revert to previous image version\n- SKIP: No action needed\nReply with a single line in format: ACTION or ACTION: reason. For UPDATE_RESOURCES, include parameters like UPDATE_RESOURCES: memory=2048 or UPDATE_RESOURCES: cpu=2.0",
                },
                {
                    "role": "user",
                    "content": f"Alert: {alert_name}, container: {container}\n\nLogs (last 50 lines):\n{logs[:2000]}\n\nStats: {stats_summary}{past_str}\n\nRecommend an action:",
                },
            ],
            max_tokens=150,
        )
        recommendation = (response.choices[0].message.content or "SKIP").strip()
        logger.info("Investigator recommendation: %s (container=%s)", recommendation, container)
        return recommendation
    except Exception as e:
        logger.warning("Investigator GROQ failed: %s", e)
        return "SKIP: GROQ error"


def operator_decide(recommendation: str, container: str) -> str:
    """Parse recommendation and return action type with parameters."""
    rec_upper = recommendation.upper()
    if "RESTART" in rec_upper:
        return "restart"
    if "STOP" in rec_upper:
        return "stop"
    if "NETWORK_DISCONNECT" in rec_upper:
        return "network_disconnect"
    if "NETWORK_CONNECT" in rec_upper:
        network_match = re.search(r"NETWORK_CONNECT[:\s]+(\S+)", rec_upper)
        network = network_match.group(1) if network_match else None
        return f"network_connect:{network}" if network else "network_connect"
    if "UPDATE_RESOURCES" in rec_upper:
        memory_match = re.search(r"memory[=:](\d+)", rec_upper)
        cpu_match = re.search(r"cpu[=:](\d+\.?\d*)", rec_upper)
        memory = int(memory_match.group(1)) if memory_match else None
        cpu = float(cpu_match.group(1)) if cpu_match else None
        params = []
        if memory:
            params.append(f"memory={memory}")
        if cpu:
            params.append(f"cpu={cpu}")
        return f"update_resources:{','.join(params)}" if params else "update_resources"
    if "ROLLBACK" in rec_upper:
        return "rollback"
    return "skip"
