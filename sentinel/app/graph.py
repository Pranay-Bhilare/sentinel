"""LangGraph investigation workflow with 3 agents (Supervisor, Investigator, Operator)."""
import logging
import os
from typing import TypedDict

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import StateGraph
from langgraph.types import interrupt
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.agents import investigator_analyze, operator_decide, supervisor_route
from app.slack_client import send_approval_request
from app.tools import (
    get_logs,
    get_stats,
    restart_container,
    stop_container,
    network_disconnect,
    network_connect,
    update_container_resources,
    rollback_container,
)

logger = logging.getLogger(__name__)

TARGET_CONTAINER = "victim_service"
DB_URI = os.getenv("SENTINEL_DB_URI", "postgresql://user:pass@postgres:5432/sentinel_db")


class InvestigationState(TypedDict):
    alert_payload: dict
    alert_name: str
    container: str
    logs: str
    stats: dict
    stats_summary: str
    recommendation: str
    action: str
    result: str
    human_approval: str
    thread_id: str


def triage_node(state: dict) -> dict:
    """Parse alert and determine target container."""
    payload = state["alert_payload"]
    alerts = payload.get("alerts", [])
    thread_id = payload.get("fingerprint", "default_incident")
    if not alerts:
        return {"alert_name": "unknown", "container": TARGET_CONTAINER, "action": "skip", "thread_id": thread_id}
    alert = alerts[0]
    labels = alert.get("labels", {})
    alert_name = labels.get("alertname", "unknown")
    container = labels.get("name") or labels.get("container") or TARGET_CONTAINER
    return {"alert_name": alert_name, "container": container, "action": "investigate", "thread_id": thread_id}


def supervisor_node(state: dict) -> dict:
    """Supervisor agent: routes to investigator or operator."""
    alert_name = state.get("alert_name", "unknown")
    severity = (state.get("alert_payload", {}).get("alerts", [{}])[0].get("labels", {}) or {}).get("severity", "critical")
    route = supervisor_route(alert_name, severity)
    return {"action": route}


def _route_after_investigator(state: dict) -> str:
    """Route to send Slack before approval gate only when destructive action."""
    recommendation = (state.get("recommendation", "SKIP") or "SKIP").upper()
    action = state.get("action", "investigator")
    if action == "skip":
        return "approval_gate"
    if "SKIP" in recommendation:
        return "approval_gate"
    destructive_actions = ["RESTART", "STOP", "NETWORK_DISCONNECT", "UPDATE_RESOURCES", "ROLLBACK"]
    if any(destructive in recommendation for destructive in destructive_actions):
        return "send_approval_request"
    return "approval_gate"


def investigator_node(state: dict) -> dict:
    """Investigator agent: gathers evidence and produces recommendation."""
    container = state.get("container", TARGET_CONTAINER)
    alert_name = state.get("alert_name", "unknown")
    try:
        logs = get_logs(container)
        stats = get_stats(container)
    except Exception as e:
        return {"logs": "", "stats": {}, "stats_summary": str(e), "recommendation": "SKIP: " + str(e)}

    cpu_pct = 0
    mem_usage = 0
    if stats:
        cpu_delta = stats.get("cpu_stats", {}).get("cpu_usage", {}).get("total_usage", 0)
        system_delta = stats.get("cpu_stats", {}).get("system_cpu_usage", 0)
        if system_delta:
            num_cpus = len(stats.get("cpu_stats", {}).get("cpu_usage", {}).get("percpu_usage") or [1])
            cpu_pct = (cpu_delta / system_delta) * num_cpus * 100 if system_delta else 0
        mem_usage = stats.get("memory_stats", {}).get("usage", 0) or 0

    stats_summary = f"CPU: ~{cpu_pct:.1f}%, Memory: {mem_usage} bytes"
    recommendation = investigator_analyze(alert_name, container, logs, stats_summary)
    return {"logs": logs, "stats": stats, "stats_summary": stats_summary, "recommendation": recommendation}


def send_approval_request_node(state: dict) -> dict:
    """Send Slack HITL approval request. Runs only once before interrupt."""
    container = state.get("container", TARGET_CONTAINER)
    alert_name = state.get("alert_name", "unknown")
    stats_summary = state.get("stats_summary", "")
    thread_id = state.get("thread_id", "default_incident")
    recommendation = state.get("recommendation", "RESTART")
    send_approval_request(
        thread_id=thread_id,
        container=container,
        recommendation=recommendation,
        alert_name=alert_name,
        stats_summary=stats_summary,
    )
    return {}


def approval_gate_node(state: dict) -> dict:
    """Gate before Operator: for destructive actions, wait for human approval."""
    recommendation = (state.get("recommendation", "SKIP") or "SKIP").upper()
    action = state.get("action", "investigator")
    thread_id = state.get("thread_id", "default_incident")

    if action == "skip":
        return {"human_approval": "approved"}

    if "SKIP" in recommendation:
        return {"human_approval": "approved"}

    destructive_actions = ["RESTART", "STOP", "NETWORK_DISCONNECT", "UPDATE_RESOURCES", "ROLLBACK"]
    if any(destructive in recommendation for destructive in destructive_actions):
        human_approval = interrupt(thread_id)
        logger.info("Human approval received: %s (thread_id=%s)", human_approval, thread_id)
        return {"human_approval": str(human_approval).lower()}

    return {"human_approval": "approved"}


def operator_node(state: dict) -> dict:
    """Operator agent: confirms and executes the action."""
    container = state.get("container", TARGET_CONTAINER)
    recommendation = state.get("recommendation", "SKIP")
    action = state.get("action", "investigator")
    human_approval = state.get("human_approval", "approved")

    if action == "skip":
        return {"result": "No remediation needed."}

    if human_approval == "denied":
        return {"result": "Investigation aborted by user."}

    decision = operator_decide(recommendation, container)

    try:
        if decision == "restart":
            msg = restart_container(container)
            return {"result": msg, "action": "restarted"}
        elif decision == "stop":
            msg = stop_container(container)
            return {"result": msg, "action": "stopped"}
        elif decision == "network_disconnect":
            msg = network_disconnect(container)
            return {"result": msg, "action": "network_disconnected"}
        elif decision.startswith("network_connect:"):
            network = decision.split(":", 1)[1]
            msg = network_connect(container, network)
            return {"result": msg, "action": "network_connected"}
        elif decision.startswith("update_resources:"):
            params_str = decision.split(":", 1)[1]
            memory = None
            cpu = None
            for param in params_str.split(","):
                if param.startswith("memory="):
                    memory = int(param.split("=")[1])
                elif param.startswith("cpu="):
                    cpu = float(param.split("=")[1])
            msg = update_container_resources(container, memory_limit_mb=memory, cpu_limit=cpu)
            return {"result": msg, "action": "resources_updated"}
        elif decision == "rollback":
            msg = rollback_container(container)
            return {"result": msg, "action": "rolled_back"}
        else:
            return {"result": f"Operator skipped. Recommendation was: {recommendation}"}
    except Exception as e:
        logger.exception("Operator action failed")
        return {"result": f"Action failed: {e}"}


def build_graph():
    workflow = StateGraph(InvestigationState)
    workflow.add_node("triage", triage_node)
    workflow.add_node("supervisor", supervisor_node)
    workflow.add_node("investigator", investigator_node)
    workflow.add_node("send_approval_request", send_approval_request_node)
    workflow.add_node("approval_gate", approval_gate_node)
    workflow.add_node("operator", operator_node)
    workflow.set_entry_point("triage")
    workflow.add_edge("triage", "supervisor")
    workflow.add_edge("supervisor", "investigator")
    workflow.add_conditional_edges("investigator", _route_after_investigator)
    workflow.add_edge("send_approval_request", "approval_gate")
    workflow.add_edge("approval_gate", "operator")
    try:
        pool = ConnectionPool(
            DB_URI,
            kwargs={"autocommit": True, "row_factory": dict_row},
        )
        checkpointer = PostgresSaver(pool)
        checkpointer.setup()
        return workflow.compile(checkpointer=checkpointer)
    except Exception as e:
        logger.warning("Checkpointer failed, running without persistence: %s", e)
        return workflow.compile()


investigation_graph = build_graph()
