"use client";

import { useEffect, useRef, useState } from "react";

import type { StreamEvent, StreamSnapshotResponse } from "../generated/client";
import {
  applyStreamEvent,
  initialRealtimeState,
  recoverFromSnapshots,
  type RealtimeState,
} from "../lib/realtime";

const topics = ["account.summary", "risk.state", "intelligence.events"] as const;
const wsUrl = "ws://127.0.0.1:8000/ws/v1/stream";
const recoveryUrl = `http://127.0.0.1:8000/api/v1/stream/snapshot?topics=${topics.join(",")}`;

function isStreamEvent(value: unknown): value is StreamEvent {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<StreamEvent>;
  return typeof candidate.topic === "string" && typeof candidate.sequence === "number" && typeof candidate.message_type === "string";
}

export function RealtimeStatus() {
  const [state, setState] = useState<RealtimeState>(initialRealtimeState);
  const stateRef = useRef(state);
  useEffect(() => {
    let active = true;
    let reconnectTimer: ReturnType<typeof setTimeout> | undefined;
    let socket: WebSocket | undefined;
    const update = (next: RealtimeState) => {
      stateRef.current = next;
      setState(next);
    };
    const recover = async () => {
      try {
        const response = await fetch(recoveryUrl, { cache: "no-store" });
        if (!response.ok) throw new Error("snapshot recovery failed");
        const body = (await response.json()) as StreamSnapshotResponse;
        if (!Array.isArray(body.messages) || !body.messages.every(isStreamEvent)) {
          throw new Error("invalid recovery payload");
        }
        if (active) update(recoverFromSnapshots(stateRef.current, body.messages));
      } catch {
        if (active) update({ ...stateRef.current, status: "ERROR", recoveryRequired: true });
      }
    };
    const connect = () => {
      if (!active) return;
      update({ ...stateRef.current, status: "CONNECTING" });
      socket = new WebSocket(wsUrl);
      socket.addEventListener("open", () => {
        socket?.send(JSON.stringify({ action: "subscribe", schema_version: "1", topics }));
      });
      socket.addEventListener("message", (event) => {
        try {
          const message: unknown = JSON.parse(String(event.data));
          if (!isStreamEvent(message)) throw new Error("invalid stream payload");
          const next = applyStreamEvent(stateRef.current, message);
          update(next);
          if (next.recoveryRequired) void recover();
        } catch {
          update({ ...stateRef.current, status: "ERROR", recoveryRequired: true });
        }
      });
      socket.addEventListener("close", () => {
        if (!active) return;
        update({ ...stateRef.current, status: "DISCONNECTED" });
        reconnectTimer = setTimeout(connect, 1500);
      });
      socket.addEventListener("error", () => socket?.close());
    };
    connect();
    return () => {
      active = false;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      socket?.close();
    };
  }, []);
  return (
    <span className={`realtime-status realtime-${state.status.toLowerCase()}`} role="status">
      <span aria-hidden="true" />
      STREAM {state.status}{state.recoveryRequired ? " · REST RECOVERY" : ""}
    </span>
  );
}
