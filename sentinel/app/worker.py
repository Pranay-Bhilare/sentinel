"""
Celery worker. Picks up alert payloads from Redis queue and runs investigation.
"""
import logging

from langgraph.types import Command

from app.celery_config import celery_app
from app.graph import investigation_graph

logger = logging.getLogger(__name__)


@celery_app.task(bind=True)
def run_investigation(self, alert_payload: dict):
    """Process alert: run LangGraph workflow and remediate."""
    status = alert_payload.get("status", "")
    if status == "resolved":
        logger.info("Alert resolved, skipping investigation.")
        return {"status": "skipped", "reason": "resolved"}

    logger.info("Investigation started: status=%s alerts=%d", status, len(alert_payload.get("alerts", [])))
    thread_id = alert_payload.get("fingerprint", "default_incident")
    config = {"configurable": {"thread_id": thread_id}}

    result = investigation_graph.invoke(
        {"alert_payload": alert_payload},
        config=config,
    )

    if result.get("__interrupt__"):
        logger.info("Investigation paused, awaiting human approval (thread_id=%s)", thread_id)
        return {"status": "awaiting_approval", "thread_id": thread_id}

    logger.info("Investigation complete: %s", result.get("result", ""))
    return {"status": "done", "result": result.get("result", "")}


@celery_app.task(bind=True)
def resume_investigation(self, thread_id: str, decision: str):
    """Resume investigation after human approval/denial from Slack."""
    config = {"configurable": {"thread_id": thread_id}}
    logger.info("Resuming investigation thread_id=%s decision=%s", thread_id, decision)

    result = investigation_graph.invoke(
        Command(resume=decision),
        config=config,
    )

    logger.info("Investigation resumed and complete: %s", result.get("result", ""))
    return {"status": "done", "result": result.get("result", "")}
