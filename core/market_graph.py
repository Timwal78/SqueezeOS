"""
SML MarketGraphify — Neo4j AuraDB Graph Engine
Maps tickers as nodes, Greek sensitivities + dark pool flows as edges.
Part of the ScriptMasterLabs Command Center 2027.
"""
import os
import logging
from datetime import datetime
from typing import Optional
from neo4j import GraphDatabase

logger = logging.getLogger(__name__)

# ── Credentials ──
# neo4j+ssc = SSL with self-signed cert support (works on Windows without cert store)
NEO4J_URI      = os.getenv("NEO4J_URI",      "neo4j+s://e57655ba.databases.neo4j.io").replace("neo4j+s://", "neo4j+ssc://")
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME", "e57655ba")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "Ht8JMleC3KCOPd_ORFEdBB6VbjUZHeDA_dyRb-S07Mc")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "e57655ba")

# ── SML Universe ──
SML_TICKERS = ["GME", "AMC", "IWM"]
SWEET_SPOT  = (1.0, 60.0)


class MarketGraph:
    """
    Persistent graph of market relationships.

    Nodes:   (:Ticker {symbol, price, regime, last_updated})
    Edges:   GAMMA_CORRELATED  — shared GEX exposure
             DARK_POOL_FLOW    — dark pool print direction
             FRACTAL_ECHO      — fractal pattern match
             BASKET_MEMBER     — basket membership
    """

    def __init__(self):
        self.driver = GraphDatabase.driver(
            NEO4J_URI,
            auth=(NEO4J_USERNAME, NEO4J_PASSWORD)
        )
        self._seed_schema()
        logger.info("[GRAPH] MarketGraphify connected to Neo4j AuraDB.")

    # ── Schema + Seed ─────────────────────────────────────────────────────────

    def _seed_schema(self):
        """Create constraint + seed the 3 SML ticker nodes if missing."""
        with self.driver.session(database=NEO4J_DATABASE) as s:
            # Uniqueness constraint
            s.run("""
                CREATE CONSTRAINT ticker_symbol IF NOT EXISTS
                FOR (t:Ticker) REQUIRE t.symbol IS UNIQUE
            """)
            # Seed ticker nodes
            for sym in SML_TICKERS:
                s.run("""
                    MERGE (t:Ticker {symbol: $sym})
                    ON CREATE SET t.price = 0.0,
                                  t.regime = 'UNKNOWN',
                                  t.sweet_spot = ($lo <= 0.0 <= $hi),
                                  t.created_at = $ts
                """, sym=sym, lo=SWEET_SPOT[0], hi=SWEET_SPOT[1],
                     ts=datetime.utcnow().isoformat())
            # Seed basket edges
            for sym in ["GME", "AMC"]:
                s.run("""
                    MATCH (a:Ticker {symbol: $sym}), (b:Ticker {symbol: 'IWM'})
                    MERGE (a)-[:BASKET_MEMBER]->(b)
                """, sym=sym)

    # ── Node Updates ──────────────────────────────────────────────────────────

    def update_ticker(self, symbol: str, price: float, regime: str,
                      vpin: float = 0.0, gex: float = 0.0):
        """Update a ticker node with live market data."""
        sweet = SWEET_SPOT[0] <= price <= SWEET_SPOT[1]
        with self.driver.session(database=NEO4J_DATABASE) as s:
            s.run("""
                MERGE (t:Ticker {symbol: $sym})
                SET t.price        = $price,
                    t.regime       = $regime,
                    t.vpin         = $vpin,
                    t.gex          = $gex,
                    t.sweet_spot   = $sweet,
                    t.last_updated = $ts
            """, sym=symbol, price=price, regime=regime,
                 vpin=vpin, gex=gex, sweet=sweet,
                 ts=datetime.utcnow().isoformat())

    # ── Edge Writers ──────────────────────────────────────────────────────────

    def write_gamma_correlation(self, sym_a: str, sym_b: str,
                                 weight: float, direction: str):
        """Write or update a GAMMA_CORRELATED edge between two tickers."""
        with self.driver.session(database=NEO4J_DATABASE) as s:
            s.run("""
                MATCH (a:Ticker {symbol: $a}), (b:Ticker {symbol: $b})
                MERGE (a)-[r:GAMMA_CORRELATED]->(b)
                SET r.weight    = $weight,
                    r.direction = $direction,
                    r.ts        = $ts
            """, a=sym_a, b=sym_b, weight=weight,
                 direction=direction, ts=datetime.utcnow().isoformat())

    def write_dark_pool_flow(self, symbol: str, flow_usd: float,
                              direction: str, confidence: float):
        """Write a DARK_POOL_FLOW self-edge (dark pool print on this ticker)."""
        with self.driver.session(database=NEO4J_DATABASE) as s:
            s.run("""
                MATCH (t:Ticker {symbol: $sym})
                SET t.dp_flow_usd   = $flow,
                    t.dp_direction  = $direction,
                    t.dp_confidence = $conf,
                    t.dp_ts         = $ts
            """, sym=symbol, flow=flow_usd, direction=direction,
                 conf=confidence, ts=datetime.utcnow().isoformat())

    def write_fractal_echo(self, sym_a: str, sym_b: str,
                            match_label: str, score: float, target: float):
        """Write a FRACTAL_ECHO edge between two correlated tickers."""
        with self.driver.session(database=NEO4J_DATABASE) as s:
            s.run("""
                MATCH (a:Ticker {symbol: $a}), (b:Ticker {symbol: $b})
                MERGE (a)-[r:FRACTAL_ECHO]->(b)
                SET r.match_label = $label,
                    r.score       = $score,
                    r.target      = $target,
                    r.ts          = $ts
            """, a=sym_a, b=sym_b, label=match_label,
                 score=score, target=target, ts=datetime.utcnow().isoformat())

    # ── Query Layer ───────────────────────────────────────────────────────────

    def get_all_tickers(self) -> list:
        """Return all ticker nodes with their current properties."""
        with self.driver.session(database=NEO4J_DATABASE) as s:
            result = s.run("""
                MATCH (t:Ticker)
                RETURN t.symbol AS symbol,
                       t.price AS price,
                       t.regime AS regime,
                       t.vpin AS vpin,
                       t.gex AS gex,
                       t.sweet_spot AS sweet_spot,
                       t.dp_flow_usd AS dp_flow,
                       t.dp_direction AS dp_dir,
                       t.last_updated AS ts
                ORDER BY t.symbol
            """)
            return [dict(r) for r in result]

    def get_edges(self, symbol: Optional[str] = None) -> list:
        """Return all relationship edges, optionally filtered by ticker."""
        with self.driver.session(database=NEO4J_DATABASE) as s:
            if symbol:
                result = s.run("""
                    MATCH (a:Ticker {symbol: $sym})-[r]->(b:Ticker)
                    RETURN a.symbol AS from, type(r) AS rel,
                           b.symbol AS to, properties(r) AS props
                """, sym=symbol)
            else:
                result = s.run("""
                    MATCH (a:Ticker)-[r]->(b:Ticker)
                    RETURN a.symbol AS from, type(r) AS rel,
                           b.symbol AS to, properties(r) AS props
                """)
            return [dict(r) for r in result]

    def get_graph_snapshot(self) -> dict:
        """Full graph snapshot for the ORACLE dashboard."""
        return {
            "nodes": self.get_all_tickers(),
            "edges": self.get_edges(),
            "snapshot_ts": datetime.utcnow().isoformat()
        }

    def close(self):
        self.driver.close()


# ── Singleton accessor ────────────────────────────────────────────────────────

_graph_instance: Optional[MarketGraph] = None

def get_graph() -> Optional[MarketGraph]:
    global _graph_instance
    if _graph_instance is None:
        try:
            _graph_instance = MarketGraph()
        except Exception as e:
            logger.error(f"[GRAPH] Failed to connect to Neo4j: {e}")
    return _graph_instance
