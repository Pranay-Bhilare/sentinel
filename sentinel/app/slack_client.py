"""Slack client for HITL: single approval at tool execution (Operator tool_calls)."""
import json
import logging
import os

import httpx

logger = logging.getLogger(__name__)

SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_CHANNEL_ID = os.getenv("SLACK_CHANNEL_ID")


def send_tool_approval_request(
    thread_id: str,
    container: str,
    tool_calls: list[dict],
) -> bool:
    """Send one Slack message per operator step listing ALL proposed tool_calls. Single HITL boundary before execution."""
    if not SLACK_BOT_TOKEN or not SLACK_CHANNEL_ID:
        logger.warning("SLACK_BOT_TOKEN or SLACK_CHANNEL_ID not set, skipping Slack notification")
        return False

    lines = []
    for tc in tool_calls:
        name = tc.get("name", "?")
        args = tc.get("args", {})
        args_str = ", ".join(f"{k}={repr(v)}" for k, v in (args or {}).items())
        lines.append(f"• `{name}({args_str})`")

    tool_text = "\n".join(lines) if lines else "No tool calls"

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Operator wants to run*\n*Container:* `{container}`\n\n{tool_text}",
            },
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "Approve or deny these tool calls:"},
        },
        {
            "type": "actions",
            "block_id": "tool_approval_actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Approve", "emoji": True},
                    "style": "primary",
                    "value": json.dumps({"thread_id": thread_id, "decision": "approved"}),
                    "action_id": "approve_tool_calls",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Deny", "emoji": True},
                    "value": json.dumps({"thread_id": thread_id, "decision": "denied"}),
                    "action_id": "deny_tool_calls",
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
        logger.info("Slack tool approval request sent for thread_id=%s", thread_id)
        return True
    except Exception as e:
        logger.exception("Failed to send Slack tool approval request: %s", e)
        return False
