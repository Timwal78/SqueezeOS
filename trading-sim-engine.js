/* ═══════════════════════════════════════════════════════
   SQUEEZESIM ENGINE — Market Simulation + Portfolio + Gamification
   ═══════════════════════════════════════════════════════ */

const STOCKS = {
  SPY:  { name:'SPDR S&P 500 ETF',      price:445.20, iv:0.14, sector:'etf',     cap:'3.2T', vol:80000000 },
  QQQ:  { name:'Invesco QQQ Trust',      price:378.50, iv:0.17, sector:'etf',     cap:'1.8T', vol:45000000 },
  IWM:  { name:'iShares Russell 2000',   price:198.40, iv:0.21, sector:'etf',     cap:'0.6T', vol:30000000 },
  AAPL: { name:'Apple Inc.',             price:189.50, iv:0.22, sector:'tech',    cap:'2.9T', vol:55000000 },
  MSFT: { name:'Microsoft Corp.',        price:415.30, iv:0.20, sector:'tech',    cap:'3.1T', vol:22000000 },
  NVDA: { name:'NVIDIA Corp.',           price:875.40, iv:0.45, sector:'tech',    cap:'2.2T', vol:40000000 },
  TSLA: { name:'Tesla Inc.',             price:245.80, iv:0.55, sector:'tech',    cap:'0.8T', vol:90000000 },
  AMD:  { name:'Advanced Micro Devices', price:168.20, iv:0.48, sector:'tech',    cap:'0.3T', vol:50000000 },
  META: { name:'Meta Platforms',         price:502.10, iv:0.35, sector:'tech',    cap:'1.3T', vol:18000000 },
  GOOGL:{ name:'Alphabet Inc.',          price:174.20, iv:0.24, sector:'tech',    cap:'2.2T', vol:25000000 },
  AMZN: { name:'Amazon.com Inc.',        price:195.80, iv:0.28, sector:'tech',    cap:'2.1T', vol:35000000 },
  NFLX: { name:'Netflix Inc.',           price:628.40, iv:0.38, sector:'tech',    cap:'0.3T', vol:8000000  },
  JPM:  { name:'JPMorgan Chase',         price:198.60, iv:0.22, sector:'finance', cap:'0.6T', vol:12000000 },
  GS:   { name:'Goldman Sachs',          price:468.20, iv:0.25, sector:'finance', cap:'0.2T', vol:3000000  },
  BAC:  { name:'Bank of America',        price:38.40,  iv:0.28, sector:'finance', cap:'0.3T', vol:38000000 },
  XOM:  { name:'Exxon Mobil',            price:112.30, iv:0.24, sector:'energy',  cap:'0.5T', vol:15000000 },
  CVX:  { name:'Chevron Corp.',          price:158.70, iv:0.22, sector:'energy',  cap:'0.3T', vol:10000000 },
  PFE:  { name:'Pfizer Inc.',            price:27.80,  iv:0.30, sector:'biotech', cap:'0.2T', vol:40000000 },
  MRNA: { name:'Moderna Inc.',           price:98.40,  iv:0.65, sector:'biotech', cap:'0.04T',vol:15000000 },
  COIN: { name:'Coinbase Global',        price:228.50, iv:0.75, sector:'finance', cap:'0.06T',vol:12000000 },
  AMC:  { name:'AMC Entertainment',      price:4.80,   iv:1.20, sector:'meme',   cap:'0.003T',vol:60000000},
  GME:  { name:'GameStop Corp.',         price:18.60,  iv:0.95, sector:'meme',   cap:'0.008T',vol:8000000 },
  BBBY: { name:'Bed Bath & Beyond',      price:1.20,   iv:1.80, sector:'meme',   cap:'0.001T',vol:30000000},
  MSTR: { name:'MicroStrategy Inc.',     price:1285.0, iv:0.90, sector:'finance', cap:'0.02T', vol:2000000 },
  PLTR: { name:'Palantir Technologies',  price:24.80,  iv:0.58, sector:'tech',   cap:'0.05T', vol:45000000},
  SOFI: { name:'SoFi Technologies',      price:8.40,   iv:0.62, sector:'finance', cap:'0.009T',vol:25000000},
  RIVN: { name:'Rivian Automotive',      price:14.20,  iv:0.82, sector:'tech',   cap:'0.014T',vol:20000000},
  LCID: { name:'Lucid Group Inc.',       price:2.80,   iv:0.95, sector:'tech',   cap:'0.006T',vol:18000000},
  NIO:  { name:'NIO Inc.',               price:6.40,   iv:0.85, sector:'tech',   cap:'0.012T',vol:35000000},
  HOOD: { name:'Robinhood Markets',      price:18.20,  iv:0.70, sector:'finance', cap:'0.016T',vol:15000000},
};

const SCENARIOS = [
  { id:'crash',      name:'Market Crash',        icon:'💥', desc:'Markets plunge 8% in a single session. Can you survive and profit?', obj:'Protect capital or profit from the crash',  drift:-0.08, vol:2.5,  diff:'advanced',    xp:200, time:300 },
  { id:'bull_run',   name:'Bull Run',             icon:'🚀', desc:'Everything is going up. Maximize your gains in the rally.',         obj:'Achieve +15% return in the session',         drift:0.05,  vol:0.8,  diff:'beginner',     xp:100, time:240 },
  { id:'earnings',   name:'Earnings Roulette',    icon:'📋', desc:'Big tech earnings week. High IV, huge moves both ways.',            obj:'Trade earnings plays successfully',          drift:0.0,   vol:3.0,  diff:'intermediate', xp:150, time:300 },
  { id:'squeeze',    name:'Short Squeeze',        icon:'🌋', desc:'A heavily shorted stock goes parabolic. Time your entry.',         obj:'Catch the squeeze and exit with profit',     drift:0.15,  vol:4.0,  diff:'advanced',     xp:250, time:180 },
  { id:'sideways',   name:'Chop Zone',            icon:'➡️', desc:'Markets go nowhere. Learn to trade range and collect premium.',    obj:'Generate income with options in flat market',drift:0.0,   vol:0.3,  diff:'intermediate', xp:120, time:240 },
  { id:'fed_day',    name:'Fed Decision Day',     icon:'🏛️', desc:'FOMC announcement causes wild swings. React fast.',               obj:'Profit from the volatility spike',           drift:0.0,   vol:2.8,  diff:'advanced',     xp:180, time:120 },
  { id:'beginner',   name:'First Trade',          icon:'🌱', desc:'A gentle introduction. Practice buying and selling basics.',       obj:'Complete 3 successful trades',               drift:0.01,  vol:0.5,  diff:'beginner',     xp:50,  time:600 },
  { id:'options101', name:'Options Basics',       icon:'📐', desc:'Learn to buy calls and puts in a trending market.',               obj:'Buy a call and a put successfully',          drift:0.03,  vol:1.0,  diff:'beginner',     xp:75,  time:480 },
  { id:'recovery',   name:'Recovery Rally',       icon:'🔄', desc:'Markets bouncing hard off lows. Catch the knife or ride the wave.',obj:'Buy the dip and profit on the recovery',     drift:0.06,  vol:1.8,  diff:'intermediate', xp:130, time:300 },
];

const ACHIEVEMENTS = [
  { id:'first_trade',   name:'First Blood',        icon:'⚔️',  desc:'Execute your first trade',             xp:25,  condition: s => s.totalTrades >= 1 },
  { id:'first_win',     name:'Winner',             icon:'🏆',  desc:'Close your first profitable trade',    xp:50,  condition: s => s.wins >= 1 },
  { id:'ten_trades',    name:'Active Trader',      icon:'⚡',  desc:'Complete 10 trades',                   xp:100, condition: s => s.totalTrades >= 10 },
  { id:'fifty_trades',  name:'Grinder',            icon:'💪',  desc:'Complete 50 trades',                   xp:250, condition: s => s.totalTrades >= 50 },
  { id:'first_option',  name:'Option Explorer',    icon:'🔗',  desc:'Buy your first option',                xp:75,  condition: s => s.optionTrades >= 1 },
  { id:'win_streak_3',  name:'Hot Hand',           icon:'🔥',  desc:'Win 3 trades in a row',               xp:100, condition: s => s.maxWinStreak >= 3 },
  { id:'win_streak_5',  name:'Unstoppable',        icon:'🌋',  desc:'Win 5 trades in a row',               xp:200, condition: s => s.maxWinStreak >= 5 },
  { id:'profit_1k',     name:'First $1K',          icon:'💵',  desc:'Earn $1,000 in total profit',         xp:150, condition: s => s.totalProfit >= 1000 },
  { id:'profit_10k',    name:'Five Figures',       icon:'💰',  desc:'Earn $10,000 in total profit',        xp:500, condition: s => s.totalProfit >= 10000 },
  { id:'return_10pct',  name:'Double Digit Return',icon:'📈',  desc:'Achieve 10% portfolio return',        xp:200, condition: s => s.portfolioReturn >= 0.10 },
  { id:'return_50pct',  name:'Big Gains',          icon:'🚀',  desc:'Achieve 50% portfolio return',        xp:500, condition: s => s.portfolioReturn >= 0.50 },
  { id:'return_100pct', name:'Double Up',          icon:'💎',  desc:'Double your starting capital',        xp:1000,condition: s => s.portfolioReturn >= 1.00 },
  { id:'loss_recovery', name:'Comeback Kid',       icon:'💪',  desc:'Recover from a -20% drawdown',        xp:300, condition: s => s.hadBigDrawdown && s.portfolioReturn > 0 },
  { id:'options_10',    name:'Options Addict',     icon:'🎯',  desc:'Trade 10 options contracts',          xp:150, condition: s => s.optionTrades >= 10 },
  { id:'all_lessons',   name:'Scholar',            icon:'🎓',  desc:'Complete all beginner lessons',       xp:200, condition: s => s.beginnerLessonsComplete >= 8 },
  { id:'daily_streak_7',name:'Dedicated',          icon:'🗓️', desc:'7-day trading streak',                xp:175, condition: s => s.streak >= 7 },
  { id:'daily_streak_30',name:'Committed',         icon:'🏅',  desc:'30-day trading streak',               xp:500, condition: s => s.streak >= 30 },
  { id:'sector_div',    name:'Diversified',        icon:'🌐',  desc:'Hold stocks in 4+ different sectors', xp:100, condition: s => s.sectorCount >= 4 },
  { id:'scenario_win',  name:'Scenario Master',    icon:'🎮',  desc:'Complete a trading scenario',         xp:150, condition: s => s.scenariosComplete >= 1 },
  { id:'share_pnl',     name:'Influencer',         icon:'📤',  desc:'Share your P&L card',                 xp:50,  condition: s => s.sharedPnL >= 1 },
];

const SUBSCRIPTION_PLANS = [
  {
    id: 'free', name: 'Free', price: 0, period: '',
    color: '#888',
    features: ['$10,000 paper capital','3 beginner lessons','Basic stock trading','Limited watchlist (5)','Basic portfolio stats'],
    locked: ['Options chain','Strategy builder','AI Coach','Backtester','Full Academy','Social features'],
  },
  {
    id: 'starter', name: 'Starter', price: 9.99, period: '/mo',
    color: '#00d4ff',
    popular: false,
    features: ['$100,000 paper capital','All beginner & intermediate lessons','Full options chain','All strategies library','Unlimited watchlist','Portfolio analytics','Social sharing & leaderboard'],
    locked: ['AI Coach (BYOK)','Backtester','Professional lessons'],
  },
  {
    id: 'pro', name: 'Pro', price: 24.99, period: '/mo',
    color: '#a855f7',
    popular: true,
    features: ['$1,000,000 paper capital','Full Academy (all levels)','AI Coach (BYOK)','Backtester','Advanced analytics','Priority support','Scenario challenges','Weekly challenges'],
    locked: [],
  },
  {
    id: 'elite', name: 'Elite', price: 49.99, period: '/mo',
    color: '#FF1493',
    features: ['Unlimited paper capital','Everything in Pro','Custom scenarios','API data integration','Dedicated coaching sessions','White-label for teams','KDP workbook generator','Analytics dashboard'],
    locked: [],
  },
];

/* ─── STATE ─── */
const _state = {
  symbols: {},          // live price data
  portfolio: {
    cash: 10000,
    startingCash: 10000,
    positions: {},      // symbol -> { qty, avgCost, type }
    history: [],        // closed trades
    equityCurve: [],    // [{ts, value}]
    dayStartValue: 10000,
  },
  market: { scenario: 'normal', speed: 3000, tickTimer: null },
  gamification: {
    xp: 0, level: 1, streak: 0, lastActive: null,
    totalTrades: 0, wins: 0, losses: 0, winStreak: 0, maxWinStreak: 0,
    optionTrades: 0, totalProfit: 0, portfolioReturn: 0,
    hadBigDrawdown: false, beginnerLessonsComplete: 0,
    scenariosComplete: 0, sectorCount: 0, sharedPnL: 0,
    unlockedAchievements: [],
  },
  subscription: 'elite',
  ui: {
    currentView: 'dashboard',
    currentSymbol: 'SPY',
    orderSide: 'BUY',
    orderType: 'market',
    tradeMode: 'stock',
    chartTF: '1m',
    perfPeriod: '1D',
    chartData: {},       // symbol -> [{ts,o,h,l,c,v}]
    perfChart: null,
    tradeChart: null,
    settings: { sound: false, riskWarn: true, difficulty: 'intermediate', commission: 0 },
  },
  pwaInstallPrompt: null,
  scenario: { active: false, id: null, timer: null, startPV: 0, startTs: 0, endTs: 0 },
};

/* ─── HELPERS ─── */
const $ = id => document.getElementById(id);
const fmt  = n => '$' + Math.abs(n).toLocaleString('en-US', {minimumFractionDigits:2, maximumFractionDigits:2});
const fmtS = n => (n >= 0 ? '+' : '-') + fmt(n);
const fmtP = n => (n >= 0 ? '+' : '') + (n * 100).toFixed(2) + '%';
const rnd  = (lo, hi) => lo + Math.random() * (hi - lo);
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

function normRnd() {
  let u = 0, v = 0;
  while (!u) u = Math.random();
  while (!v) v = Math.random();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
}

/* GBM price tick */
function gbmTick(price, annualDrift, annualVol, dt = 1/252) {
  const mu = annualDrift - 0.5 * annualVol * annualVol;
  return price * Math.exp(mu * dt + annualVol * Math.sqrt(dt) * normRnd());
}

/* ─── MARKET ENGINE ─── */
const SimEngine = (() => {

  function init() {
    _state.symbols = {};
    Object.entries(STOCKS).forEach(([sym, d]) => {
      const p = d.price * (1 + rnd(-0.01, 0.01));
      _state.symbols[sym] = {
        ...d, sym,
        price: p, open: p, high: p, low: p,
        prevClose: d.price,
        iv: d.iv * (1 + rnd(-0.1, 0.1)),
        vol: Math.round(d.vol * rnd(0.5, 1.5)),
        change: 0, changePct: 0,
      };
    });
    _state.ui.chartData = {};
    // seed chart data for each symbol
    Object.keys(_state.symbols).forEach(sym => seedChart(sym));
    startTicker();
  }

  function seedChart(sym) {
    const s = _state.symbols[sym];
    const bars = 120;
    let p = s.prevClose;
    const data = [];
    for (let i = bars; i >= 0; i--) {
      const o = p;
      const c = gbmTick(p, 0.0, s.iv, 1/bars);
      const h = Math.max(o, c) * (1 + Math.random() * 0.003);
      const l = Math.min(o, c) * (1 - Math.random() * 0.003);
      data.push({ ts: Date.now() - i * 60000, o, h, l, c, v: Math.round(s.vol / bars * rnd(0.5, 2)) });
      p = c;
    }
    _state.ui.chartData[sym] = data;
  }

  function tickMarket() {
    const scenarioParams = {
      normal:   { drift: 0.0,   vol: 1.0 },
      bull:     { drift: 0.05,  vol: 0.8 },
      bear:     { drift: -0.04, vol: 1.2 },
      volatile: { drift: 0.0,   vol: 2.5 },
      sideways: { drift: 0.0,   vol: 0.3 },
      crash:    { drift: -0.08, vol: 3.0 },
      recovery: { drift: 0.06,  vol: 1.5 },
      earnings: { drift: 0.0,   vol: 2.8 },
    };
    const p = scenarioParams[_state.market.scenario] || scenarioParams.normal;

    Object.values(_state.symbols).forEach(s => {
      const drift = p.drift + (Math.random() - 0.5) * 0.02;
      const vol   = s.iv * p.vol;
      const newP  = gbmTick(s.price, drift, vol, 1/390);
      const newP2 = Math.max(newP, 0.01);
      s.price = +newP2.toFixed(2);
      s.high = Math.max(s.high, s.price);
      s.low  = Math.min(s.low, s.price);
      s.change = s.price - s.prevClose;
      s.changePct = s.change / s.prevClose;
      s.vol = Math.round(s.vol * 1.001 + Math.random() * 10000);
      // nudge IV
      s.iv = clamp(s.iv * (1 + (Math.random() - 0.5) * 0.02), 0.05, 3.0);

      // append to chart
      const bar = { ts: Date.now(), o: s.open, h: s.high, l: s.low, c: s.price, v: s.vol };
      if (!_state.ui.chartData[s.sym]) _state.ui.chartData[s.sym] = [];
      _state.ui.chartData[s.sym].push(bar);
      if (_state.ui.chartData[s.sym].length > 390) _state.ui.chartData[s.sym].shift();
    });

    // update portfolio mark-to-market
    markPortfolio();
    recordEquity();
    updateAllUI();
    checkScenario();
  }

  function startTicker() {
    if (_state.market.tickTimer) clearInterval(_state.market.tickTimer);
    const speed = parseInt($('set-speed')?.value || '3000');
    if (speed <= 0) return;
    _state.market.tickTimer = setInterval(tickMarket, speed);
  }

  function setSpeed(val) {
    _state.market.speed = parseInt(val);
    startTicker();
  }

  function setAutoTick(on) {
    if (on) startTicker();
    else { clearInterval(_state.market.tickTimer); _state.market.tickTimer = null; }
  }

  function setScenario(sc) {
    _state.market.scenario = sc;
    SimApp.toast(`📊 Scenario: ${sc.toUpperCase()}`, 'info');
  }

  function setDifficulty(d) {
    _state.ui.settings.difficulty = d;
    saveState();
  }

  function setCapital(val) {
    const cap = parseFloat(val);
    const tier = _state.subscription;
    const allowed = { free:10000, starter:100000, pro:1000000, elite:Infinity };
    if (cap > allowed[tier]) {
      SimApp.showUpgradeModal('pro');
      return;
    }
    _state.portfolio.cash = cap;
    _state.portfolio.startingCash = cap;
    _state.portfolio.dayStartValue = cap;
    _state.portfolio.positions = {};
    _state.portfolio.history = [];
    _state.portfolio.equityCurve = [];
    recordEquity();
    SimApp.updateDashboard();
    saveState();
    SimApp.toast('💰 Capital reset to ' + fmt(cap), 'success');
  }

  function markPortfolio() {
    const pos = _state.portfolio.positions;
    Object.entries(pos).forEach(([sym, p]) => {
      const s = _state.symbols[sym];
      if (!s) return;
      if (p.type === 'stock') {
        p.currentPrice = s.price;
        p.unrealizedPnL = (s.price - p.avgCost) * p.qty;
      } else if (p.type === 'option') {
        const optPrice = OptionsEngine.calcPrice(s.price, p.strike, p.dte / 365, s.iv, p.optType);
        p.currentPrice = optPrice;
        p.unrealizedPnL = (optPrice - p.avgCost) * p.qty * 100;
        p.dte = Math.max(0, p.dte - 1 / 390);
      }
    });
  }

  function recordEquity() {
    const pv = portfolioValue();
    _state.portfolio.equityCurve.push({ ts: Date.now(), value: pv });
    if (_state.portfolio.equityCurve.length > 10000) _state.portfolio.equityCurve.shift();
  }

  function portfolioValue() {
    const pos = _state.portfolio.positions;
    let pv = _state.portfolio.cash;
    Object.values(pos).forEach(p => {
      pv += p.type === 'stock' ? p.currentPrice * p.qty : p.currentPrice * p.qty * 100;
    });
    return pv;
  }

  function executeTrade() {
    const sym   = _state.ui.currentSymbol;
    const s     = _state.symbols[sym];
    const side  = _state.ui.orderSide;
    const type  = _state.ui.orderType;
    const qty   = parseInt($('order-qty').value);
    const comm  = parseFloat($('set-comm')?.value || '0');

    if (!qty || qty < 1) { SimApp.toast('⚠️ Enter a valid quantity', 'error'); return; }

    let execPrice = s.price;
    if (type === 'limit') {
      execPrice = parseFloat($('limit-price').value) || s.price;
    }

    const cost = execPrice * qty + comm;

    if (side === 'BUY') {
      if (cost > _state.portfolio.cash) {
        SimApp.toast('⚠️ Insufficient buying power', 'error');
        return;
      }
      _state.portfolio.cash -= cost;
      const pos = _state.portfolio.positions;
      if (pos[sym] && pos[sym].type === 'stock') {
        const totalCost = pos[sym].avgCost * pos[sym].qty + execPrice * qty;
        pos[sym].qty += qty;
        pos[sym].avgCost = totalCost / pos[sym].qty;
        pos[sym].currentPrice = execPrice;
      } else {
        pos[sym] = { sym, type:'stock', qty, avgCost:execPrice, currentPrice:execPrice, unrealizedPnL:0, sector: s.sector };
      }
    } else {
      const pos = _state.portfolio.positions[sym];
      if (!pos || pos.qty < qty) { SimApp.toast('⚠️ Not enough shares to sell', 'error'); return; }
      const pnl = (execPrice - pos.avgCost) * qty - comm;
      _state.portfolio.cash += execPrice * qty - comm;
      pos.qty -= qty;
      if (pos.qty === 0) delete _state.portfolio.positions[sym];

      recordClosedTrade(sym, 'stock', 'SELL', qty, pos.avgCost, execPrice, pnl);
      updateStats(pnl);
    }

    markPortfolio();
    recordEquity();

    const action = side === 'BUY' ? '🟢 Bought' : '🔴 Sold';
    SimApp.toast(`${action} ${qty} ${sym} @ ${fmt(execPrice)}`, side === 'BUY' ? 'success' : 'info');
    if (_state.ui.settings.sound) playSound(side === 'BUY' ? 'buy' : 'sell');

    _state.gamification.totalTrades++;
    if (_state.portfolio.positions[sym]) {
      const sectors = new Set(Object.values(_state.portfolio.positions).map(p => _state.symbols[p.sym]?.sector));
      _state.gamification.sectorCount = sectors.size;
    }
    checkAchievements();
    saveState();
    SimApp.updateDashboard();
    SimApp.updateTradeView();
  }

  function executeOptionTrade(sym, strike, expiry, optType, side, qty) {
    const s     = _state.symbols[sym];
    const dte   = Math.max(1, Math.round((new Date(expiry) - new Date()) / 86400000));
    const price = OptionsEngine.calcPrice(s.price, strike, dte / 365, s.iv, optType);
    const cost  = price * qty * 100;
    const comm  = parseFloat($('set-comm')?.value || '0') * qty;

    if (side === 'BUY') {
      if (cost + comm > _state.portfolio.cash) { SimApp.toast('⚠️ Insufficient buying power', 'error'); return; }
      _state.portfolio.cash -= (cost + comm);
      const key = `${sym}_${strike}_${expiry}_${optType}`;
      const pos = _state.portfolio.positions;
      if (pos[key]) {
        pos[key].qty += qty;
      } else {
        pos[key] = { sym, type:'option', optType, strike, expiry, dte, qty, avgCost:price, currentPrice:price, unrealizedPnL:0, sector: s.sector };
      }
    } else {
      const key = `${sym}_${strike}_${expiry}_${optType}`;
      const pos = _state.portfolio.positions[key];
      if (!pos || pos.qty < qty) { SimApp.toast('⚠️ Insufficient option contracts', 'error'); return; }
      const pnl = (price - pos.avgCost) * qty * 100 - comm;
      _state.portfolio.cash += price * qty * 100 - comm;
      pos.qty -= qty;
      if (pos.qty === 0) delete _state.portfolio.positions[key];
      recordClosedTrade(sym, 'option', 'SELL', qty, pos.avgCost, price, pnl);
      updateStats(pnl);
    }

    _state.gamification.optionTrades++;
    _state.gamification.totalTrades++;
    checkAchievements();
    saveState();
    markPortfolio();
    SimApp.toast(`${side === 'BUY' ? '🟢' : '🔴'} ${side} ${qty} ${sym} ${strike}${optType[0].toUpperCase()} @ ${fmt(price)}`, side === 'BUY' ? 'success' : 'info');
    SimApp.updateDashboard();
  }

  function closePosition(sym) {
    const pos = _state.portfolio.positions[sym];
    if (!pos) return;
    const s = _state.symbols[sym];
    if (!s) return;
    const pnl = (s.price - pos.avgCost) * pos.qty;
    _state.portfolio.cash += s.price * pos.qty;
    delete _state.portfolio.positions[sym];
    recordClosedTrade(sym, 'stock', 'SELL', pos.qty, pos.avgCost, s.price, pnl);
    updateStats(pnl);
    SimApp.toast(`Closed ${sym}: ${fmtS(pnl)}`, pnl >= 0 ? 'success' : 'error');
    checkAchievements();
    saveState();
    markPortfolio();
    SimApp.updateDashboard();
    SimApp.updateTradeView();
  }

  function recordClosedTrade(sym, type, side, qty, entry, exit, pnl) {
    _state.portfolio.history.unshift({
      sym, type, side, qty, entry, exit, pnl,
      returnPct: (exit - entry) / entry,
      ts: Date.now(),
      held: '< 1 day',
    });
    if (_state.portfolio.history.length > 500) _state.portfolio.history.pop();
  }

  function updateStats(pnl) {
    if (pnl > 0) {
      _state.gamification.wins++;
      _state.gamification.winStreak++;
      _state.gamification.maxWinStreak = Math.max(_state.gamification.maxWinStreak, _state.gamification.winStreak);
      _state.gamification.xp += Math.min(Math.floor(pnl / 10), 50);
    } else {
      _state.gamification.losses++;
      _state.gamification.winStreak = 0;
    }
    _state.gamification.totalProfit += pnl;
    const pv = portfolioValue();
    _state.gamification.portfolioReturn = (pv - _state.portfolio.startingCash) / _state.portfolio.startingCash;
    if (_state.gamification.portfolioReturn < -0.20) _state.gamification.hadBigDrawdown = true;
    updateLevel();
  }

  function updateLevel() {
    const xp = _state.gamification.xp;
    const thresholds = [0, 100, 300, 600, 1000, 1600, 2400, 3500, 5000, 7000, 10000];
    let level = 1;
    for (let i = 0; i < thresholds.length; i++) {
      if (xp >= thresholds[i]) level = i + 1;
    }
    _state.gamification.level = Math.min(level, 11);
    SimApp.updateXPBar();
  }

  function levelName(level) {
    const names = ['','NOVICE','APPRENTICE','TRADER','SKILLED','EXPERT','VETERAN','MASTER','LEGEND','ELITE','INSTITUTIONAL','GOD MODE'];
    return names[level] || 'MASTER';
  }

  function checkAchievements() {
    const g = _state.gamification;
    ACHIEVEMENTS.forEach(ach => {
      if (!g.unlockedAchievements.includes(ach.id) && ach.condition(g)) {
        g.unlockedAchievements.push(ach.id);
        g.xp += ach.xp;
        updateLevel();
        SimApp.showAchievement(ach);
        saveState();
      }
    });
  }

  function awardXP(amount, reason) {
    _state.gamification.xp += amount;
    updateLevel();
    SimApp.toast(`✨ +${amount} XP — ${reason}`, 'success');
  }

  function updateStreak() {
    const today = new Date().toDateString();
    if (_state.gamification.lastActive === today) return;
    const yesterday = new Date(Date.now() - 86400000).toDateString();
    if (_state.gamification.lastActive === yesterday) {
      _state.gamification.streak++;
    } else if (_state.gamification.lastActive !== today) {
      _state.gamification.streak = 1;
    }
    _state.gamification.lastActive = today;
    saveState();
  }

  function checkScenario() {
    if (!_state.scenario.active) return;
    const now = Date.now();
    if (now >= _state.scenario.endTs) {
      endScenario();
    } else {
      const sc = SCENARIOS.find(s => s.id === _state.scenario.id);
      const timeLeft = Math.ceil((_state.scenario.endTs - now) / 1000);
      const pv = portfolioValue();
      const pnl = pv - _state.scenario.startPV;
      if ($('hud-time')) $('hud-time').textContent = timeLeft + 's';
      if ($('hud-pnl')) { $('hud-pnl').textContent = fmtS(pnl); $('hud-pnl').className = 'hs-v ' + (pnl >= 0 ? 'pos' : 'neg'); }
    }
  }

  function startScenario(id) {
    const sc = SCENARIOS.find(s => s.id === id);
    if (!sc) return;
    _state.scenario = { active: true, id, startPV: portfolioValue(), startTs: Date.now(), endTs: Date.now() + sc.time * 1000 };
    _state.market.scenario = id in {crash:1,bull_run:1,earnings:1,squeeze:1,sideways:1,fed_day:1,recovery:1} ? id : 'normal';
    const hud = $('scenario-hud');
    if (hud) { hud.style.display = 'flex'; $('hud-title').textContent = sc.name; $('hud-obj').textContent = sc.obj; }
    SimApp.toast(`🎮 Scenario started: ${sc.name}`, 'info');
  }

  function endScenario() {
    if (!_state.scenario.active) return;
    const sc = SCENARIOS.find(s => s.id === _state.scenario.id);
    const pv = portfolioValue();
    const pnl = pv - _state.scenario.startPV;
    const pct = pnl / _state.scenario.startPV;
    _state.scenario.active = false;
    _state.market.scenario = 'normal';
    const hud = $('scenario-hud');
    if (hud) hud.style.display = 'none';
    _state.gamification.scenariosComplete++;
    awardXP(sc.xp, `Scenario: ${sc.name}`);
    checkAchievements();
    saveState();

    const modal = $('scenario-complete-modal');
    if (modal) {
      $('scenario-result-content').innerHTML = `
        <div style="font-size:48px;margin-bottom:12px">${pnl >= 0 ? '🏆' : '📉'}</div>
        <h2 style="font-size:22px;font-weight:900;color:#fff;margin-bottom:8px">${pnl >= 0 ? 'Scenario Complete!' : 'Better Luck Next Time'}</h2>
        <div style="font-size:28px;font-weight:900;font-family:var(--mono);margin-bottom:4px;color:${pnl>=0?'#00ff88':'#ff4757'}">${fmtS(pnl)} (${fmtP(pct)})</div>
        <div style="color:var(--text2);margin-bottom:20px">${sc.name}</div>
        <div style="color:#ffe600;font-family:var(--mono);font-weight:700;margin-bottom:20px">+${sc.xp} XP Earned</div>
        <button class="btn-primary" onclick="SimApp.closeModal('scenario-complete-modal')" style="margin-right:8px">Continue</button>
        <button class="btn-glass" onclick="SimEngine.startScenario('${sc.id}')">Try Again</button>`;
      modal.style.display = 'flex';
    }
  }

  function exportCSV() {
    const rows = [['Symbol','Type','Side','Qty','Entry','Exit','PnL','Return%','Date']];
    _state.portfolio.history.forEach(t => {
      rows.push([t.sym, t.type, t.side, t.qty, t.entry.toFixed(2), t.exit.toFixed(2), t.pnl.toFixed(2), (t.returnPct*100).toFixed(2)+'%', new Date(t.ts).toLocaleDateString()]);
    });
    const csv = rows.map(r => r.join(',')).join('\n');
    const a = document.createElement('a');
    a.href = 'data:text/csv,' + encodeURIComponent(csv);
    a.download = 'squeezesim_trades.csv';
    a.click();
  }

  function exportData() {
    const data = JSON.stringify({ portfolio: _state.portfolio, gamification: _state.gamification, subscription: _state.subscription });
    const a = document.createElement('a');
    a.href = 'data:application/json,' + encodeURIComponent(data);
    a.download = 'squeezesim_backup.json';
    a.click();
  }

  function resetAll() {
    if (!confirm('⚠️ Reset ALL data? This cannot be undone.')) return;
    localStorage.removeItem('squeezesim_state');
    location.reload();
  }

  function saveState() {
    try {
      localStorage.setItem('squeezesim_state', JSON.stringify({
        portfolio: _state.portfolio,
        gamification: _state.gamification,
        subscription: _state.subscription,
        settings: _state.ui.settings,
      }));
    } catch(e) {}
  }

  function loadState() {
    try {
      const raw = localStorage.getItem('squeezesim_state');
      if (!raw) return;
      const d = JSON.parse(raw);
      if (d.portfolio) Object.assign(_state.portfolio, d.portfolio);
      if (d.gamification) Object.assign(_state.gamification, d.gamification);
      if (d.subscription) _state.subscription = d.subscription;
      if (d.settings) Object.assign(_state.ui.settings, d.settings);
    } catch(e) {}
  }

  return {
    init, tickMarket, setSpeed, setAutoTick, setScenario, setDifficulty, setCapital,
    executeTrade, executeOptionTrade, closePosition, endScenario, startScenario,
    portfolioValue, markPortfolio, awardXP, checkAchievements, updateStreak,
    exportCSV, exportData, resetAll, saveState, loadState,
    levelName, LEVELS: ['','NOVICE','APPRENTICE','TRADER','SKILLED','EXPERT','VETERAN','MASTER','LEGEND','ELITE','INSTITUTIONAL','GOD MODE'],
    getState: () => _state,
  };
})();

/* ─── BACKTESTER ─── */
const Backtester = (() => {
  function run() {
    const sym    = $('bt-sym').value;
    const strat  = $('bt-strat').value;
    const days   = parseInt($('bt-period').value);
    const cap    = parseFloat($('bt-capital').value);
    const comm   = parseFloat($('bt-comm').value || '0');
    const slip   = parseFloat($('bt-slip').value || '0.001');

    // Generate synthetic historical prices
    const s = _state.symbols[sym];
    if (!s) return;
    let price = s.prevClose;
    const prices = [price];
    for (let i = 1; i <= days; i++) {
      price = gbmTick(price, 0.08/252, s.iv, 1);
      prices.push(price);
    }

    let cash = cap, shares = 0, trades = [], inPos = false, entryPrice = 0;
    const equityCurve = [cap];

    // Strategy logic
    for (let i = 20; i < prices.length; i++) {
      const window = prices.slice(i - 20, i);
      const sma10  = window.slice(-10).reduce((a,b)=>a+b,0)/10;
      const sma20  = window.reduce((a,b)=>a+b,0)/20;
      const rsi    = calcRSI(window);
      let signal = null;

      if (strat === 'buy_hold' && i === 20) signal = 'buy';
      else if (strat === 'sma_cross') { if (sma10 > sma20 && !inPos) signal='buy'; else if (sma10 < sma20 && inPos) signal='sell'; }
      else if (strat === 'rsi_reversal') { if (rsi < 30 && !inPos) signal='buy'; else if (rsi > 70 && inPos) signal='sell'; }
      else if (strat === 'momentum') { if (prices[i] > prices[i-10]*1.02 && !inPos) signal='buy'; else if (prices[i] < prices[i-5] && inPos) signal='sell'; }
      else if (strat === 'mean_rev') { const avg=window.slice(-5).reduce((a,b)=>a+b,0)/5; if (prices[i]<avg*0.97 && !inPos) signal='buy'; else if (prices[i]>avg*1.03 && inPos) signal='sell'; }

      const execP = prices[i] * (1 + (signal==='buy' ? slip : -slip));
      if (signal === 'buy' && cash > execP) {
        shares = Math.floor(cash / (execP + comm));
        cash -= shares * execP + comm;
        entryPrice = execP;
        inPos = true;
      } else if (signal === 'sell' && inPos && shares > 0) {
        const proceeds = shares * execP - comm;
        const pnl = proceeds - shares * entryPrice;
        trades.push({ day:i, pnl, entry:entryPrice, exit:execP });
        cash += proceeds;
        shares = 0;
        inPos = false;
      }
      equityCurve.push(cash + shares * prices[i]);
    }

    // close if still open
    if (inPos && shares > 0) cash += shares * prices[prices.length-1];

    const finalValue = cash;
    const totalReturn = (finalValue - cap) / cap;
    const wins = trades.filter(t=>t.pnl>0).length;
    const avgPnl = trades.length ? trades.reduce((a,t)=>a+t.pnl,0)/trades.length : 0;
    const maxDD = calcMaxDrawdown(equityCurve);

    renderResults({ sym, strat, days, cap, finalValue, totalReturn, trades, wins, avgPnl, maxDD, equityCurve, prices });
  }

  function calcRSI(prices) {
    if (prices.length < 2) return 50;
    let gains=0, losses=0;
    for (let i=1; i<prices.length; i++) {
      const d = prices[i]-prices[i-1];
      if (d>0) gains+=d; else losses-=d;
    }
    const rs = losses===0 ? 100 : gains/losses;
    return 100 - 100/(1+rs);
  }

  function calcMaxDrawdown(curve) {
    let peak = curve[0], maxDD = 0;
    curve.forEach(v => { if (v>peak) peak=v; const dd=(peak-v)/peak; if (dd>maxDD) maxDD=dd; });
    return maxDD;
  }

  function renderResults(r) {
    const el = $('bt-results');
    const color = r.totalReturn >= 0 ? '#00ff88' : '#ff4757';
    el.style.display = 'block';
    el.innerHTML = `
      <div class="bt-kpis">
        <div class="bt-kpi"><div class="btk-l">TOTAL RETURN</div><div class="btk-v" style="color:${color}">${fmtP(r.totalReturn)}</div></div>
        <div class="bt-kpi"><div class="btk-l">FINAL VALUE</div><div class="btk-v">${fmt(r.finalValue)}</div></div>
        <div class="bt-kpi"><div class="btk-l">TOTAL TRADES</div><div class="btk-v">${r.trades.length}</div></div>
        <div class="bt-kpi"><div class="btk-l">WIN RATE</div><div class="btk-v">${r.trades.length ? Math.round(r.wins/r.trades.length*100) : 0}%</div></div>
        <div class="bt-kpi"><div class="btk-l">AVG TRADE P&L</div><div class="btk-v" style="color:${r.avgPnl>=0?'#00ff88':'#ff4757'}">${fmt(r.avgPnl)}</div></div>
        <div class="bt-kpi"><div class="btk-l">MAX DRAWDOWN</div><div class="btk-v neg">${(r.maxDD*100).toFixed(1)}%</div></div>
        <div class="bt-kpi"><div class="btk-l">PERIOD</div><div class="btk-v">${r.days}d</div></div>
        <div class="bt-kpi"><div class="btk-l">SYMBOL</div><div class="btk-v">${r.sym}</div></div>
      </div>
      <div style="background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-lg);padding:14px;">
        <div class="card-hdr" style="margin-bottom:10px;padding:0"><span>Equity Curve</span></div>
        <canvas id="bt-chart" height="180"></canvas>
      </div>`;
    requestAnimationFrame(() => {
      const ctx = $('bt-chart')?.getContext('2d');
      if (!ctx) return;
      new Chart(ctx, {
        type:'line',
        data:{ labels: r.equityCurve.map((_,i)=>i), datasets:[{ data:r.equityCurve, borderColor:color, backgroundColor:color+'22', fill:true, pointRadius:0, borderWidth:2 }] },
        options:{ plugins:{legend:{display:false}}, scales:{ x:{display:false}, y:{grid:{color:'rgba(255,255,255,0.05)'}, ticks:{color:'#888',callback:v=>'$'+v.toLocaleString()}} } }
      });
    });
  }

  return { run };
})();

/* ─── APP NAVIGATION & UI ─── */
const SimApp = (() => {
  let _perfChart = null, _tradeChart = null;
  let _pwaPrompt = null;

  function init() {
    SimEngine.loadState();
    SimEngine.init();
    SimEngine.updateStreak();
    populateSymbolSelects();
    setupNavigation();
    renderSubscriptionPlans();
    renderScenarioGrid();
    OptionsEngine.init();
    Academy.init();
    SocialSim.init();
    AICoach.init();
    updateDashboard();
    updateXPBar();
    checkPWA();
    initPerfChart();
    initTradeChart();
    setSymbol('SPY');

    window.addEventListener('beforeinstallprompt', e => { e.preventDefault(); _pwaPrompt = e; $('pwa-banner').style.display='flex'; });

    document.querySelectorAll('.nav-item[data-view]').forEach(btn => {
      btn.addEventListener('click', () => showView(btn.dataset.view));
    });
    requestAnimationFrame(() => {
      updateMarketIndices();
      updateMarketTable();
      updateDailyChallenge();
      updateAcademyMini();
      updateRecentTrades();
    });
  }

  function setupNavigation() {
    document.querySelectorAll('.nav-item[data-view]').forEach(btn => {
      btn.addEventListener('click', () => {
        const view = btn.dataset.view;
        const lock = btn.querySelector('.nav-lock');
        if (lock) {
          const needed = lock.dataset.tier;
          if (!tierAllows(needed)) { showUpgradeModal(needed); return; }
        }
        showView(view);
      });
    });
  }

  function tierAllows(needed) {
    const order = { free:0, starter:1, pro:2, elite:3 };
    return (order[_state.subscription] || 0) >= (order[needed] || 0);
  }

  function showView(view) {
    document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
    const el = $('view-' + view);
    if (el) { el.classList.add('active'); el.style.display = 'block'; }
    document.querySelectorAll('.nav-item').forEach(b => b.classList.toggle('active', b.dataset.view === view));
    _state.ui.currentView = view;

    // Hide sub-views when switching
    if ($('lesson-view')) $('lesson-view').style.display = 'none';
    if ($('quiz-view')) $('quiz-view').style.display = 'none';

    if (view === 'dashboard') updateDashboard();
    if (view === 'market')    { updateMarketTable(); updateMarketMovers(); }
    if (view === 'trade')     updateTradeView();
    if (view === 'options-chain') OptionsEngine.loadChain(_state.ui.currentSymbol);
    if (view === 'strategies') renderStrategies('all');
    if (view === 'portfolio') updatePortfolio();
    if (view === 'leaderboard') SocialSim.render();
    if (view === 'settings')  renderSubscriptionPlans();
    if (view === 'backtester') {
      if (!tierAllows('pro')) { $('bt-tier-bar').style.display='flex'; $('backtester-wrap').style.opacity='0.4'; $('backtester-wrap').style.pointerEvents='none'; }
    }
    if (view === 'academy') Academy.render();
    if (view === 'ai-coach') AICoach.updateStatus();

    closeSidebarOnMobile();
  }

  function closeSidebarOnMobile() {
    if (window.innerWidth <= 900) {
      $('sidebar').classList.remove('open');
      $('sidebar-overlay').classList.remove('visible');
    }
  }

  function toggleSidebar() {
    $('sidebar').classList.toggle('open');
    $('sidebar-overlay').classList.toggle('visible');
  }

  function setSymbol(sym) {
    if (!_state.symbols[sym]) return;
    _state.ui.currentSymbol = sym;
    const s = _state.symbols[sym];
    if ($('tb-price')) { $('tb-price').textContent = fmt(s.price); }
    if ($('tb-change')) {
      const chg = $('tb-change');
      chg.textContent = fmtP(s.changePct);
      chg.className = 'tb-change-val ' + (s.changePct >= 0 ? 'pos' : 'neg');
    }
    updateTradeSymbolDisplay(sym);
  }

  function populateSymbolSelects() {
    const syms = Object.keys(_state.symbols).sort();
    ['tb-symbol-select','trade-sym-sel','chain-sym-sel','bt-sym'].forEach(id => {
      const el = $(id);
      if (!el) return;
      el.innerHTML = syms.map(s => `<option value="${s}">${s}</option>`).join('');
    });
  }

  function updateAllUI() {
    if ($('tb-price') && _state.symbols[_state.ui.currentSymbol]) {
      const s = _state.symbols[_state.ui.currentSymbol];
      $('tb-price').textContent = fmt(s.price);
      const chg = $('tb-change');
      if (chg) { chg.textContent = fmtP(s.changePct); chg.className = 'tb-change-val ' + (s.changePct >= 0 ? 'pos' : 'neg'); }
    }
    if (_state.ui.currentView === 'dashboard') updateDashboard();
    if (_state.ui.currentView === 'trade') updateTradeView();
    if (_state.ui.currentView === 'market') updateMarketTable();
  }

  function updateDashboard() {
    const pv  = SimEngine.portfolioValue();
    const sc  = _state.portfolio.startingCash;
    const pnl = pv - _state.portfolio.dayStartValue;
    const ret = (pv - sc) / sc;

    setText('kpi-pv-val',  fmt(pv));
    setText('kpi-bp-val',  fmt(_state.portfolio.cash));
    setText('kpi-pnl-val', fmtS(pnl), pnl >= 0 ? 'pos' : 'neg');
    setText('kpi-pnl-pct', fmtP(pnl / (_state.portfolio.dayStartValue || sc)));
    setText('kpi-ret-val', fmtP(ret), ret >= 0 ? 'pos' : 'neg');

    const total = _state.gamification.wins + _state.gamification.losses;
    const wr = total ? Math.round(_state.gamification.wins / total * 100) : 0;
    setText('kpi-winrate', `Win Rate: ${wr}%`);
    setText('sb-pv', fmt(pv));
    setText('sb-pnl', fmtS(pnl));

    updatePositionsList();
    updateRecentTrades();
    updateWatchlistMini();
    updateMarketOverviewMini();
    updatePerfChart();
  }

  function setText(id, text, cls) {
    const el = $(id);
    if (!el) return;
    el.textContent = text;
    if (cls) el.className = el.className.replace(/ ?(pos|neg)/g,'') + ' ' + cls;
  }

  function updatePositionsList() {
    const el = $('open-positions-list');
    if (!el) return;
    const pos = Object.entries(_state.portfolio.positions);
    $('pos-count').textContent = pos.length;
    if (!pos.length) { el.innerHTML = '<div class="empty-state">No positions.<br><a onclick="SimApp.showView(\'trade\')">Make a trade →</a></div>'; return; }
    el.innerHTML = pos.map(([key, p]) => {
      const sym = p.sym || key.split('_')[0];
      const pnl = p.unrealizedPnL || 0;
      const label = p.type === 'option' ? `${p.optType?.toUpperCase()} $${p.strike} ${p.expiry?.slice(5)}` : `${p.qty} shares`;
      return `<div class="pos-item ${pnl>=0?'pos-up':'pos-down'}">
        <div><div class="pi-sym">${sym}</div><div class="pi-details">${label} @ ${fmt(p.avgCost)}</div></div>
        <div class="pi-pnl ${pnl>=0?'pos':'neg'}">${fmtS(pnl)}</div>
      </div>`;
    }).join('');
  }

  function updateRecentTrades() {
    const el = $('recent-trades-list');
    if (!el) return;
    const h = _state.portfolio.history.slice(0, 8);
    if (!h.length) { el.innerHTML = '<div class="empty-state">No trades yet.</div>'; return; }
    el.innerHTML = h.map(t => `
      <div class="trade-row ${t.pnl>=0?'win':'loss'}">
        <span class="tr-sym">${t.sym}</span>
        <span class="tr-side ${t.side.toLowerCase()}">${t.side}</span>
        <span class="tr-pnl ${t.pnl>=0?'pos':'neg'}">${fmtS(t.pnl)}</span>
      </div>`).join('');
  }

  function updateWatchlistMini() {
    const el = $('watchlist-mini');
    if (!el) return;
    const watchlist = ['SPY','QQQ','AAPL','TSLA','NVDA','AMC','GME','COIN'];
    el.innerHTML = watchlist.map(sym => {
      const s = _state.symbols[sym];
      if (!s) return '';
      return `<div class="wl-item" onclick="SimApp.setSymbol('${sym}');SimApp.showView('trade')">
        <span class="wl-sym">${sym}</span>
        <span class="wl-price">${fmt(s.price)}</span>
        <span class="wl-chg ${s.changePct>=0?'pos':'neg'}">${fmtP(s.changePct)}</span>
      </div>`;
    }).join('');
  }

  function updateMarketOverviewMini() {
    const el = $('market-overview-mini');
    if (!el) return;
    const indices = ['SPY','QQQ','IWM','AAPL'];
    el.innerHTML = indices.map(sym => {
      const s = _state.symbols[sym];
      if (!s) return '';
      return `<div class="mom-item" style="border-left-color:${s.changePct>=0?'#00ff88':'#ff4757'}">
        <div class="mom-sym">${sym}</div>
        <div class="mom-val ${s.changePct>=0?'pos':'neg'}">${fmt(s.price)} ${fmtP(s.changePct)}</div>
      </div>`;
    }).join('');
  }

  function updateMarketIndices() {
    const el = $('market-indices-bar');
    if (!el) return;
    ['SPY','QQQ','IWM','DIA'].forEach(sym => {
      const s = _state.symbols[sym];
      if (!s) return;
      const div = document.createElement('div');
      div.className = 'mib-item';
      div.innerHTML = `<div class="mib-sym">${sym}</div><div class="mib-price">${fmt(s.price)}</div><div class="mib-chg ${s.changePct>=0?'pos':'neg'}">${fmtP(s.changePct)}</div>`;
      el.appendChild(div);
    });
  }

  function updateMarketTable() {
    const el = $('market-tbody');
    if (!el) return;
    const filter = $('market-filter')?.value || 'all';
    let stocks = Object.values(_state.symbols);
    if (filter !== 'all') stocks = stocks.filter(s => s.sector === filter);
    $('market-count').textContent = `${stocks.length} symbols`;
    el.innerHTML = stocks.map(s => `
      <tr onclick="SimApp.setSymbol('${s.sym}');SimApp.showView('trade')">
        <td class="td-sym">${s.sym}</td>
        <td class="td-company">${s.name}</td>
        <td class="td-price" style="color:${s.changePct>=0?'#00ff88':'#ff4757'}">${fmt(s.price)}</td>
        <td class="${s.changePct>=0?'td-chg-pos':'td-chg-neg'}">${fmtP(s.changePct)}</td>
        <td class="td-vol">${(s.vol/1e6).toFixed(1)}M</td>
        <td>${s.cap}</td>
        <td class="td-iv">${(s.iv*100).toFixed(0)}%</td>
        <td><span class="td-sector">${s.sector}</span></td>
        <td><button class="td-act-btn" onclick="event.stopPropagation();SimApp.setSymbol('${s.sym}');SimApp.showView('trade')">Trade</button></td>
      </tr>`).join('');
  }

  function updateMarketMovers() {
    const stocks = Object.values(_state.symbols);
    const gainers = [...stocks].sort((a,b) => b.changePct - a.changePct).slice(0,5);
    const losers  = [...stocks].sort((a,b) => a.changePct - b.changePct).slice(0,5);
    const active  = [...stocks].sort((a,b) => b.vol - a.vol).slice(0,5);
    const highIV  = [...stocks].sort((a,b) => b.iv - a.iv).slice(0,5);
    const renderList = (id, arr) => {
      const el = $(id);
      if (!el) return;
      el.innerHTML = arr.map(s => `
        <div class="mover-item" onclick="SimApp.setSymbol('${s.sym}');SimApp.showView('trade')">
          <span class="mv-sym">${s.sym}</span>
          <span class="mv-price">${fmt(s.price)}</span>
          <span class="mv-chg ${s.changePct>=0?'pos':'neg'}">${fmtP(s.changePct)}</span>
        </div>`).join('');
    };
    renderList('top-gainers', gainers);
    renderList('top-losers', losers);
    renderList('most-active', active);
    renderList('high-iv-list', highIV);
  }

  function filterMarket(val) { updateMarketTable(); }
  function searchMarket(q) {
    const el = $('market-tbody');
    if (!el) return;
    q = q.toLowerCase();
    const stocks = Object.values(_state.symbols).filter(s => s.sym.toLowerCase().includes(q) || s.name.toLowerCase().includes(q));
    el.innerHTML = stocks.map(s => `
      <tr onclick="SimApp.setSymbol('${s.sym}');SimApp.showView('trade')">
        <td class="td-sym">${s.sym}</td>
        <td class="td-company">${s.name}</td>
        <td style="color:${s.changePct>=0?'#00ff88':'#ff4757'}">${fmt(s.price)}</td>
        <td class="${s.changePct>=0?'td-chg-pos':'td-chg-neg'}">${fmtP(s.changePct)}</td>
        <td class="td-vol">${(s.vol/1e6).toFixed(1)}M</td>
        <td>${s.cap}</td>
        <td class="td-iv">${(s.iv*100).toFixed(0)}%</td>
        <td><span class="td-sector">${s.sector}</span></td>
        <td><button class="td-act-btn">Trade</button></td>
      </tr>`).join('');
  }
  function sortMarket(col) { updateMarketTable(); }

  function setTradeMode(mode, btn) {
    _state.ui.tradeMode = mode;
    document.querySelectorAll('.mode-tab').forEach(b => b.classList.remove('active'));
    if (btn) btn.classList.add('active');
    $('trade-stock-panel').style.display   = mode === 'stock' ? 'block' : 'none';
    $('trade-options-panel').style.display = mode === 'options' ? 'block' : 'none';
    $('trade-scenario-panel').style.display= mode === 'scenario' ? 'block' : 'none';
    if (mode === 'options') OptionsEngine.renderMiniChain();
    if (mode === 'scenario') renderScenarioGrid();
  }

  function setOrderSide(side, btn) {
    _state.ui.orderSide = side;
    document.querySelectorAll('.otab').forEach(b => b.classList.remove('active'));
    if (btn) btn.classList.add('active');
    const execBtn = $('exec-btn');
    if (execBtn) {
      execBtn.className = `exec-btn exec-${side.toLowerCase()}`;
      execBtn.textContent = `${side === 'BUY' ? 'BUY' : 'SELL'} — ${_state.ui.orderType.toUpperCase()} ORDER`;
    }
    updateOrderCost();
  }

  function updateOrderType(type) {
    _state.ui.orderType = type;
    $('limit-field').style.display = type === 'limit' || type === 'stop-limit' ? 'block' : 'none';
    $('stop-field').style.display  = type === 'stop' || type === 'stop-limit' || type === 'bracket' ? 'block' : 'none';
    $('tp-field').style.display    = type === 'bracket' ? 'block' : 'none';
    $('trail-field').style.display = type === 'trailing' ? 'block' : 'none';
    if (type === 'limit' && $('limit-price')) {
      $('limit-price').value = (_state.symbols[_state.ui.currentSymbol]?.price || 0).toFixed(2);
    }
    setOrderSide(_state.ui.orderSide);
  }

  function adjQty(delta) {
    const el = $('order-qty');
    if (!el) return;
    el.value = Math.max(1, parseInt(el.value || '1') + delta);
    updateOrderCost();
  }

  function setSizePct(pct) {
    const s = _state.symbols[_state.ui.currentSymbol];
    if (!s) return;
    const qty = Math.max(1, Math.floor(_state.portfolio.cash * pct / s.price));
    $('order-qty').value = qty;
    updateOrderCost();
  }

  function updateOrderCost() {
    const s = _state.symbols[_state.ui.currentSymbol];
    if (!s) return;
    const qty  = parseInt($('order-qty')?.value || '1');
    const price = _state.ui.orderType === 'limit' ? parseFloat($('limit-price')?.value || s.price) : s.price;
    const cost = price * qty;
    const bp   = _state.portfolio.cash;
    setText('rc-cost', fmt(cost));
    setText('rc-bp-after', fmt(bp - cost));
    setText('rc-target', fmtS(cost * 0.05));
    setText('rc-risk', '-' + fmt(cost * 0.05));
    const rr = (cost * 0.05) / Math.max(cost * 0.05, 0.01);
    setText('rc-rr', rr.toFixed(1) + ':1');
    if ($('qty-hint')) $('qty-hint').textContent = `= ${fmt(cost)}`;
  }

  function updateTradeSymbol(sym) {
    _state.ui.currentSymbol = sym;
    updateTradeSymbolDisplay(sym);
  }

  function updateTradeSymbolDisplay(sym) {
    const s = _state.symbols[sym];
    if (!s) return;
    setText('trade-cur-price', fmt(s.price));
    const chg = $('trade-chg-display');
    if (chg) { chg.textContent = fmtP(s.changePct); chg.className = 'tcd ' + (s.changePct >= 0 ? 'pos' : 'neg'); }
    setText('tsb-open',  fmt(s.open));
    setText('tsb-high',  fmt(s.high));
    setText('tsb-low',   fmt(s.low));
    setText('tsb-vol',   (s.vol/1e6).toFixed(1)+'M');
    setText('tsb-iv',    (s.iv*100).toFixed(0)+'%');
    setText('tsb-52h',   fmt(s.high * 1.25));
    setText('tsb-52l',   fmt(s.low  * 0.75));
    setText('tsb-mktcap', s.cap);

    // Current position
    const pos = _state.portfolio.positions[sym];
    const card = $('current-pos-card');
    if (pos && card) {
      card.style.display = 'block';
      const pnl = pos.unrealizedPnL || 0;
      $('current-pos-content').innerHTML = `
        <div style="font-family:var(--mono);font-size:12px;padding:8px 0">
          <div style="display:flex;justify-content:space-between;margin-bottom:4px">
            <span style="color:var(--text3)">SHARES</span><strong>${pos.qty}</strong>
          </div>
          <div style="display:flex;justify-content:space-between;margin-bottom:4px">
            <span style="color:var(--text3)">AVG COST</span><strong>${fmt(pos.avgCost)}</strong>
          </div>
          <div style="display:flex;justify-content:space-between">
            <span style="color:var(--text3)">UNREALIZED P&L</span>
            <strong class="${pnl>=0?'pos':'neg'}">${fmtS(pnl)}</strong>
          </div>
        </div>`;
    } else if (card) {
      card.style.display = 'none';
    }

    updateOrderCost();
    updateTradeChart(sym);
  }

  function updateTradeView() {
    updateTradeSymbolDisplay(_state.ui.currentSymbol);
    const sel = $('trade-sym-sel');
    if (sel) sel.value = _state.ui.currentSymbol;
  }

  function initPerfChart() {
    const ctx = $('perf-chart')?.getContext('2d');
    if (!ctx) return;
    _perfChart = new Chart(ctx, {
      type:'line',
      data:{ labels:[], datasets:[{
        data:[], borderColor:'#00d4ff', backgroundColor:'rgba(0,212,255,0.05)',
        fill:true, pointRadius:0, borderWidth:2, tension:0.3
      }]},
      options:{
        responsive:true, maintainAspectRatio:false,
        plugins:{ legend:{display:false} },
        scales:{
          x:{display:false},
          y:{grid:{color:'rgba(255,255,255,0.04)'}, ticks:{color:'#888', callback:v=>'$'+v.toLocaleString('en-US',{maximumFractionDigits:0})}}
        }
      }
    });
  }

  function updatePerfChart() {
    if (!_perfChart) return;
    const curve = _state.portfolio.equityCurve.slice(-200);
    _perfChart.data.labels = curve.map((_,i)=>i);
    _perfChart.data.datasets[0].data = curve.map(p=>p.value);
    const last = curve[curve.length-1]?.value || _state.portfolio.startingCash;
    const first = curve[0]?.value || _state.portfolio.startingCash;
    _perfChart.data.datasets[0].borderColor = last >= first ? '#00ff88' : '#ff4757';
    _perfChart.data.datasets[0].backgroundColor = last >= first ? 'rgba(0,255,136,0.05)' : 'rgba(255,71,87,0.05)';
    _perfChart.update('none');
  }

  function initTradeChart() {
    const ctx = $('trade-chart')?.getContext('2d');
    if (!ctx) return;
    _tradeChart = new Chart(ctx, {
      type:'line',
      data:{ labels:[], datasets:[{
        data:[], borderColor:'#00d4ff', backgroundColor:'rgba(0,212,255,0.05)',
        fill:true, pointRadius:0, borderWidth:2, tension:0.1
      }]},
      options:{
        responsive:true, maintainAspectRatio:false,
        plugins:{ legend:{display:false} },
        scales:{
          x:{display:false},
          y:{grid:{color:'rgba(255,255,255,0.04)'}, ticks:{color:'#888', callback:v=>'$'+v.toFixed(2)}, position:'right'}
        }
      }
    });
  }

  function updateTradeChart(sym) {
    if (!_tradeChart) return;
    const data = (_state.ui.chartData[sym] || []).slice(-100);
    _tradeChart.data.labels = data.map((_,i)=>i);
    _tradeChart.data.datasets[0].data = data.map(b=>b.c);
    const last  = data[data.length-1]?.c || 0;
    const first = data[0]?.c || 0;
    _tradeChart.data.datasets[0].borderColor = last >= first ? '#00ff88' : '#ff4757';
    _tradeChart.update('none');
  }

  function setChartTF(tf, btn) {
    _state.ui.chartTF = tf;
    document.querySelectorAll('.cttab').forEach(b => b.classList.remove('active'));
    if (btn) btn.classList.add('active');
    updateTradeChart(_state.ui.currentSymbol);
  }

  function setPerfPeriod(p, btn) {
    _state.ui.perfPeriod = p;
    document.querySelectorAll('.ptab').forEach(b => b.classList.remove('active'));
    if (btn) btn.classList.add('active');
    updatePerfChart();
  }

  function updatePortfolio() {
    const h = _state.portfolio.history;
    const wins = h.filter(t=>t.pnl>0);
    const losses = h.filter(t=>t.pnl<0);
    const wr = h.length ? Math.round(wins.length/h.length*100) : 0;
    const avgWin  = wins.length  ? wins.reduce((a,t)=>a+t.pnl,0)/wins.length : 0;
    const avgLoss = losses.length ? losses.reduce((a,t)=>a+t.pnl,0)/losses.length : 0;
    const pf = Math.abs(avgLoss) > 0 ? Math.abs(avgWin * wins.length) / Math.abs(avgLoss * losses.length) : 0;
    const best = h.length ? Math.max(...h.map(t=>t.pnl)) : 0;
    const curve = _state.portfolio.equityCurve;
    let peak = curve[0]?.value || _state.portfolio.startingCash;
    let mdd = 0;
    curve.forEach(p => { if(p.value>peak)peak=p.value; const dd=(peak-p.value)/peak; if(dd>mdd)mdd=dd; });

    setText('pf-trades', h.length);
    setText('pf-wr', wr+'%');
    setText('pf-avgwin', fmt(avgWin));
    setText('pf-avgloss', fmt(avgLoss));
    setText('pf-pf', pf.toFixed(2));
    setText('pf-mdd', (mdd*100).toFixed(1)+'%');
    setText('pf-sharpe', (Math.random()*1.5+0.5).toFixed(2));
    setText('pf-best', fmt(best));

    updateTradeHistoryTable();
  }

  function updateTradeHistoryTable() {
    const el = $('trade-hist-tbody');
    if (!el) return;
    el.innerHTML = _state.portfolio.history.map(t => `
      <tr>
        <td style="font-weight:700;color:#fff">${t.sym}</td>
        <td>${t.type}</td>
        <td style="color:${t.side==='BUY'?'#00ff88':'#ff4757'}">${t.side}</td>
        <td>${t.qty}</td>
        <td>${fmt(t.entry)}</td>
        <td>${fmt(t.exit)}</td>
        <td class="${t.pnl>=0?'pos':'neg'}">${fmtS(t.pnl)}</td>
        <td class="${t.returnPct>=0?'pos':'neg'}">${fmtP(t.returnPct)}</td>
        <td style="color:var(--text2)">${t.held||'<1d'}</td>
        <td style="color:var(--text3)">${new Date(t.ts).toLocaleDateString()}</td>
      </tr>`).join('');
  }

  function filterTradeHistory(val) { updateTradeHistoryTable(); }

  function updateXPBar() {
    const g = _state.gamification;
    const thresholds = [0,100,300,600,1000,1600,2400,3500,5000,7000,10000,999999];
    const level = g.level;
    const xpForLevel = thresholds[level-1] || 0;
    const xpForNext  = thresholds[level] || thresholds[thresholds.length-1];
    const pct = Math.min(100, ((g.xp - xpForLevel) / (xpForNext - xpForLevel)) * 100);
    const name = SimEngine.LEVELS[level] || 'GOD';
    setText('sb-level', `${name} Lv.${level}`);
    setText('sb-xp', `${g.xp} XP`);
    const fill = $('sb-xp-fill');
    if (fill) fill.style.width = pct + '%';
    setText('sb-streak', g.streak);
    setText('tb-streak', g.streak);
  }

  function updateDailyChallenge() {
    const challenges = [
      { title:'Make 3 Trades', desc:'Execute 3 buy or sell orders today.', xp:50, key:'trades', target:3 },
      { title:'Buy an Option', desc:'Purchase at least 1 options contract.', xp:75, key:'options', target:1 },
      { title:'Hit +5% Return', desc:'Achieve a 5% daily return.', xp:100, key:'daily_return', target:0.05 },
      { title:'Complete a Lesson', desc:'Finish any lesson in the Academy.', xp:60, key:'lesson', target:1 },
      { title:'Trade 5 Symbols', desc:'Trade at least 5 different symbols.', xp:80, key:'symbols', target:5 },
    ];
    const today = new Date().getDay();
    const ch = challenges[today % challenges.length];
    const el = $('daily-challenge-content');
    const xpEl = $('challenge-xp-badge');
    if (el) el.innerHTML = `<div class="dc-title">${ch.title}</div><div class="dc-desc">${ch.desc}</div><div class="dc-progress"><div class="dc-prog-fill" style="width:${Math.random()*60}%"></div></div><div class="dc-status">In Progress...</div>`;
    if (xpEl) xpEl.textContent = `+${ch.xp} XP`;
  }

  function updateAcademyMini() {
    const el = $('academy-dash-mini');
    if (!el) return;
    const total = 24, done = _state.gamification.beginnerLessonsComplete || 0;
    const pct = Math.round(done/total*100);
    el.innerHTML = `
      <div class="am-level"><span class="am-level-name">🌱 BEGINNER</span><span>${done}/${8} lessons</span></div>
      <div class="am-progress"><div class="am-prog-fill" style="width:${done/8*100}%"></div></div>
      <div class="am-level" style="margin-top:8px"><span class="am-level-name">📈 INTERMEDIATE</span><span>${Math.max(0,done-8)}/${8} lessons</span></div>
      <div class="am-progress"><div class="am-prog-fill" style="width:${Math.max(0,(done-8)/8*100)}%"></div></div>`;
  }

  function renderSubscriptionPlans() {
    const el = $('subscription-plans');
    const el2 = $('upgrade-plans');
    if (!el && !el2) return;
    const html = SUBSCRIPTION_PLANS.map(p => `
      <div class="plan-card ${p.popular?'popular':''} ${p.id===_state.subscription?'current':''}">
        ${p.popular ? '<div class="plan-popular-badge">POPULAR</div>' : ''}
        <div class="plan-name" style="color:${p.color}">${p.name}</div>
        <div class="plan-price" style="color:${p.color}">$${p.price}<span>${p.period}</span></div>
        <div class="plan-features">
          ${p.features.map(f=>`<div class="plan-feature">${f}</div>`).join('')}
          ${p.locked.map(f=>`<div class="plan-feature locked-feat">${f}</div>`).join('')}
        </div>
        <button class="plan-btn ${p.id===_state.subscription?'active-plan':'upgrade-btn'}" onclick="SimApp.selectPlan('${p.id}')">
          ${p.id===_state.subscription ? '✓ Current Plan' : p.price===0 ? 'Free Forever' : 'Select Plan'}
        </button>
      </div>`).join('');
    if (el) el.innerHTML = html;
    if (el2) el2.innerHTML = html;
  }

  function selectPlan(id) {
    _state.subscription = id;
    const plan = SUBSCRIPTION_PLANS.find(p=>p.id===id);
    setText('sidebar-tier', (plan?.name||'FREE') + ' TIER');
    SimEngine.saveState();
    renderSubscriptionPlans();
    closeModal('upgrade-modal');
    SimApp.toast(`✅ Plan updated: ${plan?.name}`, 'success');
    $('tb-upgrade-btn').style.display = id === 'free' ? 'block' : 'none';
  }

  function showUpgradeModal(tier) {
    const modal = $('upgrade-modal');
    if (!modal) return;
    const titles = { starter:'Upgrade to Starter', pro:'Upgrade to PRO', elite:'Go Elite', general:'Upgrade Your Plan' };
    setText('upgrade-hero-title', titles[tier] || 'Upgrade Your Plan');
    renderSubscriptionPlans();
    modal.style.display = 'flex';
  }

  function renderScenarioGrid() {
    const el = $('scenario-grid');
    if (!el) return;
    el.innerHTML = SCENARIOS.map(sc => `
      <div class="scenario-card ${sc.diff}" onclick="SimEngine.startScenario('${sc.id}');SimApp.setTradeMode('stock',document.querySelector('.mode-tab'))">
        <div class="sc-icon">${sc.icon}</div>
        <div class="sc-title">${sc.name}</div>
        <div class="sc-desc">${sc.desc}</div>
        <div class="sc-meta">
          <span class="sc-tag diff-${sc.diff}">${sc.diff}</span>
          <span class="sc-tag">${sc.time}s</span>
          <span class="sc-xp">+${sc.xp} XP</span>
        </div>
      </div>`).join('');
  }

  function renderStrategies(filter) {
    const el = $('strategies-grid');
    if (!el) return;
    let strats = OptionsEngine.STRATEGIES;
    if (filter && filter !== 'all') strats = strats.filter(s => s.tags.includes(filter));
    el.innerHTML = strats.map(s => `
      <div class="strat-card" onclick="SimApp.showStratModal('${s.id}')">
        <div class="strat-card-icon">${s.icon}</div>
        <div class="strat-card-name">${s.name}</div>
        <div class="strat-card-desc">${s.desc}</div>
        <div class="strat-card-footer">
          <div style="display:flex;gap:4px;flex-wrap:wrap">${s.tags.map(t=>`<span class="strat-tag ${t}">${t}</span>`).join('')}</div>
          <button class="strat-learn-btn">View →</button>
        </div>
      </div>`).join('');
  }

  function filterStrats(filter, btn) {
    document.querySelectorAll('.sftab').forEach(b => b.classList.remove('active'));
    if (btn) btn.classList.add('active');
    renderStrategies(filter);
  }

  function showStratModal(id) {
    const s = OptionsEngine.STRATEGIES.find(s=>s.id===id);
    if (!s) return;
    setText('strat-modal-title', s.name);
    $('strat-modal-body').innerHTML = s.detail || `<p>${s.desc}</p>`;
    $('strat-modal').style.display = 'flex';
  }

  function showAchievement(ach) {
    const el = $('ach-toast');
    if (!el) return;
    el.innerHTML = `<div class="ach-toast-title">🏅 ACHIEVEMENT UNLOCKED</div><div class="ach-toast-name">${ach.icon} ${ach.name}</div><div class="ach-toast-xp">+${ach.xp} XP</div>`;
    el.style.display = 'block';
    setTimeout(() => { el.style.display = 'none'; }, 4000);
  }

  function toast(msg, type = 'info') {
    const container = $('toast-container');
    if (!container) return;
    const el = document.createElement('div');
    el.className = `toast ${type}`;
    const icons = { success:'✅', error:'❌', info:'ℹ️', warning:'⚠️' };
    el.innerHTML = `<span>${icons[type]||'ℹ️'}</span><span>${msg}</span>`;
    container.appendChild(el);
    setTimeout(() => el.remove(), 3500);
  }

  function closeModal(id) { const el = $(id); if (el) el.style.display = 'none'; }

  function checkPWA() {
    const isInstalled = window.matchMedia('(display-mode: standalone)').matches;
    setText('about-pwa', isInstalled ? '✓ Installed' : 'Not Installed');
    setText('about-platform', navigator.userAgent.includes('Android') ? 'Android' : navigator.userAgent.includes('iPhone') ? 'iOS' : 'Web');
  }

  function installPWA() { if (_pwaPrompt) { _pwaPrompt.prompt(); } }

  function setRiskWarn(v) { _state.ui.settings.riskWarn = v; SimEngine.saveState(); }
  function setSound(v)     { _state.ui.settings.sound = v; SimEngine.saveState(); }
  function requestPushPermission(on) { if (on && Notification) Notification.requestPermission(); }

  function generateKDPWorkbook() {
    const g = _state.gamification;
    const pv = SimEngine.portfolioValue();
    const h = _state.portfolio.history;
    const wins = h.filter(t=>t.pnl>0).length;
    const wr = h.length ? Math.round(wins/h.length*100) : 0;
    const el = $('kdp-workbook-content');
    if (el) el.innerHTML = `
      <h1>My Trading Journal & Workbook</h1>
      <p style="text-align:center;color:var(--text3);margin-bottom:20px">Generated by SqueezeSim Pro • ${new Date().toLocaleDateString()}</p>
      <h2>My Trading Stats</h2>
      <table><tr><th>Metric</th><th>Value</th></tr>
        <tr><td>Total Trades</td><td>${h.length}</td></tr>
        <tr><td>Win Rate</td><td>${wr}%</td></tr>
        <tr><td>Portfolio Value</td><td>${fmt(pv)}</td></tr>
        <tr><td>Total XP</td><td>${g.xp}</td></tr>
        <tr><td>Level</td><td>${SimEngine.LEVELS[g.level]}</td></tr>
        <tr><td>Best Win Streak</td><td>${g.maxWinStreak}</td></tr>
      </table>
      <h2>My Achievements</h2>
      <ul>${(g.unlockedAchievements||[]).map(id=>{const a=ACHIEVEMENTS.find(a=>a.id===id);return a?`<li><strong>${a.icon} ${a.name}</strong> — ${a.desc}</li>`:'';}).join('')||'<li>None yet — keep trading!</li>'}</ul>
      <h2>Recent Trades</h2>
      <table><tr><th>Symbol</th><th>Side</th><th>Qty</th><th>Entry</th><th>Exit</th><th>P&L</th></tr>
        ${h.slice(0,20).map(t=>`<tr><td>${t.sym}</td><td>${t.side}</td><td>${t.qty}</td><td>${fmt(t.entry)}</td><td>${fmt(t.exit)}</td><td>${fmtS(t.pnl)}</td></tr>`).join('')||'<tr><td colspan="6">No trades yet</td></tr>'}
      </table>
      <h2>Trading Notes (Print & Write)</h2>
      ${Array(10).fill(0).map((_,i)=>`<div style="margin-bottom:12px"><strong>Trade ${i+1}:</strong><div style="height:40px;border-bottom:1px solid #444;margin-top:4px"></div></div>`).join('')}
    `;
    $('kdp-modal').style.display = 'flex';
  }

  // Expose for inline handlers
  window._state = _state;

  return {
    init, showView, toggleSidebar, setSymbol, updateDashboard, updateTradeView,
    updateXPBar, updatePortfolio, updateMarketTable, updateMarketMovers, updateMarketIndices,
    searchMarket, sortMarket, filterMarket, filterTradeHistory,
    setTradeMode, setOrderSide, updateOrderType, adjQty, setSizePct, updateOrderCost,
    updateTradeSymbol, setChartTF, setPerfPeriod,
    renderStrategies, filterStrats, showStratModal,
    renderScenarioGrid, renderSubscriptionPlans, selectPlan,
    showUpgradeModal, closeModal, showAchievement, toast,
    checkPWA, installPWA, setRiskWarn, setSound, requestPushPermission,
    generateKDPWorkbook, updateAllUI, updateTradeSymbolDisplay,
  };
})();

// Boot
document.addEventListener('DOMContentLoaded', () => SimApp.init());
