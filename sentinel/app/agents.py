"""GROQ-powered agents: Investigator (structured assessment) and Operator (tools)."""
import json
import logging
import os
from typing import Any

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


def investigator_assess(
    alert_name: str, container: str, logs: str, stats_summary: str
) -> dict[str, Any]:
    """
    Analyze evidence and return informational context for the operator.
    Keys: summary (str), suggested_actions (list of str). Does not gate execution or trigger HITL.
    """
    default = {
        "summary": "Assessment unavailable.",
        "suggested_actions": [],
    }
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
                    "content": """You are an infrastructure investigator. Given container logs and stats, produce a JSON object with exactly these keys:
- "summary": Short diagnosis (1-2 sentences). Informational only.
- "suggested_actions": List of suggested actions for context, e.g. ["RESTART"], ["UPDATE_RESOURCES", "memory=2048"], or []. No free-form text; action names and optional params only.
Do not decide whether remediation is destructive or gate execution. Reply with ONLY valid JSON, no markdown or extra text.""",
                },
                {
                    "role": "user",
                    "content": f"Alert: {alert_name}, container: {container}\n\nLogs (last 50 lines):\n{logs[:2000]}\n\nStats: {stats_summary}{past_str}\n\nOutput the JSON assessment:",
                },
            ],
            max_tokens=300,
        )
        raw = (response.choices[0].message.content or "").strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        data = json.loads(raw)
        summary = str(data.get("summary", default["summary"]))
        actions = data.get("suggested_actions")
        if not isinstance(actions, list):
            actions = []
        suggested_actions = [str(a) for a in actions]
        out = {"summary": summary, "suggested_actions": suggested_actions}
        logger.info("Investigator assessment (container=%s): summary length=%d", container, len(summary))
        return out
    except Exception as e:
        logger.warning("Investigator GROQ failed: %s", e)
        return {**default, "summary": f"Assessment failed: {e}"}
