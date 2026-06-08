"""
SQUEEZE OS — 402Proof Ghost Layer IPC Bridge
════════════════════════════════════════════════
Zero-serialization-delay bridge to the Go Notary.
Utilizes Unix Domain Sockets (UDS) with a fallback to Windows Named Pipes.
Payloads are packed into raw C-struct binaries for maximum throughput.
"""

import os
import time
import struct
import logging
import socket
from typing import Dict, Any, Optional

logger = logging.getLogger("Nexus402.IPC")

# IPC Paths
UDS_PATH = os.environ.get("GHOST_LAYER_UDS", "/tmp/x402_notary.sock")
NAMED_PIPE_PATH = os.environ.get("GHOST_LAYER_PIPE", r"\\.\pipe\x402_notary")

def _connect_ipc() -> Optional[Any]:
    """Establishes an IPC connection via UDS or Windows Named Pipe."""
    # Try AF_UNIX if supported by the OS/Python version
    if hasattr(socket, "AF_UNIX"):
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(1.0)
            sock.connect(UDS_PATH)
            return ("sock", sock)
        except Exception as e:
            logger.debug(f"[IPC] UDS connection failed: {e}. Trying Named Pipe fallback.")

    # Fallback to Windows Named Pipe
    if os.name == 'nt':
        try:
            pipe = open(NAMED_PIPE_PATH, 'r+b', buffering=0)
            return ("pipe", pipe)
        except Exception as e:
            logger.debug(f"[IPC] Named Pipe connection failed: {e}.")
            
    return None

def notarize_execution(symbol: str, directive: str, qty: int, limit_price: float, reason: str, dynamic_discount: float) -> Optional[Dict[str, Any]]:
    """
    Packs the execution receipt into a binary struct and blasts it over the IPC tunnel.
    """
    try:
        # ── 1. Raw Byte Packing ──
        # Format: < (Little Endian)
        # d (8 bytes) : timestamp
        # i (4 bytes) : qty
        # d (8 bytes) : limit_price
        # d (8 bytes) : dynamic_discount
        # 8s (8 bytes): symbol
        # 4s (4 bytes): directive
        # Total payload size = 8 + 4 + 8 + 8 + 8 + 4 = 40 bytes
        
        sym_bytes = symbol.encode('utf-8')[:8].ljust(8, b'\0')
        dir_bytes = directive.encode('utf-8')[:4].ljust(4, b'\0')
        ts = time.time()
        
        payload = struct.pack('<d i d d 8s 4s', ts, qty, limit_price, dynamic_discount, sym_bytes, dir_bytes)
        
        # ── 2. IPC Transmission ──
        conn = _connect_ipc()
        if not conn:
            logger.warning("[402PROOF] IPC Notary unreachable (UDS/Pipe down). Execution proceeds un-notarized.")
            return None
            
        conn_type, handler = conn
        
        logger.info(f"[402PROOF] Blasting 40-byte binary payload via {conn_type} for {symbol} execution...")
        
        if conn_type == "sock":
            handler.sendall(payload)
            # Expecting 76 bytes response: 12 bytes Cert ID + 64 bytes Ed25519 Signature
            response_data = handler.recv(76)
            handler.close()
        else: # pipe
            handler.write(payload)
            response_data = handler.read(76)
            handler.close()
            
        # ── 3. Unpack Response ──
        if len(response_data) == 76:
            cert_id_bytes, signature_bytes = struct.unpack('<12s 64s', response_data)
            cert_id = cert_id_bytes.decode('utf-8').rstrip('\0')
            signature_hex = signature_bytes.hex()
            
            logger.info(f"[402PROOF] Attestation secured. Certificate ID: {cert_id}")
            return {
                "certificate_id": cert_id,
                "signature": signature_hex,
                "issued_at": ts
            }
        else:
            logger.error(f"[402PROOF] Malformed binary response from Notary. Received {len(response_data)} bytes.")
            return None

    except Exception as e:
        logger.error(f"[402PROOF] Failed to mint execution receipt via IPC: {e}", exc_info=True)
        return None
