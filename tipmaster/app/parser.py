from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import re


class CommandType(str, Enum):
    TIP = "tip"
    REGISTER = "register"
    BALANCE = "balance"
    STATS = "stats"
    LEADERBOARD = "leaderboard"
    HELP = "help"
    UNKNOWN = "unknown"


@dataclass
class Command:
    type: CommandType
    amount: Optional[float] = None
    target_username: Optional[str] = None
    wallet_address: Optional[str] = None
    boost: bool = False
    raw_text: str = ""


_XRPL_ADDRESS_RE = re.compile(r"\br[1-9A-HJ-NP-Za-km-z]{24,34}\b")
_USERNAME_RE = re.compile(r"@([A-Za-z0-9_.-]+)")
_AMOUNT_RE = re.compile(r"\b(\d+(?:\.\d+)?)\b")
_BOT_MENTION_RE = re.compile(r"@tipmaster\b", re.IGNORECASE)

MIN_TIP = 0.10
MAX_TIP = 100.0


def parse_command(text: str) -> Command:
    cleaned = _BOT_MENTION_RE.sub("", text).strip()
    tokens = cleaned.split()

    if not tokens:
        return Command(type=CommandType.HELP, raw_text=text)

    first = tokens[0].lower()

    if first == "register":
        rest = cleaned[len("register"):].strip()
        addr_match = _XRPL_ADDRESS_RE.search(rest)
        if addr_match:
            return Command(type=CommandType.REGISTER, wallet_address=addr_match.group(0), raw_text=text)
        return Command(type=CommandType.UNKNOWN, raw_text=text)

    if first == "balance":
        return Command(type=CommandType.BALANCE, raw_text=text)

    if first in ("stats", "history"):
        return Command(type=CommandType.STATS, raw_text=text)

    if first in ("leaderboard", "lb", "top"):
        return Command(type=CommandType.LEADERBOARD, raw_text=text)

    if first == "help":
        return Command(type=CommandType.HELP, raw_text=text)

    if first == "boost":
        rest = cleaned[len("boost"):].strip()
        cmd = _parse_tip(rest, text)
        if cmd.type == CommandType.TIP:
            cmd.boost = True
        return cmd

    if first == "tip":
        rest = cleaned[len("tip"):].strip()
        return _parse_tip(rest, text)

    return _parse_tip(cleaned, text)


def _parse_tip(text: str, raw_text: str) -> Command:
    amount_match = _AMOUNT_RE.search(text)
    if not amount_match:
        return Command(type=CommandType.UNKNOWN, raw_text=raw_text)

    try:
        amount = float(amount_match.group(1))
    except ValueError:
        return Command(type=CommandType.UNKNOWN, raw_text=raw_text)

    if amount < MIN_TIP or amount > MAX_TIP:
        return Command(type=CommandType.UNKNOWN, amount=amount, raw_text=raw_text)

    usernames = _USERNAME_RE.findall(text)
    targets = [u for u in usernames if u.lower() != "tipmaster"]

    if not targets:
        return Command(type=CommandType.UNKNOWN, raw_text=raw_text)

    return Command(type=CommandType.TIP, amount=amount, target_username=targets[0], raw_text=raw_text)
