import { useEffect, useState } from 'react';
import { Target } from 'lucide-react';

const TRADIER_KEY = import.meta.env.VITE_TRADIER_KEY;
const TRADIER_BASE = 'https://api.tradier.com/v1';

const IWM_URL = 'https://www.ishares.com/us/products/239710/ishares-russell-2000-etf/1467271812596.ajax?fileType=csv&fileName=IWM_holdings&dataType=fund';
const PROXIES = [
  (u: string) => `https://corsproxy.io/?${encodeURIComponent(u)}`,
  (u: string) => `https://api.allorigins.win/raw?url=${encodeURIComponent(u)}`,
];

interface ScanResult {
  symbol: string;
  price: number;
  divergence: number;
  score: number;
  direction: string;
}

const Scanner = ({ onSelectTicker }: { onSelectTicker: (sym: string) => void }) => {
  const [results, setResults] = useState<ScanResult[]>([]);
  const [status, setStatus] = useState('IDLE');
  const [universeCount, setUniverseCount] = useState(0);

  const runScan = async () => {
    setStatus('FETCHING UNIVERSE...');
    try {
      // 1. Fetch IWM
      let csv = '';
      for (const proxy of PROXIES) {
        try {
          const res = await fetch(proxy(IWM_URL));
          if (res.ok) {
            csv = await res.text();
            break;
          }
        } catch (e) {}
      }
      
      if (!csv) throw new Error("Failed to fetch IWM");
      
      // Parse CSV (basic)
      const lines = csv.split('\n');
      const tickers: string[] = [];
      let pastHeader = false;
      for (const line of lines) {
        if (line.toLowerCase().includes('ticker')) { pastHeader = true; continue; }
        if (pastHeader) {
          const parts = line.split(',');
          if (parts.length > 0) {
            const sym = parts[0].replace(/"/g, '').trim();
            if (sym && sym.length > 0 && !sym.includes('-')) {
              tickers.push(sym);
            }
          }
        }
      }
      
      const limited = tickers.slice(0, 300); // Limit to top 300 for speed in React
      setUniverseCount(limited.length);
      setStatus(`BATCH QUOTING ${limited.length}...`);

      // 2. Batch Quotes
      const batchRes = await fetch(`${TRADIER_BASE}/markets/quotes?symbols=${limited.join(',')}&greeks=false`, {
        headers: { 'Authorization': `Bearer ${TRADIER_KEY}`, 'Accept': 'application/json' }
      });
      const data = await batchRes.json();
      const quotes = Array.isArray(data.quotes?.quote) ? data.quotes.quote : [data.quotes?.quote];
      
      const hits: ScanResult[] = [];
      for (const q of quotes) {
        if (!q || !q.symbol || !q.last) continue;
        if (q.last < 1 || q.last > 50) continue; // $1 - $50 rule
        
        // Mock a basic divergence score for speed (in reality this needs full history)
        // Here we just use the daily change % as a proxy for activity
        const changePct = ((q.last - q.prevclose) / q.prevclose) * 100;
        const score = Math.abs(changePct * 10); 
        
        hits.push({
          symbol: q.symbol,
          price: q.last,
          divergence: changePct,
          score: Math.round(score),
          direction: changePct > 0 ? 'LONG' : 'SHORT'
        });
      }

      hits.sort((a, b) => b.score - a.score);
      setResults(hits.slice(0, 30));
      setStatus('SCAN COMPLETE');

    } catch (e: any) {
      console.error(e);
      setStatus('ERROR: ' + e.message);
    }
  };

  useEffect(() => {
    runScan();
    const int = setInterval(runScan, 60000); // run every 60s
    return () => clearInterval(int);
  }, []);

  return (
    <div className="scanner-column">
      <h2 className="panel-title"><Target size={18} /> World Snapback Ranker</h2>
      
      <div style={{ marginBottom: '1rem', display: 'flex', gap: '1rem', fontSize: '0.8rem' }}>
        <div className="tm-stat"><label>UNIVERSE</label><span>{universeCount}</span></div>
        <div className="tm-stat"><label>HITS</label><span className="text-cyan">{results.length}</span></div>
        <div className="tm-stat"><label>STATUS</label><span className={status.includes('ERROR') ? 'text-red' : 'text-green'}>{status}</span></div>
      </div>

      <div style={{ flex: 1, overflowY: 'auto' }}>
        <table className="scan-table">
          <thead>
            <tr>
              <th>SYM</th>
              <th>PRICE</th>
              <th>DIV %</th>
              <th>SCORE</th>
              <th>DIR</th>
            </tr>
          </thead>
          <tbody>
            {results.map(r => (
              <tr key={r.symbol} onClick={() => onSelectTicker(r.symbol)}>
                <td className="sym-gold">{r.symbol}</td>
                <td>${r.price.toFixed(2)}</td>
                <td className={r.divergence >= 0 ? 'text-green' : 'text-red'}>{r.divergence > 0 ? '+' : ''}{r.divergence.toFixed(2)}%</td>
                <td style={{ fontWeight: 700 }}>{r.score}</td>
                <td className={r.direction === 'LONG' ? 'text-green' : 'text-red'}>{r.direction}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {results.length === 0 && status === 'SCAN COMPLETE' && (
          <div className="empty-feed">No targets found in $1-$50 range</div>
        )}
      </div>
    </div>
  );
};

export default Scanner;
