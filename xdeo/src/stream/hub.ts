// Real-time stream fan-out via a single global Durable Object. Backs both a
// WebSocket endpoint (hibernatable) and an SSE endpoint for browsers/agents that
// prefer EventStream. Components publish events with `publishEvent()`; the hub
// broadcasts to every connected client.
//
// Spec alignment: "Durable Objects for state management" + "streaming WebSocket
// for real-time estimate updates".

import type { Env } from "../types.js";

export interface StreamEvent {
  type: string; // ESTIMATE_SUBMITTED | ESTIMATE_SCORED | VERDICT_READY | CONNECTED | ...
  data: unknown;
  ts: number; // unix ms
}

/** Serialize an event as an SSE frame. Pure — unit-tested. */
export function formatSSE(e: StreamEvent): string {
  // `id` lets clients resume with Last-Event-ID; `event` sets the named type.
  return `id: ${e.ts}\nevent: ${e.type}\ndata: ${JSON.stringify(e)}\n\n`;
}

export class StreamHub implements DurableObject {
  private sseWriters = new Set<WritableStreamDefaultWriter<Uint8Array>>();
  private encoder = new TextEncoder();

  constructor(private state: DurableObjectState, _env: Env) {}

  async fetch(req: Request): Promise<Response> {
    const url = new URL(req.url);
    if (url.pathname.endsWith("/ws")) return this.handleWebSocket(req);
    if (url.pathname.endsWith("/sse")) return this.handleSse();
    if (url.pathname.endsWith("/publish") && req.method === "POST") {
      const event = (await req.json()) as StreamEvent;
      this.broadcast(event);
      return new Response("ok");
    }
    return new Response("not found", { status: 404 });
  }

  private handleWebSocket(req: Request): Response {
    if (req.headers.get("Upgrade") !== "websocket") {
      return new Response("expected websocket", { status: 426 });
    }
    const pair = new WebSocketPair();
    const client = pair[0];
    const server = pair[1];
    // Hibernation API: the runtime can evict the DO between messages.
    this.state.acceptWebSocket(server);
    return new Response(null, { status: 101, webSocket: client });
  }

  // --- WebSocket hibernation handlers --------------------------------------
  webSocketMessage(ws: WebSocket, message: string | ArrayBuffer) {
    if (message === "ping") ws.send("pong");
  }
  webSocketClose(ws: WebSocket) {
    try {
      ws.close();
    } catch {
      /* already closed */
    }
  }

  private handleSse(): Response {
    const { readable, writable } = new TransformStream<Uint8Array, Uint8Array>();
    const writer = writable.getWriter();
    this.sseWriters.add(writer);
    void writer.write(
      this.encoder.encode(formatSSE({ type: "CONNECTED", data: {}, ts: Date.now() }))
    );
    return new Response(readable, {
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        Connection: "keep-alive",
        "Access-Control-Allow-Origin": "*"
      }
    });
  }

  private broadcast(event: StreamEvent): void {
    // WebSocket subscribers (survive hibernation).
    for (const ws of this.state.getWebSockets()) {
      try {
        ws.send(JSON.stringify(event));
      } catch {
        /* drop dead socket */
      }
    }
    // SSE subscribers (live for the lifetime of this DO instance).
    const chunk = this.encoder.encode(formatSSE(event));
    for (const writer of this.sseWriters) {
      writer.write(chunk).catch(() => this.sseWriters.delete(writer));
    }
  }
}
