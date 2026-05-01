"""
SQUEEZE OS v5.0 — Discord Webhook Alerts
Posts squeeze signals AND detailed options flow alerts to Discord.

Configure in .env:
  DISCORD_WEBHOOK_SQUEEZE=https://discord.com/api/webhooks/...
  DISCORD_WEBHOOK_FLOW=https://discord.com/api/webhooks/...
  DISCORD_WEBHOOK_ALL=https://discord.com/api/webhooks/...  (catch-all)
  DISCORD_ALERT_MIN_SCORE=55  (minimum squeeze score to alert)
  DISCORD_FLOW_MIN_SCORE=40   (minimum options unusual score to alert)
"""
import os
import time
import logging
import requests
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter
from datetime import datetime
from typing import List, Dict

logger = logging.getLogger(__name__)


def _llm_commentary(symbol: str, data: dict, timeout: int = 15) -> str:
    """Non-blocking LLM commentary — returns empty string on any failure."""
    try:
        from free_llm import get_llm
        llm = get_llm()
        return llm.analyze_signal(symbol, data)
    except Exception:
        return ""


class DiscordAlerts:

    def __init__(self):
        self.webhook_squeeze = os.environ.get('DISCORD_WEBHOOK_SQUEEZE', '')
        self.webhook_flow = os.environ.get('DISCORD_WEBHOOK_FLOW', '') or os.environ.get('DISCORD_WEBHOOK_OPTIONS', '')
        self.webhook_all = os.environ.get('DISCORD_WEBHOOK_ALL', '') or os.environ.get('DISCORD_WEBHOOK_URL', '')
        self.webhook_beast = os.environ.get('DISCORD_WEBHOOK_BEAST', '')
        self.webhook_free = os.environ.get('DISCORD_WEBHOOK_FREE', '')
        self.webhook_pro = os.environ.get('DISCORD_WEBHOOK_PRO', '')
        self.webhook_premium = os.environ.get('DISCORD_WEBHOOK_PREMIUM', '')
        self.min_squeeze_score = int(os.environ.get('DISCORD_ALERT_MIN_SCORE', '40'))
        self.min_flow_score = int(os.environ.get('DISCORD_FLOW_MIN_SCORE', '15'))
        self.cooldown = {}
        self.cooldown_sec = 300
        self.rate_limit_until = 0 # Type: int
        self.dead_webhooks = set()
        
        # ── Robust Session for SSL Resilience ──
        self.session = requests.Session()
        retries = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[500, 502, 503, 504],
            raise_on_status=False
        )
        # Use more robust adapter settings for SSL stability
        adapter = HTTPAdapter(max_retries=retries, pool_connections=10, pool_maxsize=10)
        self.session.mount('https://', adapter)

        active = []
        if self.webhook_squeeze: active.append('squeeze')
        if self.webhook_flow: active.append('flow')
        if self.webhook_all: active.append('all')
        if self.webhook_beast: active.append('beast')
        if active:
            logger.info(f"[DISCORD] Webhooks: {', '.join(active)} | squeeze>={self.min_squeeze_score} | flow>={self.min_flow_score}")
        else:
            logger.info("[DISCORD] No webhooks configured")

    @property
    def enabled(self):
        return bool(self.webhook_squeeze or self.webhook_flow or self.webhook_all or self.webhook_beast)

    def _can_alert(self, key):
        now = time.time()
        if now < self.rate_limit_until:
            return False
        last = self.cooldown.get(key, 0)
        return (now - last) >= self.cooldown_sec

    def _mark(self, key):
        self.cooldown[key] = time.time()

    def _post(self, url, payload):
        if not url or url in self.dead_webhooks:
            return
        
        # TRACE: Log attempt
        title = payload.get('embeds', [{}])[0].get('title', 'NO TITLE')
        # Diagnostic: Masked URL to verify token loading
        masked = url[:35] + "..." + url[-12:]
        logger.info(f"[DISCORD] Attempting alert: {title} | Target: {masked}")
        
        # Check if we should bypass proxies for Discord (often helps with local network issues)
        trust_env = os.environ.get('DISCORD_TRUST_ENV', 'True').lower() == 'true'
        
        try:
            # Use pooled session for SSL stability
            r = self.session.post(url, json=payload, timeout=15, proxies={"http": None, "https": None} if not trust_env else None)
            logger.info(f"[DISCORD] Response: {r.status_code}")
            
            if r.status_code == 404:
                logger.error(f"❌ [DISCORD ACTION REQUIRED] 404 Unknown Webhook. Adding to dead-list: {masked}")
                self.dead_webhooks.add(url)
            elif r.status_code == 429:
                retry_after = r.json().get('retry_after', 5)
                self.rate_limit_until = int(time.time() + retry_after)
                logger.warning(f"[DISCORD] Rate limited {retry_after}s")
            elif r.status_code not in (200, 204):
                logger.warning(f"[DISCORD] {r.status_code}: {r.text[:200]}")
                
        except requests.exceptions.ProxyError as pe:
            logger.error(f"[DISCORD] Proxy Error: {pe} | Try adding DISCORD_TRUST_ENV=False to your .env")
        except requests.exceptions.SSLError as se:
            logger.error(f"[DISCORD] SSL Critical: {se} | Hint: Check environment SSL or use a proxy.")
        except requests.exceptions.ConnectionError as ce:
            logger.error(f"[DISCORD] Connection Error: {ce}")
        except Exception as e:
            logger.error(f"[DISCORD] Unexpected Error: {e}")

    def send_alert(self, title: str, message: str, color: int = 0x00FF00):
        """Generic alert for webhooks and system events."""
        if not self.enabled:
            return
        url = self.webhook_all or self.webhook_squeeze or self.webhook_flow
        if not url:
            return
            
        payload = {
            "embeds": [{
                "title": title,
                "description": message,
                "color": color,
                "footer": {"text": f"Squeeze OS v5.0 | {datetime.now().strftime('%I:%M %p ET')}"},
                "timestamp": datetime.utcnow().isoformat(),
            }]
        }
        self._post(url, payload)

    def send_tiered_alert(self, title: str, message: str, tier: str = 'premium', color: int = 0x00FF00):
        """Routes alerts based on membership tier (free/pro/premium)."""
        if not self.enabled:
            return
            
        tier = tier.lower()
        if tier == 'free':
            url = self.webhook_free or self.webhook_squeeze or self.webhook_all
        elif tier == 'pro':
            url = self.webhook_pro or self.webhook_squeeze or self.webhook_all
        else:
            url = self.webhook_premium or self.webhook_squeeze or self.webhook_all
            
        if not url:
            return
            
        payload = {
            "embeds": [{
                "title": title,
                "description": message,
                "color": color,
                "footer": {"text": f"SML Institutional | Tier: {tier.upper()} | {datetime.now().strftime('%I:%M %p ET')}"},
                "timestamp": datetime.utcnow().isoformat(),
            }]
        }
        self._post(url, payload)

    # ══════════════════════════════════════════════════════════
    # SQUEEZE ALERTS
    # ══════════════════════════════════════════════════════════

    def fire_squeeze_alerts(self, scan_results: List[Dict]):
        if not self.enabled:
            return

        for item in scan_results:
            score = item.get('squeeze_score', 0)
            sym = item.get('symbol', '')
            if score < self.min_squeeze_score:
                continue
            if not self._can_alert(f'sq_{sym}'):
                continue

            # ── Tier-Based Routing ──────────────────────────────────────────
            tier = item.get('tier', 'premium').lower()
            if tier == 'free':
                url = self.webhook_free or self.webhook_squeeze or self.webhook_all
            elif tier == 'pro':
                url = self.webhook_pro or self.webhook_squeeze or self.webhook_all
            else:
                url = self.webhook_premium or self.webhook_squeeze or self.webhook_all

            if not url:
                continue

            # Color and Emoji by DIRECTION and INTENSITY
            direction = item.get('direction', 'NEUTRAL').upper()
            if direction == 'BULLISH':
                color = 0x00FF88 # Institutional Green
                emoji = "🟢" if score < 75 else "🔥"
            elif direction == 'BEARISH':
                color = 0xFF4444 # Institutional Red
                emoji = "🔴" if score < 75 else "🔥"
            else:
                color = 0x00BFFF # Institutional Blue
                emoji = "📊"

            # Intensity override for MOASS potential
            if score >= 85:
                emoji = "🚨" # Critical Alert

            tier = item.get('tier', '')
            tier_str = f" [{tier}]" if tier else ""

            # Build module breakdown string from analysis_components
            comps = item.get('analysis_components', {})
            if comps:
                modules = (
                    f"VOL:{comps.get('volume_profile', 0):.0f} "
                    f"CMP:{comps.get('compression', 0):.0f} "
                    f"MOM:{comps.get('momentum', 0):.0f} "
                    f"VWP:{comps.get('vwap_position', 0):.0f} "
                    f"RSI:{comps.get('rsi_engine', 0):.0f} "
                    f"MFI:{comps.get('money_flow', 0):.0f} "
                    f"STR:{comps.get('price_structure', 0):.0f} "
                    f"TRD:{comps.get('trend_alignment', 0):.0f}"
                )
            else:
                modules = "—"

            # ── Institutional Rank Mapping ──
            # ALPHA = Small Cap Momentum ($1-$15)
            # BETA = Mid Cap ($15-$150)
            # BENCHMARK = Large/Mega Cap (Blue Chips)
            current_price = item.get('price', 0)
            if 1.0 <= current_price <= 15.0:
                rank_label = "RANK: ALPHA ⭐⭐ (SML Small-Cap)"
            elif current_price > 150.0 or item.get('is_mega'):
                rank_label = "RANK: BENCHMARK 🏢 (Blue Chip)"
            else:
                rank_label = "RANK: BETA ⭐ (Mid-Cap)"

            embed = {
                "embeds": [{
                    "title": f"🚨 ECHO-SQUEEZE: {sym} ({item.get('squeeze_level', 'SIGNAL')})",
                    "color": color,
                    "fields": [
                        {"name": "🧠 INTEL BREADCRUMB", "value": f"**Rank**: `{rank_label}` | **Score**: `{score}/100`", "inline": False},
                        {"name": "📊 PRIMARY PROJECTION", "value": f"**Direction**: `{item.get('direction', '—')}`\n**Rec**: `{item.get('recommendation', '—')}`", "inline": True},
                        {"name": "⏳ TIME HORIZON", "value": f"**Price**: `${item.get('price', 0):.2f}`\n**Change**: `{item.get('changePct', 0):+.1f}%`", "inline": True},
                        {"name": "🌀 ANALYSIS MODULES", "value": f"`{modules}`", "inline": False},
                    ],
                    "footer": {"text": f"Squeeze OS v5.0 | Institutional Intelligence | {datetime.now().strftime('%I:%M %p ET')}"},
                    "timestamp": datetime.utcnow().isoformat(),
                }]
            }
            ai_note = _llm_commentary(sym, item)
            if ai_note:
                embed["embeds"][0]["fields"].append({"name": "🤖 AI ANALYST", "value": ai_note, "inline": False})
            self._post(url, embed)
            self._mark(f'sq_{sym}')
            time.sleep(2.0)

    # ══════════════════════════════════════════════════════════
    # OPTIONS FLOW ALERTS — FULL CONTRACT DETAIL
    # Each contract gets its own rich embed with:
    #   Strike, Expiry, DTE, Type, Price, Bid/Ask, Spread,
    #   Volume, OI, Vol/OI, IV, Delta, Gamma, Theta,
    #   Sentiment, Flags, Source
    # ══════════════════════════════════════════════════════════

    def fire_flow_alerts(self, flow_results: List[Dict]):
        if not self.enabled:
            return

        qualifying = [f for f in flow_results if f.get('unusual_score', 0) >= self.min_flow_score]
        if not qualifying:
            return

        # Beast Mode: Group contracts by ticker to prevent Discord spam
        ticker_groups = {}
        for alert in qualifying:
            sym = alert.get('symbol', '?')
            if sym not in ticker_groups:
                ticker_groups[sym] = []
            ticker_groups[sym].append(alert)

        sent = 0
        for sym, contracts in ticker_groups.items():
            # Use the highest-scored contract as the lead
            contracts.sort(key=lambda x: x.get('unusual_score', 0), reverse=True)
            lead = contracts[0]

            # ── Tier-Based Routing ──────────────────────────────────────────
            # Flow alerts default to Premium unless marked otherwise
            tier = lead.get('tier', 'premium').lower()
            if tier == 'free':
                url = self.webhook_free or self.webhook_flow or self.webhook_all
            elif tier == 'pro':
                url = self.webhook_pro or self.webhook_flow or self.webhook_all
            else:
                url = self.webhook_premium or self.webhook_flow or self.webhook_all

            if not url:
                continue
            
            key = f"flow_{sym}_batch"
            if not self._can_alert(key):
                continue

            opt_type = lead.get('type', 'CALL')
            strike = lead.get('strike', 0)
            expiry_fmt = lead.get('expiry_formatted', lead.get('expiry', '?'))
            dte = lead.get('days_to_expiry', 0)
            price = lead.get('price', 0)
            bid = lead.get('bid', 0)
            ask = lead.get('ask', 0)
            volume = lead.get('volume', 0)
            oi = lead.get('open_interest', 0)
            vol_oi = lead.get('vol_oi_ratio', 0)
            iv = lead.get('implied_volatility', 0)
            delta = lead.get('delta', 0)
            gamma = lead.get('gamma', 0)
            theta = lead.get('theta', 0)
            score = lead.get('unusual_score', 0)
            sentiment = lead.get('sentiment', 'NEUTRAL')
            flags = lead.get('flags', [])
            priority = lead.get('alert_priority', 'LOW')
            source = lead.get('source', '?')

            # Color by sentiment + priority
            is_oi_spike = lead.get('is_oi_spike', False)
            is_block = lead.get('is_block', False)
            is_sweep = lead.get('is_sweep', False)

            if is_oi_spike and is_sweep:
                color, title_emoji = 0xFF00FF, "💎" # SWEEP SPIKE (Magenta)
            elif is_oi_spike:
                color, title_emoji = 0xFF8C00, "🌋" # OI SPIKE (Orange)
            elif is_block:
                color, title_emoji = 0x00BFFF, "🐋" # BLOCK (Blue)
            elif priority == 'EXTREME':
                color, title_emoji = 0xFF4444, "🚨" # Institutional Red
            elif sentiment == 'BULLISH':
                color, title_emoji = 0x00FF88, "🔔" # Institutional Green
            elif sentiment == 'BEARISH':
                color, title_emoji = 0xFF4444, "🔔" # Institutional Red
            else:
                color, title_emoji = 0x00BFFF, "🔔" # Institutional Blue

            sent_emoji = "🟢" if sentiment == 'BULLISH' else "🔴" if sentiment == 'BEARISH' else "⚪"

            # Contract line
            sweep = lead.get('sweep_label', '')
            if strike > 0:
                contract = f"{sym} ${strike:.2f} {sweep if sweep else opt_type}"
            else:
                contract = f"{sym} STOCK FLOW"

            expiry_line = f"{expiry_fmt} ({dte}DTE)" if dte > 0 else expiry_fmt
            spread = f"${(ask - bid):.2f}" if ask > bid else "—"
            
            # Highlight institutional flags
            tags = []
            if is_oi_spike: tags.append("🌋 **OI SPIKE**")
            if is_block: tags.append("🐋 **BLOCK**")
            if is_sweep: tags.append("⚡ **SWEEP**")
            tag_line = " | ".join(tags) if tags else "—"

            # Build actionable recommendation line
            if sentiment == 'BULLISH' and opt_type == 'CALL':
                rec_action = f"🟢 BUY {sym} ${strike:.2f} CALL — Exp {expiry_fmt}"
            elif sentiment == 'BEARISH' and opt_type == 'PUT':
                rec_action = f"🔴 BUY {sym} ${strike:.2f} PUT — Exp {expiry_fmt}"
            elif sentiment == 'BEARISH' and opt_type == 'CALL':
                rec_action = f"🔴 SELL {sym} ${strike:.2f} CALL — Exp {expiry_fmt}"
            elif sentiment == 'BULLISH' and opt_type == 'PUT':
                rec_action = f"🟢 SELL {sym} ${strike:.2f} PUT — Exp {expiry_fmt}"
            else:
                rec_action = f"👁️ WATCH {sym} ${strike:.2f} {opt_type} — Exp {expiry_fmt}"

            embed = {
                "embeds": [{
                    "title": f"{title_emoji} {sent_emoji} {contract}",
                    "description": f"**{rec_action}**",
                    "color": color,
                    "fields": [
                        {"name": "Expiry", "value": expiry_line, "inline": True},
                        {"name": "Sentiment", "value": f"**{sentiment}**", "inline": True},
                        {"name": "Score", "value": f"**{score}**/100", "inline": True},

                        {"name": "💰 Price", "value": f"${price:.2f}", "inline": True},
                        {"name": "💵 Premium", "value": f"**${lead.get('premium', 0):,.0f}**", "inline": True},
                        {"name": "📊 Volume", "value": f"**{volume:,}**", "inline": True},

                        {"name": "📈 IV", "value": f"**{iv:.0%}**" if iv > 0 else "—", "inline": True},
                        {"name": "Vol/OI", "value": f"**{vol_oi:.1f}x**" if vol_oi > 0 else "—", "inline": True},
                        {"name": "Δ Delta", "value": f"{delta:.3f}" if delta != 0 else "—", "inline": True},
                        {"name": "🐋 HEAT TYPE", "value": tag_line, "inline": False},
                    ],
                    "footer": {"text": f"Squeeze OS v5.0 | Institutional Flow | {datetime.now().strftime('%I:%M %p ET')}"},
                    "timestamp": datetime.utcnow().isoformat(),
                }]
            }

            self._post(url, embed)
            self._mark(key)
            sent += 1
            time.sleep(2.0)

        # ── Summary after individual contract alerts ──
        if sent > 0:
            total = len(flow_results)
            bullish = sum(1 for f in qualifying if f.get('sentiment') == 'BULLISH')
            bearish = sum(1 for f in qualifying if f.get('sentiment') == 'BEARISH')

            sym_counts = {}
            for f in qualifying:
                s = f.get('symbol', '?')
                sym_counts[s] = sym_counts.get(s, 0) + 1
            top_syms = sorted(sym_counts.items(), key=lambda x: x[1], reverse=True)
            hot_list = " | ".join([f"**{s}** ({c})" for s, c in top_syms])

            self._post(url, {
                "embeds": [{
                    "title": "📋 Options Flow Summary",
                    "color": 0x00BFFF,
                    "fields": [
                        {"name": "Total Unusual", "value": str(total), "inline": True},
                        {"name": "🟢 Bullish", "value": str(bullish), "inline": True},
                        {"name": "🔴 Bearish", "value": str(bearish), "inline": True},
                        {"name": "Sent This Cycle", "value": str(sent), "inline": True},
                        {"name": "Min Score", "value": str(self.min_flow_score), "inline": True},
                        {"name": "🔥 Hottest", "value": hot_list or "—", "inline": False},
                    ],
                    "footer": {"text": "Next scan in ~3 min"},
                }]
            })

    # ══════════════════════════════════════════════════════════
    # SYSTEM ALERTS
    # ══════════════════════════════════════════════════════════

    def fire_trade_alert(self, symbol: str, price: float, score: float, sentiment: str, daily_range: float):
        """Dynamic Trade Alert: Calculated from intraday volatility."""
        if not self.enabled: return
        url = self.webhook_squeeze or self.webhook_all
        if not url: return
            
        if not self._can_alert(f'trade_{symbol}'): return

        # DYNAMIC CALCULATION: No hardcoded multipliers
        # We use the actual High-Low range as the unit of risk
        rng = daily_range if daily_range > 0 else (price * 0.02) # Fallback to 2% if range is 0
        
        if sentiment == 'BULLISH':
            target = price + (2.0 * rng)
            stop = price - (0.5 * rng)
            dir_label = "LONG"
            color = 0x00FF88
        else:
            target = price - (2.0 * rng)
            stop = price + (0.5 * rng)
            dir_label = "SHORT"
            color = 0xFF4444

        rr = abs(target - price) / abs(price - stop) if abs(price - stop) != 0 else 4.0
        conf = int(score) if score <= 100 else 99

        embed = {
            "embeds": [{
                "title": "🚨 TRADE ALERT 🚨",
                "description": (
                    f"**Ticker**: {symbol}\n"
                    f"**Signal**: Trade Idea: **{dir_label}** @ **${price:,.2f}**. "
                    f"Target: **${target:,.2f}**. Stop: **${stop:,.2f}**. "
                    f"R:R: **{rr:.1f}:1**. Confidence: **{conf}%**"
                ),
                "color": color,
                "footer": {"text": f"Time: {datetime.now().strftime('%m/%d/%Y, %H:%M:%S %p')}"}
            }]
        }
        self._post(url, embed)
        self._mark(f'trade_{symbol}')

    def fire_startup_alert(self, provider_info: str, symbol_count: int):
        url = self.webhook_all or self.webhook_squeeze or self.webhook_flow
        if not url:
            return
        self._post(url, {
            "embeds": [{
                "title": "🚀 Squeeze OS v5.0 — ONLINE",
                "description": f"Scanner active with **{symbol_count}** symbols\nProviders: {provider_info}",
                "color": 0x00FF00,
                "footer": {"text": datetime.now().strftime('%I:%M %p ET')},
            }]
        })

    def fire_schwab_connected_alert(self):
        url = self.webhook_all or self.webhook_squeeze
        if not url:
            return
        self._post(url, {
            "embeds": [{
                "title": "✅ Schwab API Connected",
                "description": "Real-time quotes + full options chains active.\nGreeks • IV • Volume • OI • Bid/Ask all flowing.",
                "color": 0x00FF00,
            }]
        })

    # ══════════════════════════════════════════════════════════
    # GAMMA FLOW FUSION ALERTS
    # ══════════════════════════════════════════════════════════

    def fire_gamma_alert(self, signal_dict: Dict):
        """Send a Gamma/Flow Fusion signal to Discord."""
        if not self.enabled:
            return
        url = self.webhook_flow or self.webhook_all
        if not url:
            return

        ticker = signal_dict.get('ticker', '?')
        sig_type = signal_dict.get('signal_type', 'unknown')
        key = f'gex_{ticker}_{sig_type}'
        if not self._can_alert(key):
            return

        strike = signal_dict.get('strike', 0)
        spot = signal_dict.get('spot_price', 0)
        urgency = signal_dict.get('urgency_score', 0)
        confidence = signal_dict.get('confidence', 'low')
        expected_move = signal_dict.get('expected_move', 0)

        if sig_type == 'gamma_squeeze_setup':
            color = 0xFF0000
            emoji = "🔥"
            label = "GAMMA SQUEEZE SETUP"
            desc = f"**{ticker}** is in SHORT GAMMA territory with heavy CALL buying at **${strike:.2f}**. Dealers must BUY as price rises — explosive potential."
        elif sig_type == 'gamma_support_bounce':
            color = 0x00FF88
            emoji = "🛡️"
            label = "GAMMA SUPPORT BOUNCE"
            desc = f"**{ticker}** is testing a high-GEX support wall at **${strike:.2f}**. Dealer hedging should provide buying pressure."
        elif sig_type == 'gamma_flip':
            color = 0xFF6600
            emoji = "⚡"
            label = "GAMMA REGIME FLIP"
            desc = f"**{ticker}** gamma regime has FLIPPED at **${strike:.2f}**. Dealer hedging dynamics have reversed — volatility regime change."
        elif sig_type == 'pin_risk':
            color = 0xFFFF00
            emoji = "📌"
            label = "PIN RISK DETECTED"
            desc = f"**{ticker}** is pinned near **${strike:.2f}** (max OI strike) with 0-2 DTE options expiring. Expect magnetic pull toward this level."
        else:
            color = 0x00BFFF
            emoji = "📉"
            label = sig_type.replace('_', ' ').upper()
            desc = f"**{ticker}** GEX signal at **${strike:.2f}**."

        embed = {
            "embeds": [{
                "title": f"{emoji} {label} — {ticker}",
                "description": desc,
                "color": color,
                "fields": [
                    {"name": "Spot Price", "value": f"${spot:.2f}", "inline": True},
                    {"name": "Signal Strike", "value": f"${strike:.2f}", "inline": True},
                    {"name": "Urgency", "value": f"**{urgency:.0f}**/100", "inline": True},
                    {"name": "Confidence", "value": f"**{confidence.upper()}**", "inline": True},
                    {"name": "Expected Move", "value": f"{expected_move:.1%}", "inline": True},
                ],
                "footer": {"text": f"Squeeze OS v5.0 | GEX Engine | {datetime.now().strftime('%I:%M %p ET')}"},
                "timestamp": datetime.utcnow().isoformat(),
            }]
        }
        self._post(url, embed)
        self._mark(key)

    # ══════════════════════════════════════════════════════════
    # REGIME CHANGE ALERTS
    # ══════════════════════════════════════════════════════════

    def fire_regime_alert(self, old_regime: str, new_regime: str, regime_data: Dict):
        """Fire Discord when RMRE regime state changes."""
        if not self.enabled:
            return
        url = self.webhook_all or self.webhook_squeeze
        if not url:
            return
        key = f'regime_{new_regime}'
        if not self._can_alert(key):
            return

        modifier = regime_data.get('beast_modifier', 0)
        bull_pct = round(regime_data.get('bull_probability', 0.5) * 100)
        fractal = regime_data.get('fractal', {})
        target = regime_data.get('target', '?')
        moass = regime_data.get('moass_watch', False)

        regime_colors = {
            'squeeze_watch': 0xFF00FF,
            'risk_on': 0x00FF88,
            'fragile_rally': 0xFFAA00,
            'risk_off': 0xFF4444,
        }
        color = regime_colors.get(new_regime, 0x00BFFF)
        regime_label = new_regime.replace('_', ' ').upper()
        old_label = old_regime.replace('_', ' ').upper()

        moass_line = f"\n🚨 **MOASS WATCH ACTIVE** — Critical short-interest/squeeze threshold reached" if moass else ""

        embed = {
            "embeds": [{
                "title": f"🧠 REGIME CHANGE → {regime_label}",
                "description": (
                    f"Market regime shifted: **{old_label}** → **{regime_label}**{moass_line}"
                ),
                "color": color,
                "fields": [
                    {"name": "Target", "value": target, "inline": True},
                    {"name": "Beast Modifier", "value": f"**{modifier:+d} pts**", "inline": True},
                    {"name": "Bull Probability", "value": f"**{bull_pct}%**", "inline": True},
                    {"name": "Fractal Match", "value": fractal.get('label', '—'), "inline": True},
                    {"name": "Similarity", "value": f"{fractal.get('similarity_pct', 0):.0f}%", "inline": True},
                    {"name": "Fractal Era", "value": fractal.get('date', '—'), "inline": True},
                ],
                "footer": {"text": f"Squeeze OS v5.0 | RMRE | {datetime.now().strftime('%I:%M %p ET')}"},
                "timestamp": datetime.utcnow().isoformat(),
            }]
        }
        self._post(url, embed)
        self._mark(key)

    # ══════════════════════════════════════════════════════════
    # REVERSAL / OPTIONS SETUP ALERTS — A/B/C GRADED
    # ══════════════════════════════════════════════════════════

    def fire_reversal_alert(self, reversal_data: Dict):
        """
        Fire Discord for a graded options setup (A/B/C only — no D/F).
        Includes: symbol, signal, grade, strike, expiry, entry, target, stop, R:R.
        """
        if not self.enabled:
            return
        url = self.webhook_squeeze or self.webhook_all
        if not url:
            return

        sym = reversal_data.get('symbol', '?')
        grade = reversal_data.get('grade', 'C')
        signal = reversal_data.get('signal', 'WATCH')
        strike = reversal_data.get('strike', 0)
        expiry = reversal_data.get('expiry', '?')
        opt_type = reversal_data.get('option_type', 'CALL')
        entry = reversal_data.get('entry', 0)
        target = reversal_data.get('target', 0)
        stop = reversal_data.get('stop', 0)
        rr = reversal_data.get('rr', 0)
        reason = reversal_data.get('reason', '')
        score = reversal_data.get('score', 0)
        price = reversal_data.get('price', 0)
        moass = reversal_data.get('moass_watch', False)

        key = f'reversal_{sym}_{signal}'
        if not self._can_alert(key):
            return

        # Institutional grade color and emoji maps
        grade_colors = {
            'A+': 0x00FF88, 'A': 0x00E676, 'B+': 0x69FF47,
            'B': 0xFFD740, 'C+': 0xFF9100, 'C': 0xFF6D00
        }
        grade_emoji = {
            'A+': '💎', 'A': '🔥', 'B+': '⚡', 'B': '📊', 'C+': '📈'
        }
        # Institutional Color: Match Signal Direction
        if signal == 'BUY':
            color = 0x00FF88 # Bullish
            s_emoji = '🟢'
        elif signal == 'SELL':
            color = 0xFF4444 # Bearish
            s_emoji = '🔴'
        else:
            color = grade_colors.get(grade, 0x00BFFF)
            s_emoji = '👁️'

        g_emoji = grade_emoji.get(grade, '📊')

        moass_tag = " | 🚀 MOASS CANDIDATE" if moass else ""
        contract_str = f"${strike:.2f} {opt_type} exp {expiry}" if strike > 0 else "STOCK"

        embed = {
            "embeds": [{
                "title": f"{g_emoji} {grade}-SETUP {s_emoji} {signal} — {sym}{moass_tag}",
                "description": (
                    f"**{sym}** {contract_str}\n"
                    f"**Reason:** {reason}"
                ),
                "color": color,
                "fields": [
                    {"name": "Grade", "value": f"**{grade}-SETUP**", "inline": True},
                    {"name": "Signal", "value": f"**{signal}**", "inline": True},
                    {"name": "Score", "value": f"**{score:.0f}**/100", "inline": True},
                    {"name": "Stock Price", "value": f"${price:.2f}", "inline": True},
                    {"name": "Entry Zone", "value": f"**${entry:.2f}**", "inline": True},
                    {"name": "Target", "value": f"**${target:.2f}**", "inline": True},
                    {"name": "Stop", "value": f"**${stop:.2f}**", "inline": True},
                    {"name": "R:R Ratio", "value": f"**{rr:.1f}:1**", "inline": True},
                    {"name": "Contract", "value": contract_str, "inline": False},
                ],
                "footer": {"text": f"Squeeze OS v5.0 | Sweet Spot $5-$50 | {datetime.now().strftime('%I:%M %p ET')}"},
                "timestamp": datetime.utcnow().isoformat(),
            }]
        }
        self._post(url, embed)
        self._mark(key)

    # ══════════════════════════════════════════════════════════
    # S&R PATTERN ALERTS (Price Action Pivot Setups)
    # ══════════════════════════════════════════════════════════

    def fire_sr_pattern_alerts(self, hits: List[Dict]):
        if not self.enabled:
            return
        url = self.webhook_squeeze or self.webhook_all
        if not url:
            return

        for hit in hits:
            sym = hit.get('symbol', '?')
            action = hit.get('action', 'WATCH')
            pattern = hit.get('pattern', 'Setup')
            zone = hit.get('zone', {})
            price = hit.get('price', 0)
            target = hit.get('target', 0)
            stop = hit.get('stop', 0)
            
            # Simple RR approx
            rr = abs(target - price) / abs(price - stop) if abs(price - stop) > 0 else 0

            key = f"sr_{sym}_{action}_{pattern}"
            if not self._can_alert(key):
                continue
                
            color = 0x00FF88 if action == 'BUY' else 0xFF4444
            emoji = "🟢" if action == 'BUY' else "🔴"
            
            z_type = zone.get('type', 'ZONE')
            z_top = zone.get('zone_high', 0)
            z_bot = zone.get('zone_low', 0)

            embed = {
                "embeds": [{
                    "title": f"{emoji} PATTERN ALERT: {sym} — {action}",
                    "description": f"**{pattern}** formed directly at a major {z_type} Pivot Zone.",
                    "color": color,
                    "fields": [
                        {"name": "Action", "value": f"**{action}**", "inline": True},
                        {"name": "Pattern", "value": pattern, "inline": True},
                        {"name": "Current Price", "value": f"**${price:.2f}**", "inline": True},
                        {"name": "Target", "value": f"**${target:.2f}**", "inline": True},
                        {"name": "Stop Loss", "value": f"**${stop:.2f}**", "inline": True},
                        {"name": "Est. R:R", "value": f"**{rr:.1f}:1**", "inline": True},
                        {"name": "Zone Range", "value": f"${z_bot:.2f} - ${z_top:.2f}", "inline": False},
                    ],
                    "footer": {"text": f"Squeeze OS v5.0 | Price Action Engine | {datetime.now().strftime('%I:%M %p ET')}"},
                    "timestamp": datetime.utcnow().isoformat(),
                }]
            }
            self._post(url, embed)
            self._mark(key)
            time.sleep(1.0)

    # ══════════════════════════════════════════════════════════
    # BEAST PAPER / LIVE TRADE NOTIFICATIONS
    # ══════════════════════════════════════════════════════════

    def fire_beast_trade_alert_full(self, trade_data: Dict, is_live: bool = False):
        """Send Discord notification when a paper or live trade is executed."""
        if not self.enabled:
            return
        url = self.webhook_beast or self.webhook_all or self.webhook_squeeze
        if not url:
            return

        sym = trade_data.get('symbol', '?')
        side = trade_data.get('side', 'BUY')
        qty = trade_data.get('qty', 0)
        price = trade_data.get('price', 0)
        reason = trade_data.get('reason', '')
        trade_id = trade_data.get('id', '?')
        sl = trade_data.get('sl', 0)
        tp = trade_data.get('tp', 0)

        mode = '🔴 LIVE' if is_live else '📋 PAPER'
        side_emoji = '🟢' if side == 'BUY' else '🔴'
        color = 0xFF0000 if is_live else 0x00BFFF  # Red for live, blue for paper

        key = f'beast_trade_{sym}_{trade_id}'
        if not self._can_alert(key):
            return

        fields = [
            {"name": "Mode", "value": f"**{mode}**", "inline": True},
            {"name": "Side", "value": f"**{side_emoji} {side}**", "inline": True},
            {"name": "Qty", "value": f"**{qty}**", "inline": True},
            {"name": "Entry Price", "value": f"**${price:.2f}**", "inline": True},
            {"name": "Total Value", "value": f"**${qty * price:,.2f}**", "inline": True},
            {"name": "Reason", "value": reason or '—', "inline": True},
        ]
        if tp > 0:
            fields.append({"name": "Take Profit", "value": f"${tp:.2f}", "inline": True})
        if sl > 0:
            fields.append({"name": "Stop Loss", "value": f"${sl:.2f}", "inline": True})

        embed = {
            "embeds": [{
                "title": f"🦅 BEAST {mode} TRADE — {side} {sym}",
                "description": f"**{qty}x {sym}** @ **${price:.2f}** | {reason}",
                "color": color,
                "fields": fields,
                "footer": {"text": f"Squeeze OS v5.0 | BEAST Engine | {datetime.now().strftime('%I:%M %p ET')}"},
                "timestamp": datetime.utcnow().isoformat(),
            }]
        }
        self._post(url, embed)
        self._mark(key)

    def fire_beast_exit_alert(self, trade_data: Dict, is_live: bool = False):
        """Send Discord notification when a paper or live trade is closed."""
        if not self.enabled:
            return
        url = self.webhook_beast or self.webhook_all or self.webhook_squeeze
        if not url:
            return

        sym = trade_data.get('symbol', '?')
        pnl = trade_data.get('pnl', 0)
        exit_reason = trade_data.get('exit_reason', 'UNKNOWN')
        entry = trade_data.get('entry_price', 0)
        exit_price = trade_data.get('current_price', 0)
        qty = trade_data.get('qty', 0)

        mode = '🔴 LIVE' if is_live else '📋 PAPER'
        pnl_emoji = '💰' if pnl >= 0 else '📉'
        color = 0x00FF88 if pnl >= 0 else 0xFF4444

        embed = {
            "embeds": [{
                "title": f"{pnl_emoji} BEAST {mode} EXIT — {sym}",
                "description": f"**{sym}** closed | PnL: **${pnl:+,.2f}** | Reason: {exit_reason}",
                "color": color,
                "fields": [
                    {"name": "Entry", "value": f"${entry:.2f}", "inline": True},
                    {"name": "Exit", "value": f"${exit_price:.2f}", "inline": True},
                    {"name": "PnL", "value": f"**${pnl:+,.2f}**", "inline": True},
                    {"name": "Qty", "value": str(qty), "inline": True},
                    {"name": "Exit Reason", "value": exit_reason, "inline": True},
                ],
                "footer": {"text": f"Squeeze OS v5.0 | BEAST Engine | {datetime.now().strftime('%I:%M %p ET')}"},
                "timestamp": datetime.utcnow().isoformat(),
            }]
        }
        self._post(url, embed)

    def fire_beast_hedge_dict(self, hedge_data: Dict, is_live: bool = False):
        """Send Discord notification when a BEAST hedger cycle executes a hedge decision."""
        if not self.enabled:
            return
        url = self.webhook_beast or self.webhook_all or self.webhook_squeeze
        if not url:
            return

        sym = hedge_data.get('symbol', '?')
        action = hedge_data.get('action', 'HEDGE')
        delta = hedge_data.get('delta', 0.0)
        gex_regime = hedge_data.get('gex_regime', 'UNKNOWN')
        conviction = hedge_data.get('conviction', 0)
        qty = hedge_data.get('qty', 0)
        price = hedge_data.get('price', 0)
        reason = hedge_data.get('reason', '')

        mode = '🔴 LIVE' if is_live else '📋 PAPER'
        color = 0xFF8C00  # Orange for hedge actions

        key = f'beast_hedge_{sym}_{action}_{int(time.time() // 300)}'
        if not self._can_alert(key):
            return

        fields = [
            {"name": "Mode", "value": f"**{mode}**", "inline": True},
            {"name": "Action", "value": f"**{action}**", "inline": True},
            {"name": "GEX Regime", "value": gex_regime, "inline": True},
            {"name": "Delta Exposure", "value": f"{delta:+.2f}Δ", "inline": True},
            {"name": "Conviction", "value": f"{conviction:.0f}%", "inline": True},
        ]
        if qty and price:
            fields.append({"name": "Qty × Price", "value": f"{qty} @ ${price:.2f}", "inline": True})
        if reason:
            fields.append({"name": "Reason", "value": reason, "inline": False})

        embed = {
            "embeds": [{
                "title": f"⚡ BEAST HEDGER — {action} {sym} [{mode}]",
                "description": f"**{sym}** hedged | GEX: {gex_regime} | Delta: {delta:+.2f}",
                "color": color,
                "fields": fields,
                "footer": {"text": f"Squeeze OS v5.0 | BEAST Hedger | {datetime.now().strftime('%I:%M %p ET')}"},
                "timestamp": datetime.utcnow().isoformat(),
            }]
        }
        self._post(url, embed)
        self._mark(key)

    def fire_beast_paper_summary(self, hedger_count: int, gex_count: int, shadow_trades: int, total_pnl: float):
        """Periodic summary of BEAST paper trading status."""
        if not self.enabled:
            return
        url = self.webhook_beast or self.webhook_all
        if not url:
            return

        key = 'beast_paper_summary'
        if not self._can_alert(key):
            return

        pnl_emoji = '💰' if total_pnl >= 0 else '📉'
        color = 0x00FF88 if total_pnl >= 0 else 0xFF4444

        embed = {
            "embeds": [{
                "title": f"🦅 BEAST Paper Trading Cycle",
                "color": color,
                "fields": [
                    {"name": "Hedger Cycles", "value": str(hedger_count), "inline": True},
                    {"name": "GEX Scans", "value": str(gex_count), "inline": True},
                    {"name": "Active Shadow Trades", "value": str(shadow_trades), "inline": True},
                    {"name": f"{pnl_emoji} Shadow PnL", "value": f"**${total_pnl:+,.2f}**", "inline": True},
                ],
                "footer": {"text": f"Squeeze OS v5.0 | BEAST Observer | {datetime.now().strftime('%I:%M %p ET')}"},
                "timestamp": datetime.utcnow().isoformat(),
            }]
        }
        self._post(url, embed)
        self._mark(key)

    def fire_beast_hedge_executed(self, symbol: str, side: str, qty: int, price: float, delta: float, reason: str):
        """Detailed notification for institutional delta-neutralization moves."""
        if not self.enabled: return
        url = self.webhook_beast or self.webhook_all
        if not url: return

        color = 0x00D0FF # Cyan for hedging
        dir_emoji = "🔵" if side == "BUY" else "🟠"
        
        embed = {
            "embeds": [{
                "title": f"🛡️ Institutional Hedge: {symbol}",
                "description": f"**{dir_emoji} {side} {qty} shares @ ${price:.2f}**",
                "color": color,
                "fields": [
                    {"name": "Net Delta", "value": f"{delta:+.2f}", "inline": True},
                    {"name": "Reason", "value": reason, "inline": True},
                    {"name": "Status", "value": "✅ EXECUTED (SHADOW)", "inline": True},
                ],
                "footer": {"text": f"Squeeze OS v5.0 | BEAST Hedger | {datetime.now().strftime('%I:%M %p ET')}"},
                "timestamp": datetime.utcnow().isoformat(),
            }]
        }
        self._post(url, embed)

    def fire_beast_trade_alert(self, trade: dict, is_live: bool = False):
        """High-precision trade alert for BEAST expert signals."""
        if not self.enabled: return
        url = self.webhook_beast or self.webhook_all
        if not url: return

        sym = trade.get('symbol', '?')
        side = trade.get('side', 'BUY')
        qty = trade.get('qty', 0)
        price = trade.get('entry_price', 0.0)
        regime = trade.get('regime', 'UNKNOWN')
        
        color = 0x00FF00 if side == "BUY" else 0xFF0000
        emoji = "🟢" if side == "BUY" else "🔴"
        
        # Extract option-specific info if available
        strike = trade.get('strike')
        expiry = trade.get('expiry')
        dte = trade.get('dte')
        
        desc = f"**{emoji} {side} {qty} {sym} @ ${price:.2f}**"
        if strike and expiry:
            desc = f"**{emoji} BUY {sym} ${strike} {side} exp {expiry} @ ${price:.2f} ({dte} DTE)**"

        embed = {
            "embeds": [{
                "title": f"🦅 BEAST {side} Signal — {sym}",
                "description": desc,
                "color": color,
                "fields": [
                    {"name": "Regime", "value": regime, "inline": True},
                    {"name": "Hurst", "value": f"{trade.get('hurst', 0.5):.2f}", "inline": True},
                    {"name": "Net Pressure", "value": f"{trade.get('net_pressure', 0.0):+.2f}", "inline": True},
                    {"name": "SL", "value": f"${trade.get('sl', 0.0):.2f}", "inline": True},
                    {"name": "TP", "value": f"${trade.get('tp', 0.0):.2f}", "inline": True},
                ],
                "footer": {"text": f"Squeeze OS v5.0 | BEAST Engine | {datetime.now().strftime('%I:%M %p ET')}"},
                "timestamp": datetime.utcnow().isoformat(),
            }]
        }
        ai_note = _llm_commentary(sym, trade)
        if ai_note:
            embed["embeds"][0]["fields"].append({"name": "🤖 AI ANALYST", "value": ai_note, "inline": False})
        self._post(url, embed)

    # ══════════════════════════════════════════════════════════
    # AI TRADE DESK BRIDGE — Keep-Alive & Unified Alerts
    # ══════════════════════════════════════════════════════════

    def ping_trade_desk(self, trade_desk_url: str) -> dict:
        """
        Ping the AI Trade Desk Render service to prevent free-tier cold-start spin-down.
        Returns health check data or error info.
        """
        if not trade_desk_url:
            return {'ok': False, 'error': 'No trade desk URL configured'}
        
        health_url = f"{trade_desk_url.rstrip('/')}/health"
        try:
            r = self.session.get(health_url, timeout=60)
            if r.status_code == 200:
                data = r.json()
                logger.info(f"[TRADE DESK] Keep-alive OK: {data.get('service', 'unknown')}")
                return {'ok': True, 'data': data}
            else:
                logger.warning(f"[TRADE DESK] Keep-alive failed: HTTP {r.status_code}")
                return {'ok': False, 'status': r.status_code}
        except Exception as e:
            logger.error(f"[TRADE DESK] Keep-alive error: {e}")
            return {'ok': False, 'error': str(e)}

    def forward_to_trade_desk(self, trade_desk_url: str, secret: str, signal: Dict):
        """
        Forward a high-conviction SqueezeOS signal to the AI Trade Desk webhook,
        which will format it as a desk-style Discord alert.
        """
        if not trade_desk_url or not secret:
            return
        
        webhook_url = f"{trade_desk_url.rstrip('/')}/webhook/tradingview"
        
        direction = signal.get('direction', 'NEUTRAL').upper()
        bias = 'LONG' if direction == 'BULLISH' else 'PUTS' if direction == 'BEARISH' else 'NEUTRAL'
        score = signal.get('squeeze_score', 0)
        price = signal.get('price', 0)
        
        daily_range = price * 0.02
        if bias == 'LONG':
            target_1 = round(price + daily_range, 2)
            target_2 = round(price + (2 * daily_range), 2)
            target_3 = round(price + (3 * daily_range), 2)
            stop = round(price - (0.5 * daily_range), 2)
        elif bias == 'PUTS':
            target_1 = round(price - daily_range, 2)
            target_2 = round(price - (2 * daily_range), 2)
            target_3 = round(price - (3 * daily_range), 2)
            stop = round(price + (0.5 * daily_range), 2)
        else:
            target_1 = target_2 = target_3 = stop = price
        
        rr = abs(target_1 - price) / abs(price - stop) if abs(price - stop) > 0 else 2.0
        grade = 'A+' if score >= 90 else 'A' if score >= 80 else 'B' if score >= 70 else 'C'
        
        payload = {
            'secret': secret,
            'source': 'SqueezeOS v5.0 Bridge',
            'ticker': signal.get('symbol', '?'),
            'exchange': 'NYSE',
            'timeframe': '240',
            'price': price,
            'alert_type': signal.get('squeeze_level', 'ECHO_SQUEEZE'),
            'bias': bias,
            'score': score,
            'grade': grade,
            'regime': signal.get('recommendation', 'WATCH'),
            'entry': price,
            'stop': stop,
            'target_1': target_1,
            'target_2': target_2,
            'target_3': target_3,
            'rr': round(rr, 1),
            'volume_ratio': signal.get('analysis_components', {}).get('volume_profile', 0) / 10,
            'action': f"{'WATCH_LONG' if bias == 'LONG' else 'WATCH_SHORT' if bias == 'PUTS' else 'MONITOR'}",
            'reason': f"SqueezeOS Bridge: {signal.get('recommendation', 'WATCH')} | Score {score}/100 | {signal.get('squeeze_level', 'SIGNAL')}"
        }
        
        try:
            r = self.session.post(webhook_url, json=payload, timeout=30)
            if r.status_code == 200:
                logger.info(f"[TRADE DESK] Forwarded {signal.get('symbol', '?')} (score={score}) to AI Trade Desk")
            else:
                logger.warning(f"[TRADE DESK] Forward failed: {r.status_code} {r.text[:200]}")
        except Exception as e:
            logger.error(f"[TRADE DESK] Forward error: {e}")

    def fire_trade_desk_status(self, is_online: bool, service_name: str = ''):
        """Post a status update about the AI Trade Desk connection to Discord."""
        if not self.enabled:
            return
        url = self.webhook_all or self.webhook_squeeze
        if not url:
            return
        
        key = 'trade_desk_status'
        if not self._can_alert(key):
            return
        
        if is_online:
            embed = {
                "embeds": [{
                    "title": "🔗 AI Trade Desk — CONNECTED",
                    "description": f"Render bridge is warm and responsive.\n**Service**: {service_name}",
                    "color": 0x00FF88,
                    "footer": {"text": f"Squeeze OS v5.0 | Trade Desk Bridge | {datetime.now().strftime('%I:%M %p ET')}"},
                    "timestamp": datetime.utcnow().isoformat(),
                }]
            }
        else:
            embed = {
                "embeds": [{
                    "title": "⚠️ AI Trade Desk — OFFLINE",
                    "description": "Render bridge is not responding. TradingView alerts may be lost during cold-start.",
                    "color": 0xFF4444,
                    "footer": {"text": f"Squeeze OS v5.0 | Trade Desk Bridge | {datetime.now().strftime('%I:%M %p ET')}"},
                    "timestamp": datetime.utcnow().isoformat(),
                }]
            }
        self._post(url, embed)
        self._mark(key)
