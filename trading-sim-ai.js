/* trading-sim-ai.js — BYOK AI Coach (OpenAI, Anthropic, Groq, Gemini) */
'use strict';

const AICoach = (() => {
  const PROVIDERS = {
    openai: {
      name: 'OpenAI',
      icon: '🤖',
      models: ['gpt-4o', 'gpt-4o-mini', 'gpt-4-turbo', 'gpt-3.5-turbo'],
      defaultModel: 'gpt-4o-mini',
      endpoint: 'https://api.openai.com/v1/chat/completions',
      headerKey: 'Authorization',
      headerVal: k => `Bearer ${k}`,
      bodyFn: (model, messages) => JSON.stringify({ model, messages, max_tokens: 1024, temperature: 0.7 }),
      parseFn: r => r.choices?.[0]?.message?.content || 'No response'
    },
    anthropic: {
      name: 'Anthropic (Claude)',
      icon: '⚡',
      models: ['claude-haiku-4-5-20251001', 'claude-sonnet-4-6', 'claude-opus-4-7'],
      defaultModel: 'claude-haiku-4-5-20251001',
      endpoint: 'https://api.anthropic.com/v1/messages',
      headerKey: 'x-api-key',
      headerVal: k => k,
      extraHeaders: { 'anthropic-version': '2023-06-01', 'anthropic-dangerous-direct-browser-access': 'true' },
      bodyFn: (model, messages) => {
        const sys = messages.find(m => m.role === 'system');
        const msgs = messages.filter(m => m.role !== 'system');
        return JSON.stringify({
          model,
          max_tokens: 1024,
          system: sys ? sys.content : undefined,
          messages: msgs
        });
      },
      parseFn: r => r.content?.[0]?.text || 'No response'
    },
    groq: {
      name: 'Groq (Fast)',
      icon: '⚡🚀',
      models: ['llama-3.3-70b-versatile', 'llama-3.1-8b-instant', 'mixtral-8x7b-32768'],
      defaultModel: 'llama-3.1-8b-instant',
      endpoint: 'https://api.groq.com/openai/v1/chat/completions',
      headerKey: 'Authorization',
      headerVal: k => `Bearer ${k}`,
      bodyFn: (model, messages) => JSON.stringify({ model, messages, max_tokens: 1024, temperature: 0.7 }),
      parseFn: r => r.choices?.[0]?.message?.content || 'No response'
    },
    gemini: {
      name: 'Google Gemini',
      icon: '✨',
      models: ['gemini-2.0-flash', 'gemini-1.5-flash', 'gemini-1.5-pro'],
      defaultModel: 'gemini-2.0-flash',
      endpoint: (model, key) => `https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent?key=${key}`,
      headerKey: 'Content-Type',
      headerVal: () => 'application/json',
      bodyFn: (model, messages) => {
        const sys = messages.find(m => m.role === 'system');
        const msgs = messages.filter(m => m.role !== 'system');
        return JSON.stringify({
          system_instruction: sys ? { parts: [{ text: sys.content }] } : undefined,
          contents: msgs.map(m => ({
            role: m.role === 'assistant' ? 'model' : 'user',
            parts: [{ text: m.content }]
          }))
        });
      },
      parseFn: r => r.candidates?.[0]?.content?.parts?.[0]?.text || 'No response',
      useKeyInUrl: true
    },
    openrouter: {
      name: 'OpenRouter',
      icon: '🌐',
      models: ['meta-llama/llama-3.3-70b-instruct', 'anthropic/claude-haiku-4-5', 'openai/gpt-4o-mini', 'google/gemini-2.0-flash-001', 'mistralai/mixtral-8x7b-instruct'],
      defaultModel: 'meta-llama/llama-3.3-70b-instruct',
      endpoint: 'https://openrouter.ai/api/v1/chat/completions',
      headerKey: 'Authorization',
      headerVal: k => `Bearer ${k}`,
      extraHeaders: { 'HTTP-Referer': 'https://squeezeos.app', 'X-Title': 'SqueezeSim AI Coach' },
      bodyFn: (model, messages) => JSON.stringify({ model, messages, max_tokens: 1024, temperature: 0.7 }),
      parseFn: r => r.choices?.[0]?.message?.content || 'No response'
    }
  };

  const QUICK_PROMPTS = [
    { id: 'analyze', label: '📊 Analyze Portfolio', icon: '📊',
      fn: () => `Analyze my current trading portfolio and provide actionable insights:\n${_portfolioContext()}` },
    { id: 'strategy', label: '🎯 Suggest Strategy', icon: '🎯',
      fn: () => `Based on my trading history and current market conditions, suggest the best trading strategy for me:\n${_portfolioContext()}\n${_marketContext()}` },
    { id: 'risk', label: '🛡️ Risk Assessment', icon: '🛡️',
      fn: () => `Assess my current risk exposure and tell me if I should adjust my positions:\n${_portfolioContext()}` },
    { id: 'options', label: '🔮 Options Advice', icon: '🔮',
      fn: () => `I want to trade options. Based on my level and portfolio, what options strategies should I consider?\n${_portfolioContext()}` },
    { id: 'explain', label: '📚 Explain Greeks', icon: '📚',
      fn: () => 'Explain options Greeks (Delta, Gamma, Theta, Vega, Rho) in simple terms with practical examples for a retail trader.' },
    { id: 'lesson', label: '🎓 Daily Lesson', icon: '🎓',
      fn: () => `Give me a concise daily trading lesson appropriate for a ${SimEngine.state.levelName || 'beginner'} level trader. Include one actionable tip I can apply today.` },
    { id: 'journal', label: '📝 Trade Journal', icon: '📝',
      fn: () => `Review my recent trades and help me identify patterns, mistakes, and improvements:\n${_recentTradesContext()}` },
    { id: 'setup', label: '🔭 Scan Setups', icon: '🔭',
      fn: () => `Given the current simulated market conditions, identify the top 3 trading setups I should be watching:\n${_marketContext()}` }
  ];

  let _history = [];
  let _currentProvider = 'openrouter';
  let _isTyping = false;
  let _keys = { openrouter: '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' };
  let _models = { openrouter: 'meta-llama/llama-3.3-70b-instruct' };

  /* ── Context builders ── */
  function _portfolioContext() {
    const st = SimEngine.state;
    const pnl = st.portfolio - st.startingCapital;
    const positions = st.positions || {};
    const posStr = Object.entries(positions).map(([sym, p]) => {
      const curr = SimEngine.prices?.[sym] || p.avgPrice;
      const posPnl = (curr - p.avgPrice) * p.qty;
      return `  ${sym}: ${p.qty} shares @ $${p.avgPrice.toFixed(2)}, current $${curr.toFixed(2)}, P&L $${posPnl.toFixed(0)}`;
    }).join('\n') || '  No open positions';

    return `Portfolio Value: $${st.portfolio.toLocaleString('en', {maximumFractionDigits:0})}
Starting Capital: $${st.startingCapital.toLocaleString()}
Total P&L: ${pnl >= 0 ? '+' : ''}$${pnl.toFixed(0)}
Return: ${(pnl/st.startingCapital*100).toFixed(2)}%
Win Rate: ${st.winRate || 0}%
Total Trades: ${st.totalTrades || 0}
Level: ${st.levelName || 'Beginner'}
Open Positions:\n${posStr}`;
  }

  function _marketContext() {
    const prices = SimEngine.prices || {};
    const top5 = Object.entries(prices).slice(0, 5)
      .map(([sym, p]) => `  ${sym}: $${p.toFixed(2)}`).join('\n');
    return `Current Market Prices (simulated):\n${top5}`;
  }

  function _recentTradesContext() {
    const trades = (SimEngine.state.tradeHistory || []).slice(-10);
    if (!trades.length) return 'No trades yet.';
    return trades.map(t =>
      `  ${t.sym} ${t.side} ${t.qty}@$${t.price.toFixed(2)} → P&L: $${(t.pnl||0).toFixed(0)}`
    ).join('\n');
  }

  function _systemPrompt() {
    const st = SimEngine.state;
    return `You are an expert trading coach and mentor inside SqueezeOS Trading Simulator. You help users learn to trade stocks and options effectively.

User Profile:
- Trading Level: ${st.levelName || 'Beginner'}
- XP: ${st.xp || 0}
- Portfolio: $${(st.portfolio || 10000).toLocaleString()}
- Win Rate: ${st.winRate || 0}%

Rules:
1. Be concise but educational — max 3-4 paragraphs per response
2. Always relate advice to the user's current level and portfolio
3. Use specific numbers and percentages when possible
4. For beginners: explain concepts simply; for pros: be technical
5. This is a SIMULATOR — educational context only, not real financial advice
6. Always end with one concrete actionable step the user can take right now`;
  }

  /* ── API call ── */
  async function _callAPI(userMessage) {
    const provider = PROVIDERS[_currentProvider];
    if (!provider) throw new Error('Unknown provider');

    const key = _keys[_currentProvider];
    if (!key) throw new Error(`No API key set for ${provider.name}. Go to Settings → AI Coach to add your key.`);

    const model = _models[_currentProvider] || provider.defaultModel;

    const messages = [
      { role: 'system', content: _systemPrompt() },
      ..._history.map(h => ({ role: h.role, content: h.content })),
      { role: 'user', content: userMessage }
    ];

    const endpoint = typeof provider.endpoint === 'function'
      ? provider.endpoint(model, key)
      : provider.endpoint;

    const headers = {
      'Content-Type': 'application/json',
      [provider.headerKey]: provider.headerVal(key),
      ...(provider.extraHeaders || {})
    };

    if (provider.useKeyInUrl) {
      delete headers[provider.headerKey];
    }

    const resp = await fetch(endpoint, {
      method: 'POST',
      headers,
      body: provider.bodyFn(model, messages)
    });

    if (!resp.ok) {
      const errText = await resp.text();
      let errMsg = `API Error ${resp.status}`;
      try {
        const errJson = JSON.parse(errText);
        errMsg = errJson.error?.message || errJson.message || errMsg;
      } catch {}
      throw new Error(errMsg);
    }

    const data = await resp.json();
    return provider.parseFn(data);
  }

  /* ── Chat UI ── */
  function _appendMessage(role, content, isError) {
    const container = document.getElementById('ai-messages');
    if (!container) return;

    const div = document.createElement('div');
    div.className = `ai-msg ai-msg-${role} ${isError ? 'ai-msg-error' : ''}`;

    const avatar = role === 'user' ? '👤' : PROVIDERS[_currentProvider]?.icon || '🤖';
    const formatted = _formatMessage(content);

    div.innerHTML = `
      <div class="ai-avatar">${avatar}</div>
      <div class="ai-bubble">
        <div class="ai-bubble-content">${formatted}</div>
        <div class="ai-bubble-meta">${new Date().toLocaleTimeString()}</div>
      </div>
    `;

    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
  }

  function _formatMessage(text) {
    return text
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/\*(.+?)\*/g, '<em>$1</em>')
      .replace(/`(.+?)`/g, '<code>$1</code>')
      .replace(/\n\n/g, '</p><p>')
      .replace(/\n/g, '<br>')
      .replace(/^/, '<p>').replace(/$/, '</p>');
  }

  function _showTyping() {
    const container = document.getElementById('ai-messages');
    if (!container) return;
    const div = document.createElement('div');
    div.className = 'ai-msg ai-msg-assistant ai-typing';
    div.id = 'ai-typing-indicator';
    div.innerHTML = `
      <div class="ai-avatar">${PROVIDERS[_currentProvider]?.icon || '🤖'}</div>
      <div class="ai-bubble">
        <div class="ai-typing-dots"><span></span><span></span><span></span></div>
      </div>
    `;
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
  }

  function _hideTyping() {
    const el = document.getElementById('ai-typing-indicator');
    if (el) el.remove();
  }

  async function sendMessage(msgOverride) {
    if (_isTyping) return;

    const input = document.getElementById('ai-input');
    const msg = msgOverride || (input ? input.value.trim() : '');
    if (!msg) return;

    if (input) input.value = '';

    if (!_keys[_currentProvider]) {
      _appendMessage('assistant',
        `⚠️ No API key configured for ${PROVIDERS[_currentProvider]?.name}.\n\nGo to **Settings → AI Coach** and add your API key to start chatting. Your key is stored only in your browser — never sent to our servers.`,
        true);
      return;
    }

    _appendMessage('user', msg);
    _history.push({ role: 'user', content: msg });

    _isTyping = true;
    _showTyping();

    const sendBtn = document.getElementById('ai-send-btn');
    if (sendBtn) sendBtn.disabled = true;

    try {
      const response = await _callAPI(msg);
      _hideTyping();
      _appendMessage('assistant', response);
      _history.push({ role: 'assistant', content: response });

      // Keep history manageable
      if (_history.length > 20) _history = _history.slice(-20);

    } catch (err) {
      _hideTyping();
      _appendMessage('assistant', `❌ Error: ${err.message}`, true);
    } finally {
      _isTyping = false;
      if (sendBtn) sendBtn.disabled = false;
    }
  }

  function sendQuickPrompt(id) {
    const qp = QUICK_PROMPTS.find(q => q.id === id);
    if (!qp) return;
    const text = qp.fn();
    sendMessage(text);
  }

  function clearChat() {
    _history = [];
    const container = document.getElementById('ai-messages');
    if (container) {
      container.innerHTML = `
        <div class="ai-welcome">
          <div class="ai-welcome-icon">${PROVIDERS[_currentProvider]?.icon || '🤖'}</div>
          <h3>AI Trading Coach</h3>
          <p>Powered by ${PROVIDERS[_currentProvider]?.name || 'AI'}. Ask me anything about trading, strategies, or your portfolio!</p>
        </div>
      `;
    }
  }

  /* ── Settings / BYOK UI ── */
  function renderBYOKSettings() {
    const el = document.getElementById('byok-panel');
    if (!el) return;

    el.innerHTML = `
      <div class="byok-tabs">
        ${Object.entries(PROVIDERS).map(([id, p]) => `
          <button class="byok-tab ${id === _currentProvider ? 'active' : ''}"
            onclick="AICoach.switchProvider('${id}')">
            ${p.icon} ${p.name}
          </button>
        `).join('')}
      </div>
      ${Object.entries(PROVIDERS).map(([id, p]) => `
        <div class="byok-panel-content ${id === _currentProvider ? 'active' : ''}" id="byok-${id}">
          <div class="byok-intro">
            <strong>${p.icon} ${p.name}</strong>
            <span class="byok-status ${_keys[id] ? 'connected' : 'disconnected'}">
              ${_keys[id] ? '● Connected' : '○ Not configured'}
            </span>
          </div>
          <div class="byok-model-row">
            <label>Model</label>
            <select id="model-${id}" onchange="AICoach.setModel('${id}', this.value)">
              ${p.models.map(m => `<option value="${m}" ${(_models[id]||p.defaultModel)===m?'selected':''}>${m}</option>`).join('')}
            </select>
          </div>
          <div class="byok-key-row">
            <label>API Key</label>
            <div class="byok-key-input-wrap">
              <input type="password" id="key-${id}" placeholder="Enter your ${p.name} API key..."
                value="${_keys[id] ? '••••••••' + (_keys[id].slice(-4) || '') : ''}"
                onfocus="if(this.value.startsWith('••')) this.value=''"
              />
              <button class="btn-sm" onclick="AICoach.saveKey('${id}')">Save</button>
              <button class="btn-sm btn-danger" onclick="AICoach.clearKey('${id}')">Clear</button>
            </div>
          </div>
          <div class="byok-actions">
            <button class="btn-primary" onclick="AICoach.testKey('${id}')">Test Connection</button>
            <span id="test-result-${id}" class="test-result"></span>
          </div>
          <div class="byok-help">
            <p>🔒 Your API key is stored only in your browser's localStorage. It is never transmitted to our servers.</p>
            ${_getProviderHelp(id)}
          </div>
        </div>
      `).join('')}
    `;
  }

  function _getProviderHelp(id) {
    const links = {
      openai: 'Get your key at platform.openai.com/api-keys',
      anthropic: 'Get your key at console.anthropic.com',
      groq: 'Get your free key at console.groq.com (very fast, free tier)',
      gemini: 'Get your free key at aistudio.google.com/apikey'
    };
    return `<p>💡 ${links[id] || ''}</p>`;
  }

  function switchProvider(id) {
    if (!PROVIDERS[id]) return;
    _currentProvider = id;
    renderBYOKSettings();
    renderQuickPrompts();
    clearChat();

    // Update AI view header
    const hdr = document.getElementById('ai-provider-name');
    if (hdr) hdr.textContent = PROVIDERS[id].name;
  }

  function saveKey(providerId) {
    const input = document.getElementById(`key-${providerId}`);
    if (!input) return;
    const val = input.value.trim();
    if (!val || val.startsWith('••')) return;

    _keys[providerId] = val;
    _persistKeys();
    SimApp.toast(`${PROVIDERS[providerId].name} key saved!`, 'success');
    renderBYOKSettings();
  }

  function clearKey(providerId) {
    delete _keys[providerId];
    _persistKeys();
    SimApp.toast(`${PROVIDERS[providerId].name} key removed`, 'info');
    renderBYOKSettings();
  }

  function setModel(providerId, model) {
    _models[providerId] = model;
    _persistKeys();
  }

  async function testKey(providerId) {
    const resultEl = document.getElementById(`test-result-${providerId}`);
    if (resultEl) { resultEl.textContent = 'Testing...'; resultEl.className = 'test-result testing'; }

    const prevProvider = _currentProvider;
    _currentProvider = providerId;

    try {
      const resp = await _callAPI('Say "OK" in exactly 2 words.');
      _currentProvider = prevProvider;
      if (resultEl) { resultEl.textContent = '✅ Connected!'; resultEl.className = 'test-result success'; }
    } catch (err) {
      _currentProvider = prevProvider;
      if (resultEl) { resultEl.textContent = `❌ ${err.message.slice(0, 60)}`; resultEl.className = 'test-result error'; }
    }
  }

  function _persistKeys() {
    localStorage.setItem('sq_ai_keys', JSON.stringify(_keys));
    localStorage.setItem('sq_ai_models', JSON.stringify(_models));
    localStorage.setItem('sq_ai_provider', _currentProvider);
  }

  function _loadKeys() {
    try { _keys = JSON.parse(localStorage.getItem('sq_ai_keys') || '{}'); } catch { _keys = {}; }
    try { _models = JSON.parse(localStorage.getItem('sq_ai_models') || '{}'); } catch { _models = {}; }
    _currentProvider = localStorage.getItem('sq_ai_provider') || 'openai';
  }

  /* ── Quick prompts render ── */
  function renderQuickPrompts() {
    const el = document.getElementById('quick-prompts');
    if (!el) return;
    el.innerHTML = QUICK_PROMPTS.map(qp => `
      <button class="quick-prompt-btn" onclick="AICoach.sendQuickPrompt('${qp.id}')">
        ${qp.icon} ${qp.label}
      </button>
    `).join('');
  }

  /* ── Context-aware suggestions ── */
  function renderContextSuggestions() {
    const el = document.getElementById('ai-suggestions');
    if (!el) return;

    const st = SimEngine.state;
    const suggestions = [];

    if ((st.totalTrades || 0) === 0) {
      suggestions.push({ text: "I'm new to trading. What should I do first?", icon: '🌱' });
    }
    if ((st.winRate || 0) < 40 && (st.totalTrades || 0) > 10) {
      suggestions.push({ text: 'My win rate is low. How can I improve?', icon: '📉' });
    }
    if (Object.keys(st.positions || {}).length > 3) {
      suggestions.push({ text: 'I have many open positions. Should I close some?', icon: '⚠️' });
    }
    if ((st.levelName || '') === 'Intermediate') {
      suggestions.push({ text: 'I\'m ready for options. Where should I start?', icon: '🎓' });
    }
    if ((st.xp || 0) > 5000) {
      suggestions.push({ text: 'What advanced strategies should I learn next?', icon: '🚀' });
    }

    suggestions.push({ text: 'What is the Iron Condor strategy?', icon: '🦅' });
    suggestions.push({ text: 'How do I manage risk with options?', icon: '🛡️' });

    el.innerHTML = suggestions.slice(0, 4).map(s => `
      <button class="ai-suggestion-chip" onclick="AICoach.sendMessage('${s.text.replace(/'/g, "\\'")}')">
        ${s.icon} ${s.text}
      </button>
    `).join('');
  }

  /* ── Keyboard handler ── */
  function handleInputKeydown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  }

  /* ── Usage stats ── */
  function renderUsageStats() {
    const el = document.getElementById('ai-usage-stats');
    if (!el) return;
    const msgs = _history.filter(h => h.role === 'user').length;
    const st = SimEngine.state;
    const tier = st.subscriptionTier || 'free';
    const limits = { free: 10, starter: 50, pro: 200, elite: 'Unlimited' };
    const limit = limits[tier];

    el.innerHTML = `
      <span>Messages: <strong>${msgs}</strong></span>
      <span>Daily limit: <strong>${limit}</strong></span>
      <span>Provider: <strong>${PROVIDERS[_currentProvider]?.name || 'None'}</strong></span>
      ${_keys[_currentProvider] ? '<span class="ai-connected">● BYOK Active</span>' : '<span class="ai-disconnected">○ No Key</span>'}
    `;
  }

  /* ── Init ── */
  function init() {
    _loadKeys();

    const input = document.getElementById('ai-input');
    if (input) input.addEventListener('keydown', handleInputKeydown);

    renderQuickPrompts();
    renderBYOKSettings();
    renderContextSuggestions();
  }

  return {
    init,
    sendMessage,
    sendQuickPrompt,
    clearChat,
    renderBYOKSettings,
    renderQuickPrompts,
    renderContextSuggestions,
    renderUsageStats,
    switchProvider,
    saveKey,
    clearKey,
    setModel,
    testKey,
    handleInputKeydown,
    PROVIDERS,
    QUICK_PROMPTS
  };
})();
