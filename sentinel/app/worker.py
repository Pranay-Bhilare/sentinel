"""
Celery worker. Picks up alert payloads from Redis queue.
Investigation logic (LangGraph) added in a later step.
"""
import logging
from celery import Celery

celery_app = Celery("sentinel", broker="redis://redis:6379/0")
logger = logging.getLogger(__name__)


@celery_app.task(bind=True)
def run_investigation(self, alert_payload: dict):
    """Process alert from webhook. LangGraph workflow added later."""
    logger.info("Investigation started: status=%s alerts=%d", alert_payload.get("status"), len(alert_payload.get("alerts", [])))
    for alert in alert_payload.get("alerts", []):
        logger.info("  Processing: %s - %s", alert.get("labels", {}).get("alertname"), alert.get("annotations", {}).get("summary"))
    return {"status": "queued", "fingerprint": alert_payload.get("fingerprint", "unknown")}
