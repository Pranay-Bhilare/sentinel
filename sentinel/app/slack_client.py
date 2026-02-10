"""Slack client for HITL approval requests."""
import json
import logging
import os

import httpx

logger = logging.getLogger(__name__)

SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_CHANNEL_ID = os.getenv("SLACK_CHANNEL_ID")


def send_approval_request(
    thread_id: str,
    container: str,
    recommendation: str,
    alert_name: str,
    stats_summary: str,
) -> bool:
    """Send Slack Block Kit message with Approve/Deny buttons."""
    if not SLACK_BOT_TOKEN or not SLACK_CHANNEL_ID:
        logger.warning("SLACK_BOT_TOKEN or SLACK_CHANNEL_ID not set, skipping Slack notification")
        return False

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Critical Action Required*\n*Issue:* {alert_name}\n*Container:* `{container}`\n*Stats:* {stats_summary}\n*Proposed Fix:* {recommendation}",
            },
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "Approve or deny this remediation action:"},
        },
        {
            "type": "actions",
            "block_id": "approval_actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Approve", "emoji": True},
                    "style": "primary",
                    "value": json.dumps({"thread_id": thread_id, "decision": "approved"}),
                    "action_id": "approve_restart",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Deny", "emoji": True},
                    "value": json.dumps({"thread_id": thread_id, "decision": "denied"}),
                    "action_id": "deny_restart",
                },
            ],
        },
    ]

    try:
        resp = httpx.post(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}", "Content-Type": "application/json"},
            json={"channel": SLACK_CHANNEL_ID, "blocks": blocks},
            timeout=10.0,
        )
        if not resp.is_success:
            logger.error("Slack API error: %s %s", resp.status_code, resp.text)
            return False
        data = resp.json()
        if not data.get("ok"):
            logger.error("Slack API not ok: %s", data)
            return False
        logger.info("Slack approval request sent for thread_id=%s", thread_id)
        return True
    except Exception as e:
        logger.exception("Failed to send Slack approval request: %s", e)
        return False
