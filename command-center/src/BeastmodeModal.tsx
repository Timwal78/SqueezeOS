import { useState, useEffect } from 'react';

interface BeastmodeModalProps {
  ticker: string | null;
  onClose: () => void;
}

const OPENROUTER_KEY = import.meta.env.VITE_OPENROUTER_KEY;
const OPENROUTER_BASE = 'https://openrouter.ai/api/v1';
const MODEL = 'google/gemini-2.5-flash';

const POLYGON_KEY = import.meta.env.VITE_POLYGON_KEY;

function calculateEMA(closes: number[], period: number) {
  if (closes.length < period) return null;
  const k = 2 / (period + 1);
  let ema = closes[0];
  for (let i = 1; i < closes.length; i++) {
    ema = (closes[i] - ema) * k + ema;
  }
  return ema;
}

const BeastmodeModal = ({ ticker, onClose }: BeastmodeModalProps) => {
  const [output, setOutput] = useState<string>('');
  const [loading, setLoading] = useState(false);

  const analyzeTicker = async () => {
    if (!ticker) return;
    setLoading(true);
    setOutput(`Fetching 65-minute historical data for ${ticker} from Polygon...`);
    
    try {
      // 1. Fetch 65-Minute Polygon Data
      const toDate = new Date().toISOString().split('T')[0];
      const fromDate = new Date(Date.now() - 2 * 365 * 24 * 60 * 60 * 1000).toISOString().split('T')[0];
      const polyUrl = `https://api.polygon.io/v2/aggs/ticker/${ticker}/range/65/minute/${fromDate}/${toDate}?adjusted=true&sort=asc&limit=50000&apiKey=${POLYGON_KEY}`;
      
      const polyRes = await fetch(polyUrl);
      if (!polyRes.ok) {
        throw new Error(`Polygon API Error: ${polyRes.status} ${await polyRes.text()}`);
      }
      
      const polyData = await polyRes.json();
      if (!polyData.results || polyData.results.length === 0) {
        throw new Error(`Polygon returned no 65-minute data for ${ticker}.`);
      }
      
      const closes = polyData.results.map((r: any) => r.c);
      const currentPrice = closes[closes.length - 1];
      
      const e1 = currentPrice;
      const e24 = calculateEMA(closes, 24);
      const e578 = calculateEMA(closes, 578);
      const e963 = calculateEMA(closes, 963);
      
      const emaText = `
**65-Minute EMAs (SqueezeOS 1-24-578-963 System):**
- EMA 1 (Current Price): $${e1.toFixed(2)}
- EMA 24 (Momentum): ${e24 ? '$' + e24.toFixed(2) : 'N/A'}
- EMA 578 (Resistance): ${e578 ? '$' + e578.toFixed(2) : 'N/A (Needs 578 periods)'}
- EMA 963 (Master Harmonic): ${e963 ? '$' + e963.toFixed(2) : 'N/A (Needs 963 periods)'}
`;
      setOutput(`Data Fetched!\n${emaText}\nInitiating Beastmode AI analysis via OpenRouter...`);

      // 2. Fetch AI Analysis
      const prompt = `Perform a rapid tactical analysis on ${ticker}.

Here is the live 65-minute EMA data:
${emaText}

Given the current price relative to the 578 and 963 EMAs, provide:
1. Regime Status (Squeeze or Mean Revert?)
2. Technical Targets (Upside/Downside)
3. 0DTE Options Flow bias (if any)
Keep it extremely concise, markdown format, with a sharp institutional tone.`;

      const res = await fetch(`${OPENROUTER_BASE}/chat/completions`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${OPENROUTER_KEY}`,
          'Content-Type': 'application/json',
          'HTTP-Referer': 'http://localhost:3000',
          'X-Title': 'SqueezeOS Command Center'
        },
        body: JSON.stringify({
          model: MODEL,
          messages: [{ role: 'user', content: prompt }]
        })
      });

      if (!res.ok) {
        const err = await res.text();
        throw new Error(`OpenRouter 429 / Error: ${err}`);
      }

      const data = await res.json();
      if (data.choices && data.choices[0]) {
        setOutput(`${emaText}\n\n---\n\n${data.choices[0].message.content}`);
      } else {
        setOutput("No response from AI.");
      }
    } catch (e: any) {
      setOutput(`TEST FAILED:\n${e.message}`);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (ticker) analyzeTicker();
  }, [ticker]);

  if (!ticker) return null;

  return (
    <div className="modal-backdrop" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal">
        <div className="modal-header">
          <h2>⚡ BEASTMODE ANALYSIS <span className="text-yellow">{ticker}</span></h2>
          <button className="modal-close" onClick={onClose}>CLOSE [ESC]</button>
        </div>
        <div className="modal-body">
          {loading && <div className="loader" style={{ marginBottom: '1rem', borderTopColor: 'var(--accent-purple)', borderLeftColor: 'var(--accent-purple)' }}></div>}
          <div style={{ whiteSpace: 'pre-wrap', fontFamily: 'var(--font-mono)' }}>
            {output}
          </div>
        </div>
        <div className="modal-footer">
          <button className="btn-pink" onClick={analyzeTicker} disabled={loading}>
            REGENERATE
          </button>
        </div>
      </div>
    </div>
  );
};

export default BeastmodeModal;
