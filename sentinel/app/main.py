import hashlib
import hmac
import json
import logging
import os
from urllib.parse import parse_qs

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.celery_config import celery_app

app = FastAPI(title="Sentinel API")
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SLACK_SIGNING_SECRET = os.getenv("SLACK_SIGNING_SECRET", "")


def _verify_slack_signature(body: bytes, signature: str, timestamp: str) -> bool:
    if not SLACK_SIGNING_SECRET:
        logger.warning("SLACK_SIGNING_SECRET not set, skipping signature verification")
        return True
    sig_basestring = f"v0:{timestamp}:{body.decode('utf-8')}"
    computed = "v0=" + hmac.new(
        SLACK_SIGNING_SECRET.encode(),
        sig_basestring.encode(),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(computed, signature)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/webhook")
async def webhook(payload: dict):
    """Receives Alertmanager webhook POSTs when alerts fire or resolve."""
    logger.info("Webhook received: status=%s alerts=%d", payload.get("status"), len(payload.get("alerts", [])))
    celery_app.send_task("app.worker.run_investigation", args=[payload])
    return {"status": "received"}


@app.post("/slack/interactive")
async def slack_interactive(request: Request):
    """Handle Slack button clicks (Approve/Deny) for HITL."""
    body = await request.body()
    headers = request.headers
    signature = headers.get("x-slack-signature", "")
    timestamp = headers.get("x-slack-request-timestamp", "")

    if not _verify_slack_signature(body, signature, timestamp):
        return JSONResponse(
            content={"status": "error", "message": "Invalid signature"},
            status_code=401,
        )

    form_data = parse_qs(body.decode("utf-8"))
    payload_str = form_data.get("payload", [None])[0]
    if not payload_str:
        return JSONResponse(
            content={"status": "error", "message": "Missing payload"},
            status_code=400,
        )

    data = json.loads(payload_str)
    actions = data.get("actions", [])
    if not actions:
        return JSONResponse(
            content={"status": "error", "message": "No action"},
            status_code=400,
        )

    try:
        value = json.loads(actions[0].get("value", "{}"))
    except json.JSONDecodeError:
        return JSONResponse(
            content={"status": "error", "message": "Invalid value"},
            status_code=400,
        )

    thread_id = value.get("thread_id")
    decision = value.get("decision", "denied")

    if not thread_id:
        return JSONResponse(
            content={"status": "error", "message": "Missing thread_id"},
            status_code=400,
        )

    celery_app.send_task("app.worker.resume_investigation", args=[thread_id, decision])
    logger.info("Slack approval received: thread_id=%s decision=%s", thread_id, decision)

    return {"status": "ok", "message": "Resuming investigation..."}
