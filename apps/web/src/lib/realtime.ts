import type { StreamEvent } from "../generated/client";

export interface RealtimeState {
  status: "CONNECTING" | "LIVE" | "DISCONNECTED" | "ERROR";
  sequences: Record<string, number>;
  recoveryRequired: boolean;
  lastEventAt?: string;
}

export const initialRealtimeState: RealtimeState = {
  status: "CONNECTING",
  sequences: {},
  recoveryRequired: false,
};

export function applyStreamEvent(state: RealtimeState, event: StreamEvent): RealtimeState {
  if (event.message_type === "heartbeat") {
    return { ...state, status: "LIVE", lastEventAt: event.server_time };
  }
  if (event.message_type === "snapshot") {
    return {
      ...state,
      status: "LIVE",
      sequences: { ...state.sequences, [event.topic]: event.sequence },
      recoveryRequired: false,
      lastEventAt: event.server_time,
    };
  }
  const previous = state.sequences[event.topic];
  if (previous === undefined || event.sequence !== previous + 1) {
    return {
      ...state,
      status: "DISCONNECTED",
      recoveryRequired: true,
      lastEventAt: event.server_time,
    };
  }
  return {
    ...state,
    status: "LIVE",
    sequences: { ...state.sequences, [event.topic]: event.sequence },
    lastEventAt: event.server_time,
  };
}

export function recoverFromSnapshots(
  state: RealtimeState,
  snapshots: StreamEvent[],
): RealtimeState {
  const sequences = { ...state.sequences };
  let lastEventAt = state.lastEventAt;
  for (const snapshot of snapshots) {
    if (snapshot.message_type !== "snapshot") {
      throw new Error("Recovery response must contain snapshots only.");
    }
    sequences[snapshot.topic] = snapshot.sequence;
    lastEventAt = snapshot.server_time;
  }
  return { status: "LIVE", sequences, recoveryRequired: false, lastEventAt };
}
