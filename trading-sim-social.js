/* trading-sim-social.js — P&L cards, sharing, leaderboard, challenges */
'use strict';

const SocialSim = (() => {
  const CARD_STYLES = {
    dark:    { bg:'#0a0e1a', bg2:'#0d1117', accent:'#00d4ff', accent2:'#00ff88', text:'#ffffff', subtext:'#8892a4', border:'#1e2a3a', glow:'rgba(0,212,255,0.3)' },
    neon:    { bg:'#0d001a', bg2:'#120020', accent:'#ff00ff', accent2:'#00ffff', text:'#ffffff', subtext:'#cc88ff', border:'#440066', glow:'rgba(255,0,255,0.4)' },
    minimal: { bg:'#ffffff', bg2:'#f5f7fa', accent:'#1a1a2e', accent2:'#e94560', text:'#1a1a2e', subtext:'#666688', border:'#e0e4ef', glow:'rgba(0,0,0,0.1)' },
    beast:   { bg:'#0a0a0a', bg2:'#111111', accent:'#ff6600', accent2:'#ffcc00', text:'#ffffff', subtext:'#aaaaaa', border:'#333333', glow:'rgba(255,102,0,0.4)' }
  };

  const MOCK_LB = [
    { rank:1,  name:'QuantKing',    avatar:'👑', pnl:284750, pct:284.75, trades:1247, level:'Elite',        streak:23 },
    { rank:2,  name:'NeonTrader',   avatar:'⚡', pnl:198340, pct:198.34, trades:891,  level:'Elite',        streak:15 },
    { rank:3,  name:'OptionsMaster',avatar:'🎯', pnl:167820, pct:167.82, trades:2341, level:'Pro',          streak:31 },
    { rank:4,  name:'BullRunner99', avatar:'🐂', pnl:143290, pct:143.29, trades:567,  level:'Pro',          streak:8  },
    { rank:5,  name:'AlphaSeeker',  avatar:'🚀', pnl:128450, pct:128.45, trades:734,  level:'Pro',          streak:12 },
    { rank:6,  name:'GammaScalper', avatar:'🎲', pnl:112670, pct:112.67, trades:1892, level:'Pro',          streak:19 },
    { rank:7,  name:'ThetaGang',    avatar:'⏰', pnl:98340,  pct:98.34,  trades:445,  level:'Intermediate', streak:7  },
    { rank:8,  name:'VegaVault',    avatar:'💎', pnl:87120,  pct:87.12,  trades:312,  level:'Intermediate', streak:4  },
    { rank:9,  name:'MomentumMax',  avatar:'📈', pnl:76890,  pct:76.89,  trades:623,  level:'Intermediate', streak:9  },
    { rank:10, name:'RiskManager',  avatar:'🛡️', pnl:65430,  pct:65.43,  trades:891,  level:'Intermediate', streak:22 }
  ];

  const CHALLENGES = [
    { id:'weekly_gain',  name:'Weekly Warrior',   desc:'Achieve 10% portfolio gain this week',  icon:'⚔️',  xp:500,  type:'weekly',  target:10, ends:_nextSunday()   },
    { id:'opts_streak',  name:'Options Oracle',   desc:'Win 5 options trades in a row',          icon:'🔮',  xp:750,  type:'weekly',  target:5,  ends:_nextSunday()   },
    { id:'vol_master',   name:'Volatility Master',desc:'Profit from the Earnings scenario',      icon:'💥',  xp:1000, type:'special', target:1,  ends:_nextSunday()   },
    { id:'trade_vol',    name:'Volume King',      desc:'Execute 50 trades this week',            icon:'👑',  xp:600,  type:'weekly',  target:50, ends:_nextSunday()   },
    { id:'risk_disc',    name:'Risk Disciplined', desc:'Keep max drawdown under 5% for 7 days', icon:'🛡️', xp:800,  type:'weekly',  target:7,  ends:_nextSunday()   },
    { id:'daily_profit', name:'Daily Grind',      desc:'Positive P&L for 3 consecutive days',   icon:'📅',  xp:400,  type:'daily',   target:3,  ends:_nextMidnight() }
  ];

  function _nextSunday() {
    const d = new Date(); d.setDate(d.getDate() + (7 - d.getDay())); d.setHours(23,59,59,0); return d.getTime();
  }
  function _nextMidnight() {
    const d = new Date(); d.setDate(d.getDate()+1); d.setHours(0,0,0,0); return d.getTime();
  }
  function _timeLeft(ts) {
    const diff = ts - Date.now(); if (diff<=0) return 'Ended';
    const h = Math.floor(diff/3600000), m = Math.floor((diff%3600000)/60000);
    return h > 24 ? `${Math.floor(h/24)}d ${h%24}h` : `${h}h ${m}m`;
  }
  function _getChallengeProgress(c) {
    const st = SimEngine.getState();
    const g  = st.gamification;
    switch(c.id) {
      case 'weekly_gain':  return Math.max(0, ((SimEngine.portfolioValue()-st.portfolio.startingCash)/st.portfolio.startingCash*100).toFixed(1)*1);
      case 'opts_streak':  return g.optionsWinStreak || 0;
      case 'vol_master':   return (g.completedScenarios||0) > 0 ? 1 : 0;
      case 'trade_vol':    return g.totalTrades || 0;
      case 'risk_disc':    return 0;
      case 'daily_profit': return g.winStreak || 0;
      default:             return 0;
    }
  }

  /* ── Leaderboard ── */
  function renderLeaderboard() {
    const st   = SimEngine.getState();
    const pv   = SimEngine.portfolioValue();
    const pnl  = pv - st.portfolio.startingCash;
    const pct  = (pnl / st.portfolio.startingCash * 100);
    const g    = st.gamification;
    const myEntry = {
      rank:0, name: st.username||'You', avatar:'🤖',
      pnl, pct, trades: g.totalTrades||0,
      level: SimEngine.levelName(g.level||1), streak: g.streak||0, isMe:true
    };
    const all = [...MOCK_LB, myEntry].sort((a,b)=>b.pct-a.pct);
    all.forEach((e,i) => { if(e.isMe) e.rank = i+1; });

    const el = document.getElementById('lb-board');
    if (!el) return;
    const rankEmoji = r => r===1?'🥇':r===2?'🥈':r===3?'🥉':`#${r}`;
    el.innerHTML = all.map(e => `
      <div class="lb-row ${e.isMe?'lb-me':''} ${e.rank<=3?'lb-top':''}">
        <div class="lb-rank">${rankEmoji(e.rank)}</div>
        <div class="lb-avatar">${e.avatar}</div>
        <div class="lb-info">
          <div class="lb-name">${e.name}${e.isMe?' <span class="lb-you-badge">YOU</span>':''}</div>
          <div class="lb-meta">${e.level} • ${e.trades.toLocaleString()} trades • 🔥${e.streak}</div>
        </div>
        <div class="lb-stats">
          <div class="lb-pct ${e.pct>=0?'pos':'neg'}">${e.pct>=0?'+':''}${e.pct.toFixed(1)}%</div>
          <div class="lb-pnl">${e.pnl>=0?'+':''}$${Math.abs(e.pnl).toLocaleString('en',{maximumFractionDigits:0})}</div>
        </div>
      </div>`).join('');

    renderMyRankCard(myEntry);
    renderChallenges();
    renderAchievements();
  }

  function renderMyRankCard(me) {
    const el = document.getElementById('your-rank-card');
    if (!el) return;
    el.innerHTML = `
      <div class="yrk-inner">
        <div class="yrk-rank">#${me.rank}</div>
        <div class="yrk-info">
          <strong>${me.name}</strong>
          <span>${me.level} • 🔥${me.streak} streak</span>
        </div>
        <div class="yrk-stats">
          <span class="${me.pct>=0?'pos':'neg'}">${me.pct>=0?'+':''}${me.pct.toFixed(1)}%</span>
          <span style="font-size:11px;color:var(--text3)">${me.trades} trades</span>
        </div>
      </div>`;
  }

  function renderChallenges() {
    const el = document.getElementById('lb-challenges');
    if (!el) return;
    const st = SimEngine.getState();
    const done = st.gamification.completedChallenges || [];
    el.innerHTML = CHALLENGES.map(c => {
      const isDone = done.includes(c.id);
      const prog   = _getChallengeProgress(c);
      const pct    = Math.min(100, (prog/c.target)*100);
      return `
        <div class="challenge-card ${isDone?'challenge-done':''}">
          <div class="challenge-icon">${c.icon}</div>
          <div class="challenge-body">
            <div class="challenge-name">${c.name}${isDone?' ✅':''}</div>
            <div class="challenge-desc">${c.desc}</div>
            <div class="challenge-meta">
              <span class="challenge-type ${c.type}">${c.type}</span>
              <span class="challenge-xp">+${c.xp} XP</span>
              <span class="challenge-time">⏱ ${_timeLeft(c.ends)}</span>
            </div>
            ${!isDone?`<div class="challenge-progress">
              <div class="challenge-bar"><div class="challenge-fill" style="width:${pct}%"></div></div>
              <span class="challenge-prog-txt">${prog}/${c.target}</span>
            </div>`:'<div class="challenge-complete-msg">Complete! XP Awarded</div>'}
          </div>
        </div>`;
    }).join('');
  }

  function renderAchievements() {
    const el = document.getElementById('achievements-grid');
    if (!el) return;
    const unlocked = SimEngine.getState().gamification.unlockedAchievements || [];
    if (!unlocked.length) { el.innerHTML = '<div class="empty-state">No achievements yet — keep trading!</div>'; return; }
    el.innerHTML = unlocked.map(id => {
      const a = ACHIEVEMENTS.find(a => a.id === id);
      if (!a) return '';
      return `<div class="ach-card"><div class="ach-card-icon">${a.icon}</div><div class="ach-card-name">${a.name}</div><div class="ach-card-xp">+${a.xp} XP</div></div>`;
    }).join('');
  }

  /* ── P&L Card ── */
  let _currentStyle = 'dark';

  function openShareModal(tradeData) {
    const modal = document.getElementById('share-modal');
    if (!modal) return;
    modal.style.display = 'flex';
    const data = tradeData || _buildCardData();
    const canvas = document.getElementById('share-canvas');
    if (canvas) drawCard(canvas, data, _currentStyle);
  }

  function closeShareModal() {
    const modal = document.getElementById('share-modal');
    if (modal) modal.style.display = 'none';
  }

  function _buildCardData() {
    const st  = SimEngine.getState();
    const pv  = SimEngine.portfolioValue();
    const pnl = pv - st.portfolio.startingCash;
    const g   = st.gamification;
    const total = g.wins + g.losses;
    return {
      type:'portfolio', symbol:'PORTFOLIO',
      pnl, pct:(pnl/st.portfolio.startingCash*100),
      portfolio:pv,
      winRate: total ? Math.round(g.wins/total*100) : 0,
      trades: g.totalTrades||0,
      level: SimEngine.levelName(g.level||1),
      xp: g.xp||0, streak:g.streak||0,
      username: st.username||'Trader'
    };
  }

  function drawCard(canvas, data, styleName) {
    const ctx = canvas.getContext('2d');
    const s = CARD_STYLES[styleName] || CARD_STYLES.dark;
    const W = canvas.width, H = canvas.height;

    const grad = ctx.createLinearGradient(0,0,W,H);
    grad.addColorStop(0, s.bg); grad.addColorStop(1, s.bg2);
    ctx.fillStyle = grad; ctx.fillRect(0,0,W,H);

    ctx.save(); ctx.strokeStyle = s.accent; ctx.lineWidth = 2;
    ctx.shadowColor = s.glow; ctx.shadowBlur = 20;
    _roundRect(ctx,2,2,W-4,H-4,16); ctx.stroke(); ctx.restore();

    ctx.save(); ctx.strokeStyle = s.border; ctx.lineWidth=0.5; ctx.globalAlpha=0.4;
    for(let x=40;x<W;x+=80){ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,H);ctx.stroke();}
    for(let y=40;y<H;y+=80){ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(W,y);ctx.stroke();}
    ctx.restore();

    ctx.fillStyle = s.accent; ctx.font = 'bold 16px monospace';
    ctx.fillText('⚡ SQUEEZESIM PRO', 32, 40);
    ctx.fillStyle = s.accent; ctx.fillRect(32,52,W-64,1);

    ctx.fillStyle = s.subtext; ctx.font = '13px monospace';
    ctx.fillText('@'+data.username, 32, 72);
    ctx.fillStyle = s.accent2; ctx.font = 'bold 13px monospace';
    ctx.fillText('LVL: '+data.level, W-180, 72);

    const isPos   = data.pnl >= 0;
    const pnlClr  = isPos ? (styleName==='minimal'?'#00aa44':'#00ff88') : '#ff4466';
    const pnlTxt  = (isPos?'+':'') + '$' + Math.abs(data.pnl).toLocaleString('en',{maximumFractionDigits:0});
    ctx.save(); ctx.fillStyle = pnlClr; ctx.font = 'bold 64px monospace';
    ctx.shadowColor = pnlClr; ctx.shadowBlur = styleName==='minimal'?0:25;
    const pw = ctx.measureText(pnlTxt).width;
    ctx.fillText(pnlTxt, (W-pw)/2, 185); ctx.restore();

    const pctTxt = (isPos?'+':'')+data.pct.toFixed(2)+'%';
    ctx.save(); ctx.fillStyle = pnlClr; ctx.font = 'bold 30px monospace';
    ctx.shadowColor = pnlClr; ctx.shadowBlur = styleName==='minimal'?0:12;
    const qw = ctx.measureText(pctTxt).width;
    ctx.fillText(pctTxt, (W-qw)/2, 228); ctx.restore();

    ctx.fillStyle = s.subtext; ctx.font = '14px monospace';
    const symW = ctx.measureText(data.symbol).width;
    ctx.fillText(data.symbol, (W-symW)/2, 255);

    const stats = [
      {label:'PORTFOLIO', val:'$'+(data.portfolio/1000).toFixed(1)+'K'},
      {label:'WIN RATE',  val:data.winRate+'%'},
      {label:'TRADES',    val:''+data.trades},
      {label:'STREAK',    val:'🔥'+data.streak}
    ];
    const sw = (W-64)/stats.length;
    stats.forEach((st2,i) => {
      const x = 32 + i*sw + sw/2;
      ctx.fillStyle = s.subtext; ctx.font = '10px monospace';
      const lw = ctx.measureText(st2.label).width;
      ctx.fillText(st2.label, x-lw/2, 300);
      ctx.fillStyle = s.text; ctx.font = 'bold 16px monospace';
      const vw = ctx.measureText(st2.val).width;
      ctx.fillText(st2.val, x-vw/2, 320);
    });

    ctx.fillStyle = s.border; ctx.fillRect(32,335,W-64,1);
    ctx.fillStyle = s.accent; ctx.font = '12px monospace';
    ctx.fillText('Trade smarter at SqueezeOS • Educational simulator only', 32, 358);
    return canvas;
  }

  function _roundRect(ctx,x,y,w,h,r) {
    ctx.beginPath(); ctx.moveTo(x+r,y); ctx.lineTo(x+w-r,y);
    ctx.quadraticCurveTo(x+w,y,x+w,y+r); ctx.lineTo(x+w,y+h-r);
    ctx.quadraticCurveTo(x+w,y+h,x+w-r,y+h); ctx.lineTo(x+r,y+h);
    ctx.quadraticCurveTo(x,y+h,x,y+h-r); ctx.lineTo(x,y+r);
    ctx.quadraticCurveTo(x,y,x+r,y); ctx.closePath();
  }

  function setCardStyle(style, btn) {
    _currentStyle = style;
    document.querySelectorAll('.share-style-btn').forEach(b => b.classList.remove('active'));
    if (btn) btn.classList.add('active');
    const canvas = document.getElementById('share-canvas');
    if (canvas) drawCard(canvas, _buildCardData(), style);
  }

  function _buildShareText(data) {
    const d = data || _buildCardData();
    const e = d.pnl>=0?'🚀🟢':'📉🔴';
    return `${e} ${d.pnl>=0?'Made':'Lost'} ${d.pnl>=0?'+':''}$${Math.abs(d.pnl).toLocaleString()} (${d.pct.toFixed(2)}%) on SqueezeOS Simulator!\n\nPortfolio: $${d.portfolio.toLocaleString('en',{maximumFractionDigits:0})} | Win Rate: ${d.winRate}% | Level: ${d.level}\n\n#TradingSimulator #SqueezeOS #PaperTrading #Options`;
  }

  function shareToTwitter() {
    window.open('https://twitter.com/intent/tweet?text='+encodeURIComponent(_buildShareText()), '_blank', 'width=600,height=400');
    SimApp.toast('Opened Twitter/X!', 'success');
  }
  function shareToReddit() {
    const d = _buildCardData();
    const t = encodeURIComponent(`SqueezeOS Sim: ${d.pnl>=0?'+':''}$${Math.abs(d.pnl).toLocaleString()} (${d.pct.toFixed(2)}%)`);
    window.open('https://www.reddit.com/r/wallstreetbets/submit?title='+t+'&text='+encodeURIComponent(_buildShareText(d)), '_blank');
    SimApp.toast('Opened Reddit!', 'success');
  }
  async function copyDiscord() {
    try { await navigator.clipboard.writeText(_buildShareText()); SimApp.toast('Copied for Discord!','success'); }
    catch { SimApp.toast('Copy failed','error'); }
  }
  async function copyImage() {
    const canvas = document.getElementById('share-canvas');
    if (!canvas) return;
    try {
      canvas.toBlob(async blob => {
        await navigator.clipboard.write([new ClipboardItem({'image/png':blob})]);
        SimApp.toast('Image copied!','success');
      });
    } catch { SimApp.toast('Image copy not supported in this browser','warn'); }
  }
  function downloadCard() {
    const canvas = document.getElementById('share-canvas');
    if (!canvas) return;
    const a = document.createElement('a');
    a.download = 'squeezesim-pnl-'+Date.now()+'.png';
    a.href = canvas.toDataURL('image/png'); a.click();
    SimApp.toast('Card downloaded!','success');
  }
  async function copyLink() {
    try { await navigator.clipboard.writeText(window.location.href); SimApp.toast('Link copied!','success'); }
    catch { SimApp.toast('Could not copy link','error'); }
  }

  function shareTradeCard(sym, pnl, pct) {
    const st = SimEngine.getState();
    const g  = st.gamification;
    const total = g.wins + g.losses;
    openShareModal({
      type:'trade', symbol:sym, pnl, pct,
      portfolio: SimEngine.portfolioValue(),
      winRate: total?Math.round(g.wins/total*100):0,
      trades: g.totalTrades||0,
      level: SimEngine.levelName(g.level||1),
      xp:g.xp||0, streak:g.streak||0, username:st.username||'Trader'
    });
  }

  /* ── Init / Render ── */
  function init() {
    const lbPeriod = document.getElementById('lb-period');
    if (lbPeriod) lbPeriod.addEventListener('change', renderLeaderboard);
  }

  function render() {
    renderLeaderboard();
  }

  return {
    init, render,
    renderLeaderboard, renderChallenges, renderAchievements,
    openShareModal, closeShareModal,
    setCardStyle, drawCard,
    shareToTwitter, shareToReddit, copyDiscord, copyImage, downloadCard, copyLink,
    shareTradeCard, CARD_STYLES
  };
})();
