"""LangGraph investigation workflow with 3 agents (Supervisor, Investigator, Operator)."""
import logging
import os
from typing import TypedDict

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import StateGraph
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.agents import investigator_analyze, operator_decide, supervisor_route
from app.tools import get_logs, get_stats, restart_container, stop_container

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


def supervisor_node(state: dict) -> dict:
    """Supervisor agent: routes to investigator or operator."""
    alert_name = state.get("alert_name", "unknown")
    severity = (state.get("alert_payload", {}).get("alerts", [{}])[0].get("labels", {}) or {}).get("severity", "critical")
    route = supervisor_route(alert_name, severity)
    return {"action": route}


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


def operator_node(state: dict) -> dict:
    """Operator agent: confirms and executes the action."""
    container = state.get("container", TARGET_CONTAINER)
    recommendation = state.get("recommendation", "SKIP")
    action = state.get("action", "investigator")

    if action == "skip":
        return {"result": "No remediation needed."}

    decision = operator_decide(recommendation, container)

    if decision == "restart":
        try:
            msg = restart_container(container)
            return {"result": msg, "action": "restarted"}
        except Exception as e:
            return {"result": f"Restart failed: {e}"}
    if decision == "stop":
        try:
            msg = stop_container(container)
            return {"result": msg, "action": "stopped"}
        except Exception as e:
            return {"result": f"Stop failed: {e}"}
    return {"result": f"Operator skipped. Recommendation was: {recommendation}"}


def build_graph():
    workflow = StateGraph(InvestigationState)
    workflow.add_node("triage", triage_node)
    workflow.add_node("supervisor", supervisor_node)
    workflow.add_node("investigator", investigator_node)
    workflow.add_node("operator", operator_node)
    workflow.set_entry_point("triage")
    workflow.add_edge("triage", "supervisor")
    workflow.add_edge("supervisor", "investigator")
    workflow.add_edge("investigator", "operator")
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
