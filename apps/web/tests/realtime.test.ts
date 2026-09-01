import { describe, expect, it } from "vitest";

import type { StreamEvent } from "../src/generated/client";
import { applyStreamEvent, initialRealtimeState, recoverFromSnapshots } from "../src/lib/realtime";

const snapshot: StreamEvent = {
  schema_version: "1",
  message_type: "snapshot",
  topic: "risk.state",
  event_id: "snapshot:risk:4",
  event_time: "2026-09-01T21:50:00Z",
  server_time: "2026-09-01T21:50:01Z",
  sequence: 4,
  payload: { records: [] },
};

describe("realtime sequence recovery", () => {
  it("stops applying increments when a sequence gap appears", () => {
    const ready = applyStreamEvent(initialRealtimeState, snapshot);
    const gap = applyStreamEvent(ready, {
      ...snapshot,
      message_type: "increment",
      event_id: "increment:risk:6",
      sequence: 6,
    });
    expect(gap.status).toBe("DISCONNECTED");
    expect(gap.recoveryRequired).toBe(true);
    expect(gap.sequences["risk.state"]).toBe(4);
  });

  it("resumes only after a REST snapshot", () => {
    const disconnected = { ...initialRealtimeState, status: "DISCONNECTED" as const, recoveryRequired: true };
    const recovered = recoverFromSnapshots(disconnected, [snapshot]);
    expect(recovered.status).toBe("LIVE");
    expect(recovered.recoveryRequired).toBe(false);
    expect(recovered.sequences["risk.state"]).toBe(4);
  });
});
