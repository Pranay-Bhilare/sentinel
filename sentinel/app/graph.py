"""LangGraph investigation workflow. Rule-based for HighCPUUsage."""
from typing import TypedDict

from langgraph.graph import StateGraph

from app.tools import get_logs, get_stats, restart_container

TARGET_CONTAINER = "victim_service"


class InvestigationState(TypedDict):
    alert_payload: dict
    alert_name: str
    container: str
    logs: str
    stats: dict
    action: str
    result: str


def triage_node(state: dict) -> dict:
    """Parse alert and determine target container."""
    payload = state["alert_payload"]
    alerts = payload.get("alerts", [])
    if not alerts:
        return {"alert_name": "unknown", "container": TARGET_CONTAINER, "action": "skip"}
    alert = alerts[0]
    labels = alert.get("labels", {})
    alert_name = labels.get("alertname", "unknown")
    container = labels.get("name") or labels.get("container") or TARGET_CONTAINER
    return {"alert_name": alert_name, "container": container, "action": "investigate"}


def diagnose_node(state: dict) -> dict:
    """Gather logs and stats."""
    container = state.get("container", TARGET_CONTAINER)
    try:
        logs = get_logs(container)
        stats = get_stats(container)
    except Exception as e:
        return {"logs": "", "stats": {}, "action": "skip", "result": f"Error: {e}"}
    return {"logs": logs, "stats": stats}


def remediate_node(state: dict) -> dict:
    """Restart container if HighCPUUsage."""
    alert_name = state.get("alert_name", "")
    container = state.get("container", TARGET_CONTAINER)
    action = state.get("action", "skip")
    if action == "skip":
        return {"result": "No remediation needed."}
    if alert_name == "HighCPUUsage":
        try:
            msg = restart_container(container)
            return {"result": msg, "action": "restarted"}
        except Exception as e:
            return {"result": f"Restart failed: {e}"}
    return {"result": f"Alert {alert_name} - no auto-remediation configured."}


def build_graph():
    workflow = StateGraph(InvestigationState)
    workflow.add_node("triage", triage_node)
    workflow.add_node("diagnose", diagnose_node)
    workflow.add_node("remediate", remediate_node)
    workflow.set_entry_point("triage")
    workflow.add_edge("triage", "diagnose")
    workflow.add_edge("diagnose", "remediate")
    return workflow.compile()


investigation_graph = build_graph()
