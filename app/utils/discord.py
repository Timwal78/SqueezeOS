import os
import aiohttp
import logging
from datetime import datetime

logger = logging.getLogger("argus.discord")

# System channel — MUST be set in .env. No hardcoded tokens in source.
WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_SYSTEM", "")

async def send_system_alert(title: str, message: str, color: int = 0x3498db):
    """Sends a system-level alert to the Discord infrastructure channel."""
    if not WEBHOOK_URL:
        return

    payload = {
        "embeds": [{
            "title": f"🛡️ {title}",
            "description": message,
            "color": color,
            "footer": {
                "text": "Argus Omega • ScriptMasterLabs™"
            },
            "timestamp": datetime.utcnow().isoformat()
        }]
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(WEBHOOK_URL, json=payload, timeout=10) as resp:
                if resp.status not in (200, 204):
                    logger.error(f"Failed to send Discord alert: {resp.status}")
    except Exception as e:
        logger.error(f"Discord alerting error: {e}")
