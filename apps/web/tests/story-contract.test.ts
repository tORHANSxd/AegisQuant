import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

const components = [
  "MetricTile", "MetricDelta", "StatusBadge", "FreshnessIndicator", "RiskStateBanner",
  "EnvironmentBadge", "EquityChart", "DrawdownChart", "CandlestickTradeChart",
  "AttributionWaterfall", "PnLHeatmap", "ExposureTreemap", "CorrelationMatrix",
  "OrderTimeline", "SignalDecisionTrace", "DataQualityGrid", "ModelCalibrationChart",
  "IncidentTimeline", "VirtualDataTable", "FilterBar", "CommandPalette", "EmptyState",
  "ErrorBoundaryPanel", "ExportMenu",
] as const;
const stories = [
  "Normal", "Loading", "Empty", "Stale", "Degraded", "Disconnected", "Error",
  "PermissionDenied", "Narrow", "Accessible",
] as const;

describe("Storybook complete state gallery", () => {
  it("renders every taskbook common component", () => {
    const gallery = readFileSync(resolve("src/components/component-gallery.tsx"), "utf8");
    for (const component of components) expect(gallery).toContain(`<GalleryItem title="${component}">`);
  });

  it("defines every required state, narrow, and accessibility story", () => {
    const source = readFileSync(resolve("src/components/component-gallery.stories.tsx"), "utf8");
    for (const story of stories) expect(source).toContain(`export const ${story}: Story`);
  });
});
