import type { ExperienceEvent, ExperienceState } from "./types";

export const WIRE_SCHEMA: string;
export const CONTRACT_SCHEMA: string;
export const MAX_EVENT_BYTES: number;
export const EVENT_KINDS: readonly string[];
export function createInitialState(): ExperienceState;
export function validateEventStructure(input: unknown): ExperienceEvent;
export function reduceExperience(state: ExperienceState, input: unknown): ExperienceState;
export function createSyntheticEvent(index: number, kind: string, payload: Record<string, unknown>): Promise<ExperienceEvent>;
export function buildDesignTape(): Promise<ExperienceEvent[]>;
