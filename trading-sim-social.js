/* trading-sim-social.js — P&L cards, sharing, leaderboard, challenges */
'use strict';

const SocialSim = (() => {
  const CARD_STYLES = {
    dark: {
      bg: '#0a0e1a', bg2: '#0d1117', accent: '#00d4ff', accent2: '#00ff88',
      text: '#ffffff', subtext: '#8892a4', border: '#1e2a3a', glow: 'rgba(0,212,255,0.3)'
    },
    neon: {
      bg: '#0d001a', bg2: '#120020', accent: '#ff00ff', accent2: '#00ffff',
      text: '#ffffff', subtext: '#cc88ff', border: '#440066', glow: 'rgba(255,0,255,0.4)'
    },
    minimal: {
      bg: '#ffffff', bg2: '#f5f7fa', accent: '#1a1a2e', accent2: '#e94560',
      text: '#1a1a2e', subtext: '#666688', border: '#e0e4ef', glow: 'rgba(0,0,0,0.1)'
    },
    beast: {
      bg: '#0a0a0a', bg2: '#111111', accent: '#ff6600', accent2: '#ffcc00',
      text: '#ffffff', subtext: '#aaaaaa', border: '#333333', glow: 'rgba(255,102,0,0.4)'
    }
  };

  const MOCK_LEADERBOARD = [
    { rank: 1, name: 'QuantKing', avatar: '👑', pnl: 284750, pct: 284.75, trades: 1247, level: 'Elite', streak: 23 },
    { rank: 2, name: 'NeonTrader', avatar: '⚡', pnl: 198340, pct: 198.34, trades: 891, level: 'Elite', streak: 15 },
    { rank: 3, name: 'OptionsMaster', avatar: '🎯', pnl: 167820, pct: 167.82, trades: 2341, level: 'Pro', streak: 31 },
    { rank: 4, name: 'BullRunner99', avatar: '🐂', pnl: 143290, pct: 143.29, trades: 567, level: 'Pro', streak: 8 },
    { rank: 5, name: 'AlphaSeeker', avatar: '🚀', pnl: 128450, pct: 128.45, trades: 734, level: 'Pro', streak: 12 },
    { rank: 6, name: 'GammaScalper', avatar: '🎲', pnl: 112670, pct: 112.67, trades: 1892, level: 'Pro', streak: 19 },
    { rank: 7, name: 'ThetaGang', avatar: '⏰', pnl: 98340, pct: 98.34, trades: 445, level: 'Intermediate', streak: 7 },
    { rank: 8, name: 'VegaVault', avatar: '💎', pnl: 87120, pct: 87.12, trades: 312, level: 'Intermediate', streak: 4 },
    { rank: 9, name: 'MomentumMax', avatar: '📈', pnl: 76890, pct: 76.89, trades: 623, level: 'Intermediate', streak: 9 },
    { rank: 10, name: 'RiskManager', avatar: '🛡️', pnl: 65430, pct: 65.43, trades: 891, level: 'Intermediate', streak: 22 }
  ];

  const CHALLENGES = [
    {
      id: 'weekly_gain',
      name: 'Weekly Warrior',
      desc: 'Achieve 10% portfolio gain this week',
      icon: '⚔️',
      xp: 500,
      type: 'weekly',
      target: 10,
      metric: 'pct_gain',
      ends: _nextSunday()
    },
    {
      id: 'options_streak',
      name: 'Options Oracle',
      desc: 'Win 5 options trades in a row',
      icon: '🔮',
      xp: 750,
      type: 'weekly',
      target: 5,
      metric: 'options_win_streak',
      ends: _nextSunday()
    },
    {
      id: 'vol_master',
      name: 'Volatility Master',
      desc: 'Profit from the Earnings Squeeze scenario',
      icon: '💥',
      xp: 1000,
      type: 'special',
      target: 1,
      metric: 'scenario_earnings',
      ends: _nextSunday()
    },
    {
      id: 'trade_volume',
      name: 'Volume King',
      desc: 'Execute 50 trades this week',
      icon: '👑',
      xp: 600,
      type: 'weekly',
      target: 50,
      metric: 'weekly_trades',
      ends: _nextSunday()
    },
    {
      id: 'risk_disciplined',
      name: 'Risk Disciplined',
      desc: 'Keep max drawdown under 5% for 7 days',
      icon: '🛡️',
      xp: 800,
      type: 'weekly',
      target: 7,
      metric: 'drawdown_days',
      ends: _nextSunday()
    },
    {
      id: 'daily_profit',
      name: 'Daily Grind',
      desc: 'Achieve positive P&L for 3 consecutive days',
      icon: '📅',
      xp: 400,
      type: 'daily',
      target: 3,
      metric: 'daily_streak',
      ends: _nextMidnight()
    }
  ];

  function _nextSunday() {
    const d = new Date();
    d.setDate(d.getDate() + (7 - d.getDay()));
    d.setHours(23, 59, 59, 0);
    return d.getTime();
  }

  function _nextMidnight() {
    const d = new Date();
    d.setDate(d.getDate() + 1);
    d.setHours(0, 0, 0, 0);
    return d.getTime();
  }

  function _timeLeft(ts) {
    const diff = ts - Date.now();
    if (diff <= 0) return 'Ended';
    const h = Math.floor(diff / 3600000);
    const m = Math.floor((diff % 3600000) / 60000);
    if (h > 24) return `${Math.floor(h / 24)}d ${h % 24}h`;
    return `${h}h ${m}m`;
  }

  /* ── Leaderboard ── */
  function renderLeaderboard() {
    const st = SimEngine.state;
    const myPct = st.startingCapital > 0
      ? ((st.portfolio - st.startingCapital) / st.startingCapital * 100)
      : 0;

    const myEntry = {
      rank: '?',
      name: st.username || 'You',
      avatar: '🤖',
      pnl: st.portfolio - st.startingCapital,
      pct: myPct,
      trades: st.totalTrades,
      level: st.levelName || 'Beginner',
      streak: st.currentStreak || 0,
      isMe: true
    };

    const allEntries = [...MOCK_LEADERBOARD, myEntry].sort((a, b) => b.pct - a.pct);
    allEntries.forEach((e, i) => { if (e.isMe) e.rank = i + 1; });

    const tab = document.getElementById('lb-tab') || 'global';
    const periodEl = document.getElementById('lb-period');
    const period = periodEl ? periodEl.value : 'weekly';

    const container = document.getElementById('leaderboard-list');
    if (!container) return;

    const rankEmoji = (r) => r === 1 ? '🥇' : r === 2 ? '🥈' : r === 3 ? '🥉' : `#${r}`;

    container.innerHTML = allEntries.map(e => `
      <div class="lb-row ${e.isMe ? 'lb-me' : ''} ${e.rank <= 3 ? 'lb-top' : ''}">
        <div class="lb-rank">${rankEmoji(e.rank)}</div>
        <div class="lb-avatar">${e.avatar}</div>
        <div class="lb-info">
          <div class="lb-name">${e.name} ${e.isMe ? '<span class="lb-you-badge">YOU</span>' : ''}</div>
          <div class="lb-meta">${e.level} • ${e.trades.toLocaleString()} trades • 🔥${e.streak}</div>
        </div>
        <div class="lb-stats">
          <div class="lb-pct ${e.pct >= 0 ? 'pos' : 'neg'}">${e.pct >= 0 ? '+' : ''}${e.pct.toFixed(1)}%</div>
          <div class="lb-pnl">${e.pnl >= 0 ? '+' : ''}$${Math.abs(e.pnl).toLocaleString()}</div>
        </div>
      </div>
    `).join('');

    renderChallenges();
    renderMyStats();
  }

  function renderChallenges() {
    const container = document.getElementById('challenges-list');
    if (!container) return;

    const st = SimEngine.state;
    const completed = st.completedChallenges || [];

    container.innerHTML = CHALLENGES.map(c => {
      const done = completed.includes(c.id);
      const progress = _getChallengeProgress(c, st);
      const pct = Math.min(100, (progress / c.target) * 100);

      return `
        <div class="challenge-card ${done ? 'challenge-done' : ''}">
          <div class="challenge-icon">${c.icon}</div>
          <div class="challenge-body">
            <div class="challenge-name">${c.name} ${done ? '✅' : ''}</div>
            <div class="challenge-desc">${c.desc}</div>
            <div class="challenge-meta">
              <span class="challenge-type ${c.type}">${c.type}</span>
              <span class="challenge-xp">+${c.xp} XP</span>
              <span class="challenge-time">⏱ ${_timeLeft(c.ends)}</span>
            </div>
            ${!done ? `
              <div class="challenge-progress">
                <div class="challenge-bar">
                  <div class="challenge-fill" style="width:${pct}%"></div>
                </div>
                <span class="challenge-prog-txt">${progress}/${c.target}</span>
              </div>
            ` : '<div class="challenge-complete-msg">Challenge Complete! XP Awarded</div>'}
          </div>
        </div>
      `;
    }).join('');
  }

  function _getChallengeProgress(c, st) {
    switch (c.metric) {
      case 'pct_gain': {
        const g = ((st.portfolio - st.startingCapital) / st.startingCapital * 100);
        return Math.max(0, g.toFixed(1) * 1);
      }
      case 'options_win_streak': return st.optionsWinStreak || 0;
      case 'scenario_earnings': return (st.completedScenarios || []).includes('earnings') ? 1 : 0;
      case 'weekly_trades': return st.weeklyTrades || 0;
      case 'drawdown_days': return st.drawdownDays || 0;
      case 'daily_streak': return st.dailyProfitStreak || 0;
      default: return 0;
    }
  }

  function renderMyStats() {
    const el = document.getElementById('my-lb-stats');
    if (!el) return;
    const st = SimEngine.state;
    const pnl = st.portfolio - st.startingCapital;
    const pct = (pnl / st.startingCapital * 100).toFixed(2);
    el.innerHTML = `
      <div class="my-stat"><span>Portfolio</span><strong>$${st.portfolio.toLocaleString('en', {maximumFractionDigits:0})}</strong></div>
      <div class="my-stat"><span>Total P&L</span><strong class="${pnl>=0?'pos':'neg'}">${pnl>=0?'+':''}$${Math.abs(pnl).toLocaleString('en',{maximumFractionDigits:0})}</strong></div>
      <div class="my-stat"><span>Return</span><strong class="${pct>=0?'pos':'neg'}">${pct>=0?'+':''}${pct}%</strong></div>
      <div class="my-stat"><span>Win Rate</span><strong>${st.winRate||0}%</strong></div>
      <div class="my-stat"><span>Level</span><strong>${st.levelName||'Beginner'}</strong></div>
      <div class="my-stat"><span>XP</span><strong>${(st.xp||0).toLocaleString()}</strong></div>
    `;
  }

  /* ── P&L Card Generator ── */
  let _currentStyle = 'dark';

  function openShareModal(tradeData) {
    const modal = document.getElementById('share-modal');
    if (!modal) return;
    modal.style.display = 'flex';
    _renderCardPreview(tradeData || _buildCardData());
    _renderShareOptions(tradeData || _buildCardData());
  }

  function closeShareModal() {
    const modal = document.getElementById('share-modal');
    if (modal) modal.style.display = 'none';
  }

  function _buildCardData() {
    const st = SimEngine.state;
    const pnl = st.portfolio - st.startingCapital;
    return {
      type: 'portfolio',
      symbol: 'PORTFOLIO',
      pnl: pnl,
      pct: (pnl / st.startingCapital * 100),
      portfolio: st.portfolio,
      winRate: st.winRate || 0,
      trades: st.totalTrades || 0,
      level: st.levelName || 'Beginner',
      xp: st.xp || 0,
      streak: st.currentStreak || 0,
      username: st.username || 'Trader'
    };
  }

  function _renderCardPreview(data) {
    const preview = document.getElementById('card-preview-area');
    if (!preview) return;

    const canvas = document.createElement('canvas');
    canvas.width = 800;
    canvas.height = 450;
    canvas.id = 'pnl-canvas';
    canvas.style.cssText = 'width:100%;max-width:600px;border-radius:12px;';
    preview.innerHTML = '';
    preview.appendChild(canvas);
    drawCard(canvas, data, _currentStyle);
  }

  function drawCard(canvas, data, styleName) {
    const ctx = canvas.getContext('2d');
    const s = CARD_STYLES[styleName] || CARD_STYLES.dark;
    const W = canvas.width, H = canvas.height;

    // Background gradient
    const grad = ctx.createLinearGradient(0, 0, W, H);
    grad.addColorStop(0, s.bg);
    grad.addColorStop(1, s.bg2);
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, W, H);

    // Border glow
    ctx.save();
    ctx.strokeStyle = s.accent;
    ctx.lineWidth = 2;
    ctx.shadowColor = s.glow;
    ctx.shadowBlur = 20;
    _roundRect(ctx, 2, 2, W - 4, H - 4, 16);
    ctx.stroke();
    ctx.restore();

    // Grid lines
    ctx.save();
    ctx.strokeStyle = s.border;
    ctx.lineWidth = 0.5;
    ctx.globalAlpha = 0.4;
    for (let x = 40; x < W; x += 80) {
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke();
    }
    for (let y = 40; y < H; y += 80) {
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke();
    }
    ctx.restore();

    // Logo/brand
    ctx.fillStyle = s.accent;
    ctx.font = 'bold 18px "Courier New", monospace';
    ctx.fillText('⚡ SQUEEZE OS SIMULATOR', 32, 42);

    // Divider
    ctx.fillStyle = s.accent;
    ctx.fillRect(32, 54, W - 64, 1);

    // Username + level
    ctx.fillStyle = s.subtext;
    ctx.font = '14px "Courier New", monospace';
    ctx.fillText(`@${data.username}`, 32, 78);
    ctx.fillStyle = s.accent2;
    ctx.font = 'bold 14px "Courier New", monospace';
    ctx.fillText(`LVL: ${data.level}`, W - 180, 78);
    ctx.fillStyle = s.subtext;
    ctx.fillText(`${data.xp.toLocaleString()} XP`, W - 100, 78);

    // Main P&L
    const isPos = data.pnl >= 0;
    const pnlColor = isPos ? (styleName === 'minimal' ? '#00aa44' : '#00ff88') : '#ff4466';
    const pnlText = `${isPos ? '+' : ''}$${Math.abs(data.pnl).toLocaleString('en', { maximumFractionDigits: 0 })}`;

    ctx.save();
    ctx.fillStyle = pnlColor;
    ctx.font = 'bold 72px "Courier New", monospace';
    ctx.shadowColor = pnlColor;
    ctx.shadowBlur = styleName === 'minimal' ? 0 : 30;
    const pnlW = ctx.measureText(pnlText).width;
    ctx.fillText(pnlText, (W - pnlW) / 2, 200);
    ctx.restore();

    // Percentage
    const pctText = `${isPos ? '+' : ''}${data.pct.toFixed(2)}%`;
    ctx.save();
    ctx.fillStyle = pnlColor;
    ctx.font = 'bold 36px "Courier New", monospace';
    ctx.shadowColor = pnlColor;
    ctx.shadowBlur = styleName === 'minimal' ? 0 : 15;
    const pctW = ctx.measureText(pctText).width;
    ctx.fillText(pctText, (W - pctW) / 2, 250);
    ctx.restore();

    // Symbol/type label
    ctx.fillStyle = s.subtext;
    ctx.font = '16px "Courier New", monospace';
    const symW = ctx.measureText(data.symbol).width;
    ctx.fillText(data.symbol, (W - symW) / 2, 280);

    // Stats row
    const stats = [
      { label: 'PORTFOLIO', val: `$${(data.portfolio / 1000).toFixed(1)}K` },
      { label: 'WIN RATE', val: `${data.winRate}%` },
      { label: 'TRADES', val: data.trades.toString() },
      { label: 'STREAK', val: `🔥${data.streak}` }
    ];

    const statW = (W - 64) / stats.length;
    stats.forEach((stat, i) => {
      const x = 32 + i * statW + statW / 2;
      ctx.fillStyle = s.subtext;
      ctx.font = '11px "Courier New", monospace';
      const lw = ctx.measureText(stat.label).width;
      ctx.fillText(stat.label, x - lw / 2, 330);

      ctx.fillStyle = s.text;
      ctx.font = 'bold 18px "Courier New", monospace';
      const vw = ctx.measureText(stat.val).width;
      ctx.fillText(stat.val, x - vw / 2, 355);
    });

    // Divider
    ctx.fillStyle = s.border;
    ctx.fillRect(32, 370, W - 64, 1);

    // Bottom CTA
    ctx.fillStyle = s.accent;
    ctx.font = '13px "Courier New", monospace';
    ctx.fillText('Trade smarter at SqueezeOS.com', 32, 400);

    ctx.fillStyle = s.subtext;
    ctx.font = '11px "Courier New", monospace';
    ctx.fillText('Simulated trading for educational purposes', 32, 420);

    // Watermark pattern
    if (styleName !== 'minimal') {
      ctx.save();
      ctx.globalAlpha = 0.04;
      ctx.fillStyle = s.accent;
      ctx.font = 'bold 120px "Courier New", monospace';
      ctx.fillText('SIM', 200, 380);
      ctx.restore();
    }

    return canvas;
  }

  function _roundRect(ctx, x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.lineTo(x + w - r, y);
    ctx.quadraticCurveTo(x + w, y, x + w, y + r);
    ctx.lineTo(x + w, y + h - r);
    ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
    ctx.lineTo(x + r, y + h);
    ctx.quadraticCurveTo(x, y + h, x, y + h - r);
    ctx.lineTo(x, y + r);
    ctx.quadraticCurveTo(x, y, x + r, y);
    ctx.closePath();
  }

  function _renderShareOptions(data) {
    const el = document.getElementById('share-options-area');
    if (!el) return;
    el.innerHTML = `
      <div class="share-style-row">
        ${Object.keys(CARD_STYLES).map(k => `
          <button class="style-btn ${k === _currentStyle ? 'active' : ''}"
            onclick="SocialSim.setCardStyle('${k}',this)"
            style="background:${CARD_STYLES[k].bg};color:${CARD_STYLES[k].accent};border-color:${CARD_STYLES[k].accent}">
            ${k.charAt(0).toUpperCase() + k.slice(1)}
          </button>
        `).join('')}
      </div>
      <div class="share-buttons-row">
        <button class="share-btn share-twitter" onclick="SocialSim.shareToTwitter()">
          𝕏 Twitter/X
        </button>
        <button class="share-btn share-reddit" onclick="SocialSim.shareToReddit()">
          📡 Reddit
        </button>
        <button class="share-btn share-discord" onclick="SocialSim.copyDiscord()">
          💬 Discord Copy
        </button>
        <button class="share-btn share-copy" onclick="SocialSim.copyImage()">
          📋 Copy Image
        </button>
        <button class="share-btn share-download" onclick="SocialSim.downloadCard()">
          ⬇️ Download PNG
        </button>
      </div>
    `;
  }

  function setCardStyle(style, btn) {
    _currentStyle = style;
    document.querySelectorAll('.style-btn').forEach(b => b.classList.remove('active'));
    if (btn) btn.classList.add('active');
    _renderCardPreview(_buildCardData());
  }

  function _getCanvas() {
    return document.getElementById('pnl-canvas');
  }

  function _buildShareText(data) {
    const d = data || _buildCardData();
    const isPos = d.pnl >= 0;
    const emoji = isPos ? '🚀🟢' : '📉🔴';
    return `${emoji} Just ${isPos ? 'made' : 'lost'} ${isPos ? '+' : ''}$${Math.abs(d.pnl).toLocaleString()} (${isPos ? '+' : ''}${d.pct.toFixed(2)}%) trading ${d.symbol} on SqueezeOS Simulator!\n\nPortfolio: $${d.portfolio.toLocaleString()} | Win Rate: ${d.winRate}% | Level: ${d.level}\n\n#TradingSimulator #SqueezeOS #PaperTrading #Options`;
  }

  function shareToTwitter() {
    const text = encodeURIComponent(_buildShareText());
    window.open(`https://twitter.com/intent/tweet?text=${text}`, '_blank', 'width=600,height=400');
    SimApp.toast('Opened Twitter/X!', 'success');
  }

  function shareToReddit() {
    const data = _buildCardData();
    const title = encodeURIComponent(`SqueezeOS Sim: ${data.pnl >= 0 ? '+' : ''}$${Math.abs(data.pnl).toLocaleString()} (${data.pct.toFixed(2)}%) - ${data.symbol}`);
    const text = encodeURIComponent(_buildShareText(data));
    window.open(`https://www.reddit.com/r/wallstreetbets/submit?title=${title}&text=${text}`, '_blank');
    SimApp.toast('Opened Reddit!', 'success');
  }

  async function copyDiscord() {
    const text = _buildShareText();
    try {
      await navigator.clipboard.writeText(text);
      SimApp.toast('Copied for Discord!', 'success');
    } catch {
      SimApp.toast('Copy failed — try manual copy', 'error');
    }
  }

  async function copyImage() {
    const canvas = _getCanvas();
    if (!canvas) return;
    try {
      canvas.toBlob(async blob => {
        await navigator.clipboard.write([new ClipboardItem({ 'image/png': blob })]);
        SimApp.toast('Image copied to clipboard!', 'success');
      });
    } catch {
      SimApp.toast('Image copy not supported in this browser', 'warn');
    }
  }

  function downloadCard() {
    const canvas = _getCanvas();
    if (!canvas) return;
    const data = _buildCardData();
    const link = document.createElement('a');
    link.download = `squeezeos-pnl-${data.symbol}-${Date.now()}.png`;
    link.href = canvas.toDataURL('image/png');
    link.click();
    SimApp.toast('Card downloaded!', 'success');
  }

  function shareTradeCard(sym, side, pnl, pct, type) {
    const st = SimEngine.state;
    const data = {
      type: type || 'trade',
      symbol: sym,
      pnl: pnl,
      pct: pct,
      portfolio: st.portfolio,
      winRate: st.winRate || 0,
      trades: st.totalTrades || 0,
      level: st.levelName || 'Beginner',
      xp: st.xp || 0,
      streak: st.currentStreak || 0,
      username: st.username || 'Trader',
      side: side
    };
    openShareModal(data);
  }

  /* ── Copy generic link ── */
  async function copyLink() {
    const url = window.location.href.split('#')[0] + '#simulator';
    try {
      await navigator.clipboard.writeText(url);
      SimApp.toast('Link copied!', 'success');
    } catch {
      SimApp.toast('Could not copy link', 'error');
    }
  }

  /* ── Referral system ── */
  function generateReferralCode() {
    const st = SimEngine.state;
    if (st.referralCode) return st.referralCode;
    const code = 'SQ' + Math.random().toString(36).substr(2, 8).toUpperCase();
    st.referralCode = code;
    SimEngine.saveState();
    return code;
  }

  function renderReferralSection() {
    const el = document.getElementById('referral-section');
    if (!el) return;
    const code = generateReferralCode();
    el.innerHTML = `
      <div class="referral-card">
        <h4>🎁 Refer Friends & Earn XP</h4>
        <p>Share your referral code. Each friend who signs up earns you <strong>500 XP</strong>!</p>
        <div class="referral-code-row">
          <span class="referral-code">${code}</span>
          <button class="btn-sm" onclick="SocialSim.copyReferral('${code}')">Copy</button>
          <button class="btn-sm" onclick="SocialSim.shareReferral('${code}')">Share</button>
        </div>
        <div class="referral-stats">
          <span>Referrals: <strong>${SimEngine.state.referrals || 0}</strong></span>
          <span>XP Earned: <strong>${(SimEngine.state.referrals || 0) * 500}</strong></span>
        </div>
      </div>
    `;
  }

  async function copyReferral(code) {
    const text = `Join me on SqueezeOS Trading Simulator! Use code ${code} to get started. #SqueezeOS #TradingSimulator`;
    try {
      await navigator.clipboard.writeText(text);
      SimApp.toast('Referral code copied!', 'success');
    } catch {
      SimApp.toast('Copy failed', 'error');
    }
  }

  function shareReferral(code) {
    const text = encodeURIComponent(`Join me on SqueezeOS Trading Simulator! Use code ${code} to get started. #SqueezeOS #TradingSimulator`);
    window.open(`https://twitter.com/intent/tweet?text=${text}`, '_blank');
  }

  /* ── Init ── */
  function init() {
    const lbTab = document.getElementById('lb-period');
    if (lbTab) lbTab.addEventListener('change', renderLeaderboard);
  }

  return {
    init,
    renderLeaderboard,
    renderChallenges,
    openShareModal,
    closeShareModal,
    setCardStyle,
    shareToTwitter,
    shareToReddit,
    copyDiscord,
    copyImage,
    downloadCard,
    shareTradeCard,
    copyLink,
    drawCard,
    renderReferralSection,
    copyReferral,
    shareReferral,
    CARD_STYLES
  };
})();
