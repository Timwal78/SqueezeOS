import os
import sys
from dotenv import load_dotenv

# Add current dir to path
sys.path.append(os.getcwd())

from discord_alerts import DiscordAlerts

def test_signal():
    load_dotenv()
    discord = DiscordAlerts()
    if discord.enabled:
        print("Sending Startup Signal to Discord...")
        discord.fire_startup_alert("Tradier-Live | Alpaca-Ready | Polygon-Verified", 450)
        print("Signal Sent. Check your Discord!")
    else:
        print("Discord not enabled in .env")

if __name__ == "__main__":
    test_signal()
