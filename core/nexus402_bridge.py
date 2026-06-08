"""
SQUEEZE OS — 402Proof Ghost Layer IPC Bridge
════════════════════════════════════════════════
Zero-serialization-delay bridge to the Go Notary.
Implements strict platform gating (TCP Loopback on Windows, AF_UNIX on Linux).
Payloads are aligned exclusively to 8-byte words for Go 64-bit architecture.
"""

import os
import time
import struct
import logging
import socket
import platform
from typing import Dict, Any, Optional

logger = logging.getLogger("Nexus402.IPC")

# ── Platform Gating ──
if platform.system() == "Windows":
    IPC_TYPE = "tcp"
    IPC_ADDRESS = ("127.0.0.1", 4020)
else:
    IPC_TYPE = "unix"
    IPC_ADDRESS = os.environ.get("GHOST_LAYER_UDS", "/tmp/x402_notary.sock")

def _connect_ipc() -> Optional[socket.socket]:
    """Establishes an OS-gated IPC connection."""
    try:
        if IPC_TYPE == "tcp":
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1.0)
            sock.connect(IPC_ADDRESS)
        else:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(1.0)
            sock.connect(IPC_ADDRESS)
        return sock
    except Exception as e:
        logger.debug(f"[IPC] {IPC_TYPE} connection failed: {e}")
        return None

def notarize_execution(symbol: str, directive: str, qty: int, limit_price: float, reason: str, dynamic_discount: float) -> Optional[Dict[str, Any]]:
    """
    Packs the execution receipt into a strictly aligned 48-byte struct.
    """
    try:
        # ── 1. Symmetrical Byte Packing ──
        # Format: < (Little Endian)
        # q (8 bytes) : timestamp (int64 milliseconds)
        # q (8 bytes) : qty (int64)
        # d (8 bytes) : limit_price (float64)
        # d (8 bytes) : dynamic_discount (float64)
        # 8s (8 bytes): symbol (padded)
        # 8s (8 bytes): directive (padded to 8 to maintain word alignment)
        # Total payload size = 48 bytes (Perfectly aligned for Go)
        
        sym_bytes = symbol.encode('utf-8')[:8].ljust(8, b'\0')
        dir_bytes = directive.encode('utf-8')[:8].ljust(8, b'\0')
        ts_ms = int(time.time() * 1000)
        qty_int = int(qty)
        
        payload = struct.pack('<q q d d 8s 8s', ts_ms, qty_int, limit_price, dynamic_discount, sym_bytes, dir_bytes)
        
        # ── 2. IPC Transmission ──
        sock = _connect_ipc()
        if not sock:
            logger.warning(f"[402PROOF] IPC Notary unreachable on {IPC_TYPE}. Execution proceeds un-notarized.")
            return None
            
        logger.info(f"[402PROOF] Blasting 48-byte aligned payload via {IPC_TYPE.upper()} for {symbol} execution...")
        
        sock.sendall(payload)
        
        # Expecting 76 bytes response: 12 bytes Cert ID + 64 bytes Ed25519 Signature
        response_data = sock.recv(76)
        sock.close()
            
        # ── 3. Unpack Response ──
        if len(response_data) == 76:
            cert_id_bytes, signature_bytes = struct.unpack('<12s 64s', response_data)
            cert_id = cert_id_bytes.decode('utf-8').rstrip('\0')
            signature_hex = signature_bytes.hex()
            
            logger.info(f"[402PROOF] Attestation secured. Certificate ID: {cert_id}")
            return {
                "certificate_id": cert_id,
                "signature": signature_hex,
                "issued_at": ts_ms
            }
        else:
            logger.error(f"[402PROOF] Malformed binary response from Notary. Received {len(response_data)} bytes.")
            return None

    except Exception as e:
        logger.error(f"[402PROOF] Failed to mint execution receipt via IPC: {e}", exc_info=True)
        return None
