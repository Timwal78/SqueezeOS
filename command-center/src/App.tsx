import { useEffect, useState } from 'react';
import { Activity, Zap, Radio, Target, Cpu, Layers, Crosshair, AlertTriangle } from 'lucide-react';
import Scanner from './Scanner';
import BeastmodeModal from './BeastmodeModal';
import './index.css';

const PRIMARY_TICKERS = ['AMC', 'GME', 'IWM'];
const API_URL = import.meta.env.VITE_API_URL || 'https://squeezeos-api.onrender.com';
const TIPMASTER_URL = import.meta.env.VITE_TIPMASTER_URL || 'https://tipmaster.onrender.com';

interface OracleData {
  symbol: string;
  directive: string;
  confidence: number;
  price: number;
  volume: number;
  vpin: number;
  regime: string;
  reason: string;
  gamma_flip: boolean;
  gamma_wall_above: number;
  gamma_wall_below: number;
  tp1: number;
  tp2: number;
  stop: number;
  timestamp: string;
  error?: boolean;
}

interface TipMasterData {
  totalTips: number;
  topTipper: string;
  topTipperAmount: number;
}

const BeastmodeTerminal = () => {
  const [oracleData, setOracleData] = useState<Record<string, OracleData>>({});
  const [events, setEvents] = useState<any[]>([]);
  const [isConnected, setIsConnected] = useState(false);
  const [tipMasterData, setTipMasterData] = useState<TipMasterData>({ totalTips: 0, topTipper: 'N/A', topTipperAmount: 0 });
  const [modalTicker, setModalTicker] = useState<string | null>(null);

  // 1. Fetch Oracle Council Data for Primary Tickers
  useEffect(() => {
    const fetchOracle = async () => {
      const newData: Record<string, OracleData> = {};
      try {
        for (const sym of PRIMARY_TICKERS) {
          try {
            const res = await fetch(`${API_URL}/api/oracle/${sym}`);
            if (res.ok) {
              const data = await res.json();
              if (data.status === 'success' && data.oracle) {
                newData[sym] = data.oracle;
              } else {
                newData[sym] = { symbol: sym, directive: 'N/A', confidence: 0, price: 0, volume: 0, vpin: 0, regime: 'OFFLINE', reason: 'N/A', gamma_flip: false, gamma_wall_above: 0, gamma_wall_below: 0, tp1: 0, tp2: 0, stop: 0, timestamp: '', error: true };
              }
            } else {
              newData[sym] = { symbol: sym, directive: 'N/A', confidence: 0, price: 0, volume: 0, vpin: 0, regime: 'OFFLINE', reason: 'N/A', gamma_flip: false, gamma_wall_above: 0, gamma_wall_below: 0, tp1: 0, tp2: 0, stop: 0, timestamp: '', error: true };
            }
          } catch (e) {
            console.error(`Failed to fetch oracle data for ${sym}:`, e);
            newData[sym] = { symbol: sym, directive: 'N/A', confidence: 0, price: 0, volume: 0, vpin: 0, regime: 'OFFLINE', reason: 'N/A', gamma_flip: false, gamma_wall_above: 0, gamma_wall_below: 0, tp1: 0, tp2: 0, stop: 0, timestamp: '', error: true };
          }
        }
        setOracleData(newData);
      } catch (e) {
        console.error('Failed to fetch oracle data');
      }
    };

    fetchOracle();
    const interval = setInterval(fetchOracle, 15000); // 15s refresh
    return () => clearInterval(interval);
  }, []);

  // 2. Connect to SSE Live Event Stream
  useEffect(() => {
    const source = new EventSource(`${API_URL}/api/events`);
    
    source.onopen = () => setIsConnected(true);
    source.onerror = () => setIsConnected(false);
    
    source.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);
        if (data.type === 'CONNECTED') return;
        
        // Add to front of feed, keep last 100 events
        setEvents(prev => {
          // Prevent duplicates by ts/type/symbol
          const isDup = prev.find(p => p.ts === data.ts && p.symbol === data.symbol && p.type === data.type);
          if (isDup) return prev;
          return [data, ...prev].slice(0, 100);
        });
      } catch (err) {
        console.error("SSE Parse Error:", err);
      }
    };
    
    return () => {
      source.close();
      setIsConnected(false);
    };
  }, []);

  // 3. Fetch TipMaster Data (Live)
  useEffect(() => {
    const fetchTipMaster = async () => {
      try {
        const res = await fetch(`${TIPMASTER_URL}/api/leaderboard?period=alltime&limit=5`);
        if (res.ok) {
          const data = await res.json();
          if (data.leaderboard && data.leaderboard.length > 0) {
            const total = data.leaderboard.reduce((acc: number, cur: any) => acc + cur.amount, 0);
            setTipMasterData({
              totalTips: total,
              topTipper: data.leaderboard[0].username,
              topTipperAmount: data.leaderboard[0].amount
            });
          }
        }
      } catch (e) {
        // Fallback to 0 if TipMaster isn't running
      }
    };
    fetchTipMaster();
    const interval = setInterval(fetchTipMaster, 30000); // 30s refresh
    return () => clearInterval(interval);
  }, []);

  // Format Helpers
  const formatDir = (d: string) => {
    if (d === 'BUY') return <span className="dir-buy">BUY</span>;
    if (d === 'SELL') return <span className="dir-sell">SELL</span>;
    if (d === 'SHIELD') return <span className="dir-shield">SHIELD</span>;
    return <span className="dir-hold">HOLD</span>;
  };

  return (
    <div className="terminal-container">
      {/* HEADER: Streaming Tickers */}
      <div className="ticker-tape">
        <div className="ticker-label">
          <Activity size={16} className={isConnected ? "text-green animate-pulse" : "text-red"} />
          LIVE TAPE
        </div>
        <div className="ticker-stream">
          {PRIMARY_TICKERS.map(sym => {
            const d = oracleData[sym];
            if (!d || d.error) return <span key={sym} className="ticker-item">{sym} <span className="text-muted">...</span></span>;
            return (
              <span key={sym} className="ticker-item">
                <strong>{sym}</strong> ${d.price.toFixed(2)} 
                <span className="ticker-dir">{formatDir(d.directive)}</span>
                <span className="ticker-conf">[{d.confidence}%]</span>
              </span>
            );
          })}
        </div>
        <div className="sse-status">
          <Radio size={14} className={isConnected ? "text-green" : "text-red"} /> 
          {isConnected ? "SSE CONNECTED" : "RECONNECTING..."}
        </div>
      </div>

      <div className="terminal-grid">
        {/* NEW LEFT COLUMN: Market Scanner */}
        <Scanner onSelectTicker={(sym) => setModalTicker(sym)} />

        {/* MIDDLE COLUMN: Agent Council (Primary Tickers) */}
        <div className="council-column">
          <h2 className="panel-title"><Cpu size={18} /> SqueezeOS Council Analysis</h2>
          <div className="council-cards">
            {PRIMARY_TICKERS.map(sym => {
              const d = oracleData[sym];
              if (!d) return (
                <div key={sym} className="agent-card loading">
                   <div className="loader"></div> Processing {sym}...
                </div>
              );
              
              if (d.error) {
                return (
                  <div key={sym} className="agent-card" style={{ borderColor: 'var(--accent-red)' }}>
                    <div className="card-header">
                      <span className="card-symbol text-red">{sym} <AlertTriangle size={14} style={{ display: 'inline' }} /></span>
                      <span className="conf-badge" style={{ background: 'var(--accent-red)' }}>OFFLINE</span>
                    </div>
                    <div className="card-metrics" style={{ color: 'var(--accent-red)', fontSize: '0.8rem', padding: '10px 0' }}>
                      Render API is Suspended or Unreachable. Please check the backend.
                    </div>
                  </div>
                );
              }
              
              const isBuy = d.directive === 'BUY';
              const isSell = d.directive === 'SELL';
              
              return (
                <div key={sym} className={`agent-card ${isBuy ? 'border-buy' : isSell ? 'border-sell' : ''}`}>
                  <div className="card-header">
                    <span className="card-symbol">{d.symbol}</span>
                    <div className="card-verdict">
                      {formatDir(d.directive)} <span className="conf-badge">{d.confidence}% Conf</span>
                    </div>
                  </div>
                  
                  <div className="card-metrics">
                    <div className="metric">
                      <label>Last Price</label>
                      <span>${d.price.toFixed(2)}</span>
                    </div>
                    <div className="metric">
                      <label>Regime</label>
                      <span className="text-cyan">{d.regime}</span>
                    </div>
                    <div className="metric">
                      <label>VPIN Tox</label>
                      <span className={d.vpin > 0.65 ? 'text-red' : 'text-green'}>{(d.vpin * 100).toFixed(1)}%</span>
                    </div>
                    <div className="metric">
                      <label>TP1 / TP2</label>
                      <span className="text-green">{d.tp1 ? `$${d.tp1}` : 'N/A'} / {d.tp2 ? `$${d.tp2}` : 'N/A'}</span>
                    </div>
                    <div className="metric">
                      <label>Stop Loss</label>
                      <span className="text-red">{d.stop ? `$${d.stop}` : 'N/A'}</span>
                    </div>
                  </div>

                  <div className="gamma-walls">
                    <div className="gamma-item above">
                      <label>Call Wall (Above)</label>
                      <span>{d.gamma_wall_above ? `$${d.gamma_wall_above}` : 'None'}</span>
                    </div>
                    <div className="gamma-item below">
                      <label>Put Wall (Below)</label>
                      <span>{d.gamma_wall_below ? `$${d.gamma_wall_below}` : 'None'}</span>
                    </div>
                  </div>

                  <div className="agent-reasoning">
                    <Target size={14} className="reason-icon" />
                    <p>{d.reason}</p>
                  </div>
                </div>
              );
            })}
          </div>

          {/* TIPMASTER LIVE METRICS */}
          <div className="tipmaster-panel mt-6">
            <h2 className="panel-title"><Zap size={18} className="text-yellow" /> TipMaster Telemetry</h2>
            <div className="tipmaster-grid">
              <div className="tm-stat">
                <label>Total XRPL Volume</label>
                <span>{tipMasterData.totalTips} RLUSD</span>
              </div>
              <div className="tm-stat">
                <label>Top Tipper</label>
                <span>@{tipMasterData.topTipper} ({tipMasterData.topTipperAmount})</span>
              </div>
            </div>
          </div>
        </div>

        {/* RIGHT COLUMN: Options Anomaly & Sweep Radar */}
        <div className="radar-column">
          <h2 className="panel-title"><Zap size={18} className="text-yellow" /> Live Flow Radar (0DTE Focus)</h2>
          <div className="radar-feed">
            {events.length === 0 ? (
              <div className="empty-feed">
                <Layers size={32} className="text-muted mb-2" />
                <p>Awaiting institutional flow signals...</p>
              </div>
            ) : (
              events.map((evt, idx) => {
                const ts = new Date(evt.ts * 1000).toLocaleTimeString([], { hour12: false });
                
                if (evt.type === 'OPTIONS_ANOMALY') {
                  const sevColor = evt.severity === 'CRITICAL' ? 'text-red' : evt.severity === 'SUSPICIOUS' ? 'text-yellow' : 'text-cyan';
                  return (
                    <div key={`${evt.ts}-${idx}`} className="feed-item anomaly">
                      <div className="feed-header">
                        <span className="feed-time">{ts}</span>
                        <span className={`feed-badge ${sevColor}`}><AlertTriangle size={12}/> {evt.anomaly_type}</span>
                        <span className="feed-symbol">{evt.symbol}</span>
                      </div>
                      <p className="feed-body">{evt.thesis}</p>
                    </div>
                  );
                }
                
                if (evt.type === 'OPTIONS_SWEEP') {
                  // Universal Rule: Only show A and A+ grades
                  if (evt.grade !== 'A' && evt.grade !== 'A+') {
                    return null;
                  }

                  // IWM Rule: ONLY 0DTE
                  if (evt.symbol === 'IWM') {
                    const estFormatter = new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', year: 'numeric', month: '2-digit', day: '2-digit' });
                    const parts = estFormatter.formatToParts(new Date());
                    const year = parts.find((p: any) => p.type === 'year')?.value;
                    const month = parts.find((p: any) => p.type === 'month')?.value;
                    const day = parts.find((p: any) => p.type === 'day')?.value;
                    const today = `${year}-${month}-${day}`;

                    if (evt.expiration !== today) {
                      return null; // Skip non-0DTE sweeps for IWM
                    }
                  }

                  const typeColor = evt.option_type?.toLowerCase() === 'call' ? 'text-green' : 'text-red';
                  return (
                    <div key={`${evt.ts}-${idx}`} className="feed-item sweep">
                      <div className="feed-header">
                        <span className="feed-time">{ts}</span>
                        <span className="feed-badge text-purple"><Crosshair size={12}/> 0DTE SWEEP (Grade {evt.grade})</span>
                        <span className="feed-symbol">{evt.symbol}</span>
                      </div>
                      <p className="feed-body">
                        ${evt.strike} <span className={typeColor}>{evt.option_type?.toUpperCase()}</span> exp {evt.expiration} @ ${evt.mid}
                      </p>
                    </div>
                  );
                }

                if (evt.type === 'SQUEEZE_ALERT') {
                  return (
                    <div key={`${evt.ts}-${idx}`} className="feed-item squeeze">
                      <div className="feed-header">
                        <span className="feed-time">{ts}</span>
                        <span className="feed-badge text-green"><Zap size={12}/> TECH SQUEEZE</span>
                        <span className="feed-symbol">{evt.symbol}</span>
                      </div>
                      <p className="feed-body">
                        Score: {evt.score} | Dir: {evt.direction} | Price: ${evt.price}
                      </p>
                    </div>
                  );
                }
                
                return null;
              })
            )}
          </div>
        </div>
      </div>
      
      {/* BEASTMODE AI MODAL */}
      <BeastmodeModal ticker={modalTicker} onClose={() => setModalTicker(null)} />
    </div>
  );
};

export default BeastmodeTerminal;
