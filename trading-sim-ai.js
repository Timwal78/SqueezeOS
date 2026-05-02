/* trading-sim-ai.js — BYOK AI Coach */
'use strict';

const AICoach = (() => {
  const PROVIDERS = {
    openrouter: {
      name:'OpenRouter', icon:'🌐',
      models:['meta-llama/llama-3.3-70b-instruct','anthropic/claude-haiku-4-5','openai/gpt-4o-mini','google/gemini-2.0-flash-001','mistralai/mixtral-8x7b-instruct'],
      defaultModel:'meta-llama/llama-3.3-70b-instruct',
      endpoint:'https://openrouter.ai/api/v1/chat/completions',
      headerKey:'Authorization', headerVal:k=>`Bearer ${k}`,
      extraHeaders:{'HTTP-Referer':'https://squeezeos.app','X-Title':'SqueezeSim AI Coach'},
      bodyFn:(model,msgs)=>JSON.stringify({model,messages:msgs,max_tokens:1024,temperature:0.7}),
      parseFn:r=>r.choices?.[0]?.message?.content||'No response'
    },
    openai: {
      name:'OpenAI', icon:'🤖',
      models:['gpt-4o','gpt-4o-mini','gpt-4-turbo','gpt-3.5-turbo'],
      defaultModel:'gpt-4o-mini',
      endpoint:'https://api.openai.com/v1/chat/completions',
      headerKey:'Authorization', headerVal:k=>`Bearer ${k}`,
      bodyFn:(model,msgs)=>JSON.stringify({model,messages:msgs,max_tokens:1024,temperature:0.7}),
      parseFn:r=>r.choices?.[0]?.message?.content||'No response'
    },
    anthropic: {
      name:'Anthropic (Claude)', icon:'⚡',
      models:['claude-haiku-4-5-20251001','claude-sonnet-4-6','claude-opus-4-7'],
      defaultModel:'claude-haiku-4-5-20251001',
      endpoint:'https://api.anthropic.com/v1/messages',
      headerKey:'x-api-key', headerVal:k=>k,
      extraHeaders:{'anthropic-version':'2023-06-01','anthropic-dangerous-direct-browser-access':'true'},
      bodyFn:(model,msgs)=>{
        const sys=msgs.find(m=>m.role==='system');
        return JSON.stringify({model,max_tokens:1024,system:sys?.content,messages:msgs.filter(m=>m.role!=='system')});
      },
      parseFn:r=>r.content?.[0]?.text||'No response'
    },
    groq: {
      name:'Groq (Fast)', icon:'🚀',
      models:['llama-3.3-70b-versatile','llama-3.1-8b-instant','mixtral-8x7b-32768'],
      defaultModel:'llama-3.1-8b-instant',
      endpoint:'https://api.groq.com/openai/v1/chat/completions',
      headerKey:'Authorization', headerVal:k=>`Bearer ${k}`,
      bodyFn:(model,msgs)=>JSON.stringify({model,messages:msgs,max_tokens:1024,temperature:0.7}),
      parseFn:r=>r.choices?.[0]?.message?.content||'No response'
    },
    gemini: {
      name:'Google Gemini', icon:'✨',
      models:['gemini-2.0-flash','gemini-1.5-flash','gemini-1.5-pro'],
      defaultModel:'gemini-2.0-flash',
      endpoint:(model,key)=>`https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent?key=${key}`,
      headerKey:'Content-Type', headerVal:()=>'application/json',
      bodyFn:(model,msgs)=>{
        const sys=msgs.find(m=>m.role==='system');
        return JSON.stringify({
          system_instruction:sys?{parts:[{text:sys.content}]}:undefined,
          contents:msgs.filter(m=>m.role!=='system').map(m=>({role:m.role==='assistant'?'model':'user',parts:[{text:m.content}]}))
        });
      },
      parseFn:r=>r.candidates?.[0]?.content?.parts?.[0]?.text||'No response',
      useKeyInUrl:true
    }
  };

  const QUICK_PROMPTS = [
    { id:'analyze', label:'📊 Analyze Portfolio', fn:()=>`Analyze my current trading portfolio:\n${_portfolioCtx()}` },
    { id:'strategy',label:'🎯 Suggest Strategy',  fn:()=>`Suggest the best strategy for me:\n${_portfolioCtx()}\n${_marketCtx()}` },
    { id:'risk',    label:'🛡️ Risk Assessment',   fn:()=>`Assess my risk exposure:\n${_portfolioCtx()}` },
    { id:'options', label:'🔮 Options Advice',     fn:()=>`What options strategies suit my level?\n${_portfolioCtx()}` },
    { id:'explain', label:'📚 Explain Greeks',     fn:()=>'Explain options Greeks (Delta, Gamma, Theta, Vega, Rho) simply with practical examples.' },
    { id:'lesson',  label:'🎓 Daily Lesson',       fn:()=>`Give me a daily lesson for a ${SimEngine.levelName(SimEngine.getState().gamification.level||1)} trader with one actionable tip.` },
    { id:'journal', label:'📝 Trade Journal',      fn:()=>`Review my recent trades and find patterns:\n${_tradesCtx()}` },
    { id:'setup',   label:'🔭 Scan Setups',        fn:()=>`Identify top 3 trading setups to watch:\n${_marketCtx()}` }
  ];

  const DEFAULT_KEYS   = { openrouter:'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' };
  const DEFAULT_MODELS = { openrouter:'meta-llama/llama-3.3-70b-instruct' };

  let _provider = 'openrouter';
  let _keys     = { ...DEFAULT_KEYS };
  let _models   = { ...DEFAULT_MODELS };
  let _history  = [];
  let _busy     = false;

  /* ── Context ── */
  function _portfolioCtx() {
    const st  = SimEngine.getState();
    const pv  = SimEngine.portfolioValue();
    const pnl = pv - st.portfolio.startingCash;
    const pos = Object.entries(st.portfolio.positions||{}).map(([k,p]) => {
      return `  ${p.sym||k}: ${p.type==='option'?p.optType+' $'+p.strike:p.qty+' shares'} @ $${p.avgCost.toFixed(2)}, P&L $${(p.unrealizedPnL||0).toFixed(0)}`;
    }).join('\n') || '  None';
    const g = st.gamification;
    return `Portfolio: $${pv.toLocaleString('en',{maximumFractionDigits:0})} | P&L: ${pnl>=0?'+':''}$${pnl.toFixed(0)} (${(pnl/st.portfolio.startingCash*100).toFixed(1)}%) | Win Rate: ${g.wins+g.losses?Math.round(g.wins/(g.wins+g.losses)*100):0}% | Trades: ${g.totalTrades||0} | Level: ${SimEngine.levelName(g.level||1)}\nOpen Positions:\n${pos}`;
  }
  function _marketCtx() {
    const syms = SimEngine.getState().symbols;
    return 'Market (simulated):\n' + Object.values(syms).slice(0,6).map(s=>`  ${s.sym}: $${s.price.toFixed(2)} (${s.changePct>=0?'+':''}${(s.changePct*100).toFixed(1)}%)`).join('\n');
  }
  function _tradesCtx() {
    const h = SimEngine.getState().portfolio.history.slice(0,10);
    return h.length ? h.map(t=>`  ${t.sym} ${t.side} ${t.qty}@$${t.entry.toFixed(2)} → $${t.exit.toFixed(2)} P&L:$${t.pnl.toFixed(0)}`).join('\n') : 'No trades yet.';
  }
  function _systemPrompt() {
    const g = SimEngine.getState().gamification;
    return `You are an expert trading coach inside SqueezeOS Trading Simulator. User level: ${SimEngine.levelName(g.level||1)}, XP: ${g.xp||0}, Win Rate: ${g.wins+g.losses?Math.round(g.wins/(g.wins+g.losses)*100):0}%. Be concise (3-4 paragraphs max), educational, and always end with one actionable step. This is a simulator — educational only, not real financial advice.`;
  }

  /* ── API call ── */
  async function _callAPI(userMsg) {
    const p = PROVIDERS[_provider];
    if (!p) throw new Error('Unknown provider');
    const key = _keys[_provider];
    if (!key) throw new Error(`No API key for ${p.name}. Add it in Settings → AI Coach.`);
    const model = _models[_provider] || p.defaultModel;
    const messages = [
      {role:'system', content:_systemPrompt()},
      ..._history.map(h=>({role:h.role, content:h.content})),
      {role:'user', content:userMsg}
    ];
    const endpoint = typeof p.endpoint==='function' ? p.endpoint(model,key) : p.endpoint;
    const headers  = {'Content-Type':'application/json', [p.headerKey]:p.headerVal(key), ...(p.extraHeaders||{})};
    if (p.useKeyInUrl) delete headers[p.headerKey];
    const resp = await fetch(endpoint, {method:'POST', headers, body:p.bodyFn(model,messages)});
    if (!resp.ok) {
      const txt = await resp.text();
      let msg = `API Error ${resp.status}`;
      try { msg = JSON.parse(txt).error?.message || JSON.parse(txt).message || msg; } catch {}
      throw new Error(msg);
    }
    return p.parseFn(await resp.json());
  }

  /* ── Chat UI ── */
  function _appendMsg(role, content, isErr) {
    const container = document.getElementById('ai-messages');
    if (!container) return;
    const p = PROVIDERS[_provider];
    const div = document.createElement('div');
    div.className = `ai-msg ai-msg-${role}${isErr?' ai-msg-error':''}`;
    div.innerHTML = `
      <div class="ai-avatar">${role==='user'?'👤':p?.icon||'🤖'}</div>
      <div class="ai-bubble">
        <div class="ai-bubble-content">${_fmt(content)}</div>
        <div class="ai-bubble-meta">${new Date().toLocaleTimeString()}</div>
      </div>`;
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
  }

  function _fmt(t) {
    return ('<p>' + t
      .replace(/\*\*(.+?)\*\*/g,'<strong>$1</strong>')
      .replace(/\*(.+?)\*/g,'<em>$1</em>')
      .replace(/`(.+?)`/g,'<code>$1</code>')
      .replace(/\n\n/g,'</p><p>')
      .replace(/\n/g,'<br>') + '</p>');
  }

  function _showTyping() {
    const c = document.getElementById('ai-messages');
    if (!c) return;
    const d = document.createElement('div');
    d.id = 'ai-typing'; d.className = 'ai-msg ai-msg-assistant';
    d.innerHTML = `<div class="ai-avatar">${PROVIDERS[_provider]?.icon||'🤖'}</div><div class="ai-bubble"><div class="ai-typing-dots"><span></span><span></span><span></span></div></div>`;
    c.appendChild(d); c.scrollTop = c.scrollHeight;
  }
  function _hideTyping() { document.getElementById('ai-typing')?.remove(); }

  async function sendMessage(override) {
    if (_busy) return;
    const input = document.getElementById('ai-input');
    const msg   = override || (input?input.value.trim():'');
    if (!msg) return;
    if (input) input.value = '';
    if (!_keys[_provider]) {
      _appendMsg('assistant', `⚠️ No API key for **${PROVIDERS[_provider]?.name}**.\n\nGo to **Settings → AI Coach** and paste your key. It's stored only in your browser.`, true);
      return;
    }
    _appendMsg('user', msg);
    _history.push({role:'user', content:msg});
    _busy = true; _showTyping();
    const btn = document.getElementById('ai-send-btn');
    if (btn) btn.disabled = true;
    try {
      const reply = await _callAPI(msg);
      _hideTyping(); _appendMsg('assistant', reply);
      _history.push({role:'assistant', content:reply});
      if (_history.length > 20) _history = _history.slice(-20);
    } catch(err) {
      _hideTyping(); _appendMsg('assistant', `❌ ${err.message}`, true);
    } finally {
      _busy = false;
      if (btn) btn.disabled = false;
    }
  }

  function sendQuickPrompt(id) {
    const qp = QUICK_PROMPTS.find(q=>q.id===id);
    if (qp) sendMessage(qp.fn());
  }

  function clearChat() {
    _history = [];
    const c = document.getElementById('ai-messages');
    if (c) {
      const p = PROVIDERS[_provider];
      c.innerHTML = `<div class="ai-welcome"><div style="font-size:48px">${p?.icon||'🤖'}</div><h3>AI Trading Coach</h3><p>Powered by ${p?.name||'AI'}. Ask me anything!</p></div>`;
    }
  }

  /* ── Panel show/hide ── */
  function updateStatus() {
    const hasKey    = !!_keys[_provider];
    const noKeyEl   = document.getElementById('ai-no-key-panel');
    const chatEl    = document.getElementById('ai-chat-panel');
    if (noKeyEl) noKeyEl.style.display = hasKey ? 'none' : 'flex';
    if (chatEl)  chatEl.style.display  = hasKey ? 'flex' : 'none';
    const badge = document.getElementById('ai-provider-badge');
    if (badge) {
      const p = PROVIDERS[_provider];
      badge.textContent = hasKey ? `${p?.icon||''} ${p?.name||_provider} ✓` : 'No Key — Add in Settings';
      badge.style.color = hasKey ? 'var(--neon-green,#00ff88)' : 'var(--neon-red,#ff4757)';
    }
    _syncBYOKUI();
  }

  /* ── BYOK static UI sync ── */
  function _syncBYOKUI() {
    const keyInput   = document.getElementById('byok-key-input');
    const modelSel   = document.getElementById('byok-model-sel');
    const statusEl   = document.getElementById('byok-status');
    const p          = PROVIDERS[_provider];
    if (!p) return;

    if (keyInput) {
      const existing = _keys[_provider];
      keyInput.value = existing ? '••••••••' + existing.slice(-4) : '';
      keyInput.placeholder = `Enter ${p.name} API key...`;
    }
    if (modelSel) {
      modelSel.innerHTML = p.models.map(m=>`<option value="${m}" ${(_models[_provider]||p.defaultModel)===m?'selected':''}>${m}</option>`).join('');
    }
    if (statusEl) {
      statusEl.textContent = _keys[_provider] ? `✅ ${p.name} connected` : `○ No key for ${p.name}`;
      statusEl.style.color = _keys[_provider] ? 'var(--neon-green,#00ff88)' : 'var(--text3,#666)';
    }

    // highlight active tab
    document.querySelectorAll('.byok-tab').forEach(btn => {
      btn.classList.toggle('active', btn.getAttribute('onclick')?.includes(`'${_provider}'`));
    });
  }

  function switchProvider(id, btn) {
    if (!PROVIDERS[id]) return;
    _provider = id;
    _persist();
    updateStatus();
    clearChat();
  }

  function toggleKeyViz() {
    const el = document.getElementById('byok-key-input');
    if (!el) return;
    if (el.type === 'password') { el.type = 'text'; if (el.value.startsWith('••')) el.value = _keys[_provider]||''; }
    else { el.type = 'password'; }
  }

  function saveCurrentKey() {
    const input = document.getElementById('byok-key-input');
    if (!input) return;
    const val = input.value.trim();
    if (!val || val.startsWith('••')) { SimApp.toast('Enter a valid key first', 'error'); return; }
    _keys[_provider] = val;
    _persist();
    updateStatus();
    SimApp.toast(`${PROVIDERS[_provider]?.name} key saved ✓`, 'success');
  }

  function clearCurrentKey() {
    delete _keys[_provider];
    _persist();
    const inp = document.getElementById('byok-key-input');
    if (inp) inp.value = '';
    updateStatus();
    SimApp.toast(`${PROVIDERS[_provider]?.name} key removed`, 'info');
  }

  async function testCurrentKey() {
    const statusEl = document.getElementById('byok-status');
    if (statusEl) { statusEl.textContent = 'Testing...'; statusEl.style.color='var(--text2)'; }
    try {
      const reply = await _callAPI('Say "OK" in exactly one word.');
      if (statusEl) { statusEl.textContent = `✅ Connected! Response: "${reply.slice(0,40)}"`; statusEl.style.color='var(--neon-green,#00ff88)'; }
    } catch(err) {
      if (statusEl) { statusEl.textContent = `❌ ${err.message.slice(0,80)}`; statusEl.style.color='var(--neon-red,#ff4757)'; }
    }
  }

  function _persist() {
    localStorage.setItem('sq_ai_keys',    JSON.stringify(_keys));
    localStorage.setItem('sq_ai_models',  JSON.stringify(_models));
    localStorage.setItem('sq_ai_provider',_provider);
  }

  function _loadKeys() {
    try { const k = JSON.parse(localStorage.getItem('sq_ai_keys')||'{}');    _keys    = {...DEFAULT_KEYS, ...k};    } catch { _keys    = {...DEFAULT_KEYS};    }
    try { const m = JSON.parse(localStorage.getItem('sq_ai_models')||'{}');  _models  = {...DEFAULT_MODELS, ...m};  } catch { _models  = {...DEFAULT_MODELS};  }
    _provider = localStorage.getItem('sq_ai_provider') || 'openrouter';
  }

  /* ── Init ── */
  function init() {
    _loadKeys();
    updateStatus();
    const input = document.getElementById('ai-input');
    if (input) input.addEventListener('keydown', e => {
      if (e.key==='Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
    });
  }

  return {
    init, updateStatus, clearChat,
    sendMessage, sendQuickPrompt,
    switchProvider, toggleKeyViz,
    saveCurrentKey, clearCurrentKey, testCurrentKey,
    PROVIDERS, QUICK_PROMPTS
  };
})();
