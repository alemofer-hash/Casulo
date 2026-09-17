import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import type { ExperienceEvent } from "./types";

export interface BridgeStatus {
  schema: string;
  wire_schema: string;
  contract_sha256: string;
  mode: "RUNTIME_VALIDATED" | "RUNTIME_CONFIGURED" | "WAITING_FOR_RUNTIME_STREAM" | "CONFIGURATION_REJECTED";
  stream_path: string | null;
  configuration_error: string | null;
  network_enabled: false;
  shell_enabled: false;
}

export function isTauriRuntime(): boolean {
  return typeof window !== "undefined" && Boolean(window.__TAURI_INTERNALS__);
}

export async function bridgeStatus(): Promise<BridgeStatus | null> {
  if (!isTauriRuntime()) return null;
  return invoke<BridgeStatus>("bridge_status");
}

export async function startBridge(): Promise<BridgeStatus | null> {
  if (!isTauriRuntime()) return null;
  return invoke<BridgeStatus>("start_bridge");
}

export async function subscribeToExperience(
  onEvent: (event: ExperienceEvent) => void,
): Promise<UnlistenFn> {
  if (!isTauriRuntime()) return () => undefined;
  return listen<{ source: "RUNTIME_VALIDATED"; event: ExperienceEvent }>(
    "casulo://experience",
    ({ payload }) => {
      if (payload.source !== "RUNTIME_VALIDATED") return;
      onEvent(payload.event);
    },
  );
}

export async function subscribeToBridgeRejections(
  onRejection: (reason: string) => void,
): Promise<UnlistenFn> {
  if (!isTauriRuntime()) return () => undefined;
  return listen<{ source: "RUNTIME_REJECTED"; line_number: number; reason: string }>(
    "casulo://bridge-rejection",
    ({ payload }) => onRejection(payload.reason),
  );
}
