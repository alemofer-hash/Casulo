export interface ExperienceEvent {
  schema: string;
  event_id: string;
  kind: string;
  payload: Record<string, unknown>;
  source_event_ids: string[];
  occurred_at: string;
  event_hash: string;
}

export interface ExperienceState {
  presence: boolean;
  model: string;
  form: string;
  notice: string;
  activeTurn: string | null;
  nextTokenSequence: number;
  messages: Array<{ id: string; text: string; complete: boolean }>;
  jobs: Array<{
    id: string;
    status: string;
    summary: string;
    evidence: string;
    milestones: Array<{ summary: string; evidence: string }>;
  }>;
  seenEventIds: string[];
  lastEvent: ExperienceEvent | null;
  recoverableError: string | null;
}

export interface BridgeStatusView {
  schema: string;
  wire_schema: string;
  contract_sha256: string;
  mode: string;
  stream_path: string | null;
  configuration_error: string | null;
  network_enabled: boolean;
  shell_enabled: boolean;
}
