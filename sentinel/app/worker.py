"""
Celery worker. Picks up alert payloads from Redis queue and runs investigation.
"""
import logging
from celery import Celery

from app.graph import investigation_graph

celery_app = Celery("sentinel", broker="redis://redis:6379/0")
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

    result = investigation_graph.invoke(
        {"alert_payload": alert_payload},
        config={"configurable": {"thread_id": thread_id}},
    )

    logger.info("Investigation complete: %s", result.get("result", ""))
    return {"status": "done", "result": result.get("result", "")}
