import "server-only";

import { cache } from "react";

import { createClient } from "../generated/client/client";
import {
  intelligenceOverviewApiV1IntelligenceOverviewGet,
  orderTraceApiV1OrdersOrderIdTraceGet,
  overviewApiV1OverviewGet,
  type IntelligenceResponse,
  type OrderTraceRecord,
  type OverviewResponse,
  type WorkbenchResponse,
  workbenchApiV1WorkbenchGet,
} from "../generated/client";

const DEFAULT_API_URL = "http://127.0.0.1:8000";

function apiBaseUrl(): string {
  const configured = process.env.AEGISQUANT_API_URL ?? DEFAULT_API_URL;
  const parsed = new URL(configured);
  if (parsed.hostname !== "127.0.0.1" && parsed.hostname !== "localhost") {
    throw new Error("AegisQuant read API must remain on loopback.");
  }
  if (parsed.protocol !== "http:") {
    throw new Error("The local read API URL must use http on loopback.");
  }
  return parsed.origin;
}

function readClient() {
  return createClient({
    baseUrl: apiBaseUrl(),
    throwOnError: true,
  });
}

export async function getOverview(): Promise<OverviewResponse> {
  const result = await overviewApiV1OverviewGet({
    client: readClient(),
    cache: "no-store",
    throwOnError: true,
  });
  return result.data;
}

export async function getIntelligenceOverview(): Promise<IntelligenceResponse> {
  const result = await intelligenceOverviewApiV1IntelligenceOverviewGet({
    client: readClient(),
    cache: "no-store",
    throwOnError: true,
  });
  return result.data;
}

export const getWorkbench = cache(async (): Promise<WorkbenchResponse> => {
  const result = await workbenchApiV1WorkbenchGet({
    client: readClient(),
    cache: "no-store",
    throwOnError: true,
  });
  return result.data;
});

export const getOrderTrace = cache(async (orderId: string): Promise<OrderTraceRecord> => {
  const result = await orderTraceApiV1OrdersOrderIdTraceGet({
    client: readClient(),
    path: { order_id: orderId },
    cache: "no-store",
    throwOnError: true,
  });
  return result.data;
});
