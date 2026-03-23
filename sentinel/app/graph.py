"""LangGraph investigation workflow: triage → investigator (autonomous ReAct) → operator (HITL ReAct)."""
import logging
import operator
import os
from typing import Annotated, Sequence, TypedDict

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import StateGraph
from langgraph.types import interrupt
from langgraph.prebuilt import ToolNode
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.agents import get_investigator_model, get_operator_model
from app.tools import INVESTIGATOR_TOOLS, OPERATOR_TOOLS
from app.slack_client import send_tool_approval_request

logger = logging.getLogger(__name__)

TARGET_CONTAINER = "victim_service"
DB_URI = os.getenv("SENTINEL_DB_URI", "postgresql://user:pass@postgres:5432/sentinel_db")

class InvestigationState(TypedDict, total=False):
    alert_payload: dict
    alert_name: str
    container: str
    thread_id: str
    
    # Phase 1: Investigator (Autonomous RCA)
    investigator_messages: Annotated[Sequence[BaseMessage], operator.add]
    rca_report: str
    
    # Phase 2: Operator (Immediate Fix with HITL)
    operator_messages: Annotated[Sequence[BaseMessage], operator.add]
    human_approval: str
    result: str

def triage_node(state: dict) -> dict:
    payload = state.get("alert_payload", {})
    alerts = payload.get("alerts", [])
    thread_id = payload.get("fingerprint", "default_incident")
    if not alerts:
        return {"alert_name": "unknown", "container": TARGET_CONTAINER, "thread_id": thread_id}
    alert = alerts[0]
    labels = alert.get("labels", {})
    alert_name = labels.get("alertname", "unknown")
    container = labels.get("name") or labels.get("container") or TARGET_CONTAINER
    return {"alert_name": alert_name, "container": container, "thread_id": thread_id}

def investigator_agent_node(state: dict) -> dict:
    msgs = state.get("investigator_messages") or []
    if not msgs:
        alert_name = state.get("alert_name", "unknown")
        container = state.get("container", TARGET_CONTAINER)
        # Rigid, technical prompt for Slack compatibility and tool efficiency
        initial_msg = (
            f"Alert: {alert_name} on container: {container}.\n\n"
            f"You are the Investigator Agent. Conduct a deep Root Cause Analysis using traces, code, logs, and system stats.\n\n"
            f"CONSTRAINTS:\n"
            f"1. *SOURCE CODE*: When using 'read_docker_source_code', read a MAX of 100 lines per call. Focus on lines identified in traces.\n"
            f"2. *CONCISENESS*: Final report MUST be under 1500 characters. Summarize the logic bug briefly.\n"
            f"3. *FORMATTING*: Simple Slack mrkdwn only. *No headers (#)*. Use *BOLD CAPS* (single asterisks) for sections.\n"
            f"4. *REMEDIATION*: You cannot stop/modify internal functions or endpoints. Suggest only *container-level* actions from the Operator's list:\n"
            f"- restart_container: Reboots full service.\n"
            f"- update_container_resources: Scales CPU/Memory (e.g. mb=1500).\n"
            f"- rollback_container: Restores stable version.\n"
            f"- network_disconnect: Isolates the container.\n\n"
            f"GOAL: Output a short RCA and identify the 'Proposed Immediate Fix By Operator' for the container `{container}`."
        )
        msgs = [HumanMessage(content=initial_msg)]
        
    model = get_investigator_model()
    response = model.invoke(msgs)
    if not isinstance(response, AIMessage):
        response = AIMessage(content=str(response))
        
    out = {"investigator_messages": [response]}
    if not (getattr(response, "tool_calls", None) or []):
        out["rca_report"] = (response.content or "No RCA found.").strip()
    return out

def _investigator_route(state: dict) -> str:
    msgs = state.get("investigator_messages") or []
    if not msgs:
        return "__end__"
    last = msgs[-1]
    if getattr(last, "tool_calls", None):
        return "investigator_tools"
    return "operator_agent"

investigator_tools_node = ToolNode(INVESTIGATOR_TOOLS, messages_key="investigator_messages")


def operator_agent_node(state: dict) -> dict:
    msgs = state.get("operator_messages") or []
    if not msgs:
        rca_report = state.get("rca_report", "Unknown RCA")
        alert = state.get("alert_name", "unknown")
        # Prompt the operator to be the 'hands' for the investigator
        initial_msg = (
            f"RCA and Recommended Tactical Fix for {alert}:\n\n"
            f"{rca_report}\n\n"
            f"You are the Operator Agent (Infrastructure Executor). Look at the 'Proposed Tactical Fix' suggested by the Investigator. \n"
            f"Your ONLY job is to execute the appropriate remediation tool precisely as suggested. Do not argue or invent new values unless the proposal is technically impossible. "
            f"Call the tool(s) now to stabilize the container."
        )
        msgs = [HumanMessage(content=initial_msg)]
        
    model = get_operator_model()
    response = model.invoke(msgs)
    if not isinstance(response, AIMessage):
        response = AIMessage(content=str(response))
        
    out = {"operator_messages": [response]}
    if not (getattr(response, "tool_calls", None) or []):
        out["result"] = (response.content or "No tactical fix required.").strip()
    return out

def _operator_route(state: dict) -> str:
    msgs = state.get("operator_messages") or []
    if not msgs:
        return "__end__"
    last = msgs[-1]
    if getattr(last, "tool_calls", None):
        return "send_tool_approval"
    return "__end__"

def send_tool_approval_node(state: dict) -> dict:
    thread_id = state.get("thread_id", "default")
    container = state.get("container", TARGET_CONTAINER)
    rca = state.get("rca_report", "No RCA provided")
    msgs = state.get("operator_messages") or []
    last = msgs[-1] if msgs else None
    tool_calls = getattr(last, "tool_calls", None) or []
    if tool_calls:
        # We pass both the RCA report and the proposed tool_calls to Slack
        send_tool_approval_request(
            thread_id=thread_id, 
            container=container, 
            rca_report=rca, 
            tool_calls=tool_calls
        )
    return {}

def operator_approval_node(state: dict) -> dict:
    thread_id = state.get("thread_id", "default")
    msgs = state.get("operator_messages") or []
    last = msgs[-1] if msgs else None
    tool_calls = getattr(last, "tool_calls", None) or []
    if not tool_calls:
        return {"result": "No operator tools requested."}
        
    human_approval = interrupt(thread_id)
    human_approval = str(human_approval).lower() if human_approval else "denied"
    out = {"human_approval": human_approval}
    if human_approval == "denied":
        out["result"] = "Investigation finished. RCA delivered, but tactical tool execution was denied."
    return out

def _operator_approval_route(state: dict) -> str:
    if state.get("human_approval") == "approved":
        return "operator_tools"
    return "__end__"

operator_tools_node = ToolNode(OPERATOR_TOOLS, messages_key="operator_messages")


def build_graph():
    workflow = StateGraph(InvestigationState)
    workflow.add_node("triage", triage_node)
    
    # Phase 1: Investigator Loop (Autonomous)
    workflow.add_node("investigator_agent", investigator_agent_node)
    workflow.add_node("investigator_tools", investigator_tools_node)
    
    # Phase 2: Operator Loop (HITL)
    workflow.add_node("operator_agent", operator_agent_node)
    workflow.add_node("send_tool_approval", send_tool_approval_node)
    workflow.add_node("operator_approval", operator_approval_node)
    workflow.add_node("operator_tools", operator_tools_node)
    
    workflow.set_entry_point("triage")
    
    # Wiring Investigator (Autonomous Loop)
    workflow.add_edge("triage", "investigator_agent")
    workflow.add_conditional_edges("investigator_agent", _investigator_route)
    workflow.add_edge("investigator_tools", "investigator_agent")
    
    # Wiring Operator (Tactical Fix with Slack Gate)
    workflow.add_conditional_edges("operator_agent", _operator_route)
    workflow.add_edge("send_tool_approval", "operator_approval")
    workflow.add_conditional_edges("operator_approval", _operator_approval_route)
    workflow.add_edge("operator_tools", "__end__") # After tool execution, we end. Tactical fix done.
    
    try:
        pool = ConnectionPool(DB_URI, kwargs={"autocommit": True, "row_factory": dict_row})
        checkpointer = PostgresSaver(pool)
        checkpointer.setup()
        return workflow.compile(checkpointer=checkpointer)
    except Exception as e:
        logger.warning("Checkpointer failed, running without persistence: %s", e)
        return workflow.compile()

investigation_graph = build_graph()
