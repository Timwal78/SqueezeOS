"""Shared utilities for SqueezeOS Vercel API functions."""
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import json


def parse_query(handler: "BaseHTTPRequestHandler") -> dict:
    return {k: v[0] for k, v in parse_qs(urlparse(handler.path).query).items()}


def send_json(handler: "BaseHTTPRequestHandler", data: dict, status: int = 200) -> None:
    body = json.dumps(data).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def send_cors_preflight(handler: "BaseHTTPRequestHandler") -> None:
    handler.send_response(200)
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type")
    handler.end_headers()
