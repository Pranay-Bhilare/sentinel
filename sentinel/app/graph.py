"""LangGraph investigation workflow: triage → investigator → operator_agent ⇄ operator_tools. Single HITL at tool execution."""
import logging
import operator
import os
from typing import Annotated, Sequence, TypedDict

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import StateGraph
from langgraph.types import interrupt
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_groq import ChatGroq
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.agents import investigator_assess
from app.operator_tools import OPERATOR_TOOLS
from app.slack_client import send_tool_approval_request
from app.tools import get_logs, get_stats

logger = logging.getLogger(__name__)

TARGET_CONTAINER = "victim_service"
DB_URI = os.getenv("SENTINEL_DB_URI", "postgresql://user:pass@postgres:5432/sentinel_db")


class InvestigationState(TypedDict, total=False):
    alert_payload: dict
    alert_name: str
    container: str
    logs: str
    stats: dict
    stats_summary: str
    action: str
    investigator_summary: str
    suggested_actions: list  # Informational only; passed to operator_agent context
    result: str
    human_approval: str  # Set only by operator_approval (tool-level HITL)
    thread_id: str
    messages: Annotated[Sequence[BaseMessage], operator.add]


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


def investigator_node(state: dict) -> dict:
    """Investigator: gathers logs, stats, summary. Informational only; does not gate execution or trigger HITL."""
    container = state.get("container", TARGET_CONTAINER)
    alert_name = state.get("alert_name", "unknown")
    if state.get("action") == "skip":
        return {
            "logs": "",
            "stats": {},
            "stats_summary": "",
            "investigator_summary": "No alerts to investigate.",
            "suggested_actions": [],
        }
    try:
        logs = get_logs(container)
        stats = get_stats(container)
    except Exception as e:
        return {
            "logs": "",
            "stats": {},
            "stats_summary": str(e),
            "investigator_summary": f"Evidence gather failed: {e}",
            "suggested_actions": [],
        }

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
    assessment = investigator_assess(alert_name, container, logs, stats_summary)
    return {
        "logs": logs,
        "stats": stats,
        "stats_summary": stats_summary,
        "investigator_summary": assessment.get("summary", ""),
        "suggested_actions": assessment.get("suggested_actions") or [],
    }


def _get_operator_model():
    """Chat model with operator tools bound for ReAct-style tool calling."""
    model = ChatGroq(
        model=os.getenv("GROQ_MODEL", "llama-3.1-70b-versatile"),
        api_key=os.getenv("GROQ_API_KEY"),
        temperature=0,
    )
    return model.bind_tools(OPERATOR_TOOLS)


def operator_agent_node(state: dict) -> dict:
    """Operator agent: LLM with bind_tools proposes tool_calls. Single HITL at execution (operator_approval)."""
    container = state.get("container", TARGET_CONTAINER)
    messages = state.get("messages") or []
    if not messages:
        alert_name = state.get("alert_name", "unknown")
        stats_summary = state.get("stats_summary", "")
        logs_preview = (state.get("logs") or "")[:1500]
        summary = state.get("investigator_summary", "")
        suggested_actions = state.get("suggested_actions") or []
        actions_str = ", ".join(suggested_actions) if suggested_actions else "None"
        initial = (
            f"Alert: {alert_name}. Container: {container}. Stats: {stats_summary}. "
            f"Investigator summary: {summary}. Suggested actions: {actions_str}. "
            f"Use your tools to remediate as appropriate. Logs (preview): {logs_preview}"
        )
        messages = [HumanMessage(content=initial)]
    model = _get_operator_model()
    response = model.invoke(messages)
    if not isinstance(response, AIMessage):
        response = AIMessage(content=str(response))
    out = {"messages": [response]}
    if not (getattr(response, "tool_calls", None) or []):
        out["result"] = (response.content or "Remediation complete.").strip()
    return out


def _operator_agent_route(state: dict) -> str:
    """Route to send_tool_approval if last message has tool_calls, else END."""
    messages = state.get("messages") or []
    if not messages:
        return "__end__"
    last = messages[-1]
    if getattr(last, "tool_calls", None):
        return "send_tool_approval_request"
    return "__end__"


def send_tool_approval_request_node(state: dict) -> dict:
    """HITL #2: Send Slack listing the full batch of proposed tool_calls for this turn (one request per step)."""
    thread_id = state.get("thread_id", "default_incident")
    container = state.get("container", TARGET_CONTAINER)
    messages = state.get("messages") or []
    last = messages[-1] if messages else None
    tool_calls = getattr(last, "tool_calls", None) or []
    if tool_calls:
        send_tool_approval_request(thread_id=thread_id, container=container, tool_calls=tool_calls)
    return {}


def operator_approval_node(state: dict) -> dict:
    """HITL gate: interrupt for tool_calls approval; on resume return human_approval."""
    thread_id = state.get("thread_id", "default_incident")
    messages = state.get("messages") or []
    last = messages[-1] if messages else None
    tool_calls = getattr(last, "tool_calls", None) or []
    if not tool_calls:
        return {"result": "No tool calls to approve."}
    human_approval = interrupt(thread_id)
    human_approval = str(human_approval).lower() if human_approval else "denied"
    logger.info("Tool approval received: %s (thread_id=%s)", human_approval, thread_id)
    out = {"human_approval": human_approval}
    if human_approval == "denied":
        out["result"] = "Investigation aborted by user (tool calls denied)."
    return out


def _operator_approval_route(state: dict) -> str:
    """If approved go to tools, else END."""
    if state.get("human_approval") == "approved":
        return "operator_tools"
    return "__end__"


def operator_tools_node(state: dict) -> dict:
    """Execute the full batch of tool_calls from the last AIMessage; append ToolMessages and loop back to agent."""
    messages = state.get("messages") or []
    last = messages[-1] if messages else None
    tool_calls = getattr(last, "tool_calls", None) or []
    tools_by_name = {t.name: t for t in OPERATOR_TOOLS}
    tool_messages = []
    for tc in tool_calls:
        name = tc.get("name", "")
        args = tc.get("args") or {}
        tid = tc.get("id", "")
        try:
            tool_fn = tools_by_name.get(name)
            if not tool_fn:
                content = f"Unknown tool: {name}"
            else:
                content = tool_fn.invoke(args)
            tool_messages.append(ToolMessage(content=str(content), tool_call_id=tid))
        except Exception as e:
            logger.exception("Tool %s failed", name)
            tool_messages.append(ToolMessage(content=f"Error: {e}", tool_call_id=tid))
    return {"messages": tool_messages}


def build_graph():
    workflow = StateGraph(InvestigationState)
    workflow.add_node("triage", triage_node)
    workflow.add_node("investigator", investigator_node)
    workflow.add_node("operator_agent", operator_agent_node)
    workflow.add_node("send_tool_approval_request", send_tool_approval_request_node)
    workflow.add_node("operator_approval", operator_approval_node)
    workflow.add_node("operator_tools", operator_tools_node)
    workflow.set_entry_point("triage")
    workflow.add_edge("triage", "investigator")
    workflow.add_edge("investigator", "operator_agent")
    workflow.add_conditional_edges("operator_agent", _operator_agent_route)
    workflow.add_edge("send_tool_approval_request", "operator_approval")
    workflow.add_conditional_edges("operator_approval", _operator_approval_route)
    workflow.add_edge("operator_tools", "operator_agent")
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
