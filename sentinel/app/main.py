from fastapi import FastAPI
import logging

from app.celery_config import celery_app

app = FastAPI(title="Sentinel API")
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/webhook")
async def webhook(payload: dict):
    """Receives Alertmanager webhook POSTs when alerts fire or resolve."""
    logger.info("Webhook received: status=%s alerts=%d", payload.get("status"), len(payload.get("alerts", [])))
    celery_app.send_task("app.worker.run_investigation", args=[payload])
    return {"status": "received"}
