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


class DiscordAlerts:

    def __init__(self):
        self.webhook_squeeze = os.environ.get('DISCORD_WEBHOOK_SQUEEZE', '')
        self.webhook_flow = os.environ.get('DISCORD_WEBHOOK_FLOW', '')
        self.webhook_all = os.environ.get('DISCORD_WEBHOOK_ALL', '')
        self.min_squeeze_score = int(os.environ.get('DISCORD_ALERT_MIN_SCORE', '40'))
        self.min_flow_score = int(os.environ.get('DISCORD_FLOW_MIN_SCORE', '15'))
        self.cooldown = {}
        self.cooldown_sec = 300
        self.rate_limit_until = 0 # Type: int
        
        # ── Robust Session for SSL Resilience ──
        self.session = requests.Session()
        retries = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[500, 502, 503, 504],
            raise_on_status=False
        )
        self.session.mount('https://', HTTPAdapter(max_retries=retries))

        active = []
        if self.webhook_squeeze: active.append('squeeze')
        if self.webhook_flow: active.append('flow')
        if self.webhook_all: active.append('all')
        if active:
            logger.info(f"[DISCORD] Webhooks: {', '.join(active)} | squeeze>={self.min_squeeze_score} | flow>={self.min_flow_score}")
        else:
            logger.info("[DISCORD] No webhooks configured")

    @property
    def enabled(self):
        return bool(self.webhook_squeeze or self.webhook_flow or self.webhook_all)

    def _can_alert(self, key):
        now = time.time()
        if now < self.rate_limit_until:
            return False
        last = self.cooldown.get(key, 0)
        return (now - last) >= self.cooldown_sec

    def _mark(self, key):
        self.cooldown[key] = time.time()

    def _post(self, url, payload):
        if not url:
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
                logger.error("❌ [DISCORD ACTION REQUIRED] 404 Unknown Webhook. Your URLs in .env are dead/deleted.")
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

    # ══════════════════════════════════════════════════════════
    # SQUEEZE ALERTS
    # ══════════════════════════════════════════════════════════

    def fire_squeeze_alerts(self, scan_results: List[Dict]):
        if not self.enabled:
            return
        url = self.webhook_squeeze or self.webhook_all
        if not url:
            return

        for item in scan_results:
            score = item.get('squeeze_score', 0)
            sym = item.get('symbol', '')
            if score < self.min_squeeze_score:
                continue
            if not self._can_alert(f'sq_{sym}'):
                continue

            # Color and Emoji by DIRECTION and INTENSITY
            direction = item.get('direction', 'NEUTRAL').upper()
            if direction == 'BULLISH':
                color = 0x00FF88 # Institutional Bullish Green
                emoji = "🟢" if score < 75 else "🔥"
            elif direction == 'BEARISH':
                color = 0xFF4444 # Institutional Bearish Red
                emoji = "🔴" if score < 75 else "🔥"
            else:
                color = 0x00BFFF
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
        url = self.webhook_flow or self.webhook_all
        if not url:
            return

        qualifying = [f for f in flow_results if f.get('unusual_score', 0) >= self.min_flow_score]
        if not qualifying:
            return

        # Beast Mode: Group contracts by ticker to prevent Discord spam
        # Instead of 5 pings for 5 different strikes on AAPL, send 1 consolidated card
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
                color, title_emoji = 0xFF00FF, "💎" # SWEEP SPIKE
            elif is_oi_spike:
                color, title_emoji = 0xFF8C00, "🌋" # OI SPIKE
            elif is_block:
                color, title_emoji = 0x00BFFF, "🐋" # BLOCK
            elif priority == 'EXTREME':
                color, title_emoji = 0xFF0000, "🔥"
            elif sentiment == 'BULLISH':
                color, title_emoji = 0x00FF88, "🔔"
            elif sentiment == 'BEARISH':
                color, title_emoji = 0xFF4444, "🔔"
            else:
                color, title_emoji = 0x888888, "🔔"

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

