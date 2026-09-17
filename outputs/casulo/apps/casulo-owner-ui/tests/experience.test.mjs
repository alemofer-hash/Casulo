import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";
import { buildDesignTape, createInitialState, createSyntheticEvent, reduceExperience, validateEventStructure } from "../src/experience.mjs";

test("the design tape exercises token streaming and evidenced jobs without a timer", async () => {
  const tape = await buildDesignTape();
  let state = createInitialState();
  for (const event of tape) state = reduceExperience(state, event);
  assert.equal(state.model, "READY");
  assert.equal(state.messages.length, 1);
  assert.equal(state.messages[0].complete, true);
  assert.match(state.messages[0].text, /algo que você possa abrir e usar/);
  assert.equal(state.jobs.length, 1);
  assert.equal(state.jobs[0].status, "COMPLETED");
  assert.equal(state.jobs[0].milestones.length, 2);
  assert.equal(state.form, "MATERIALIZED");
});

test("a duplicated event is rejected without mutating accepted state", async () => {
  const event = await createSyntheticEvent(1, "PRESENCE_READY", { text: "Aqui." });
  const state = reduceExperience(createInitialState(), event);
  assert.throws(() => reduceExperience(state, event), /duplicado/);
  assert.equal(state.seenEventIds.length, 1);
});

test("an assistant token requires a started turn and exact sequence", async () => {
  const token = await createSyntheticEvent(2, "ASSISTANT_TOKEN", { turn_id: "turn:x", sequence: 1, text: "oi" });
  assert.throws(() => reduceExperience(createInitialState(), token), /turno ativo/);
  const start = await createSyntheticEvent(1, "ASSISTANT_START", { turn_id: "turn:x" });
  const state = reduceExperience(createInitialState(), start);
  const skipped = await createSyntheticEvent(3, "ASSISTANT_TOKEN", { turn_id: "turn:x", sequence: 2, text: "fora" });
  assert.throws(() => reduceExperience(state, skipped), /fora de ordem/);
});

test("fabricated percentages and jobs without evidence are rejected", async () => {
  const fake = await createSyntheticEvent(1, "NOTICE", { text: "quase", progress_percent: 90 });
  assert.throws(() => validateEventStructure(fake), /fabricado/);
  const job = await createSyntheticEvent(2, "JOB_STARTED", { job_id: "job:x", summary: "começou", evidence_sha256: "0" });
  assert.throws(() => validateEventStructure(job), /evidência/);
  const zero = await createSyntheticEvent(3, "JOB_STARTED", { job_id: "job:zero", summary: "sem prova", evidence_sha256: "0".repeat(64) });
  assert.throws(() => validateEventStructure(zero), /evidência/);
});

test("late completion after cancellation cannot publish", async () => {
  const evidence = "e".repeat(64);
  let state = createInitialState();
  state = reduceExperience(state, await createSyntheticEvent(1, "JOB_STARTED", { job_id: "job:x", summary: "início", evidence_sha256: evidence }));
  state = reduceExperience(state, await createSyntheticEvent(2, "JOB_CANCELLED", { job_id: "job:x", summary: "cancelado", evidence_sha256: evidence }));
  const late = await createSyntheticEvent(3, "JOB_COMPLETED", { job_id: "job:x", summary: "tarde", evidence_sha256: evidence });
  assert.throws(() => reduceExperience(state, late), /terminal sem job ativo/);
  assert.equal(state.jobs[0].status, "CANCELLED");
});

test("the scene contract remains a pure projection of the shared wire contract", async () => {
  const scene = JSON.parse(await readFile(new URL("../../../schemas/product/stark-jobs-scene-v1.json", import.meta.url), "utf8"));
  assert.equal(scene.schema, "casulo.stark-jobs-scene/1.0");
  assert.equal(scene.allowed_inputs.wire_schema, "casulo.owner-ux-event/1.0");
  assert.equal(scene.authority.role, "PURE_PRESENTATION_PROJECTION");
  assert.equal(Object.values(scene.authority).includes(true), false);
  assert.equal(scene.synthetic_mode.runtime_evidence, false);
  for (const form of Object.values(scene.projection)) assert.ok(scene.forms.includes(form));
});

test("the shared Hosted/Native replay reaches the frozen scene", async () => {
  const fixture = JSON.parse(await readFile(new URL("../../../schemas/product/stark-jobs-conformance-v1.json", import.meta.url), "utf8"));
  let state = createInitialState();
  for (const raw of fixture.accepted) {
    state = reduceExperience(state, { schema: "casulo.owner-ux-event/1.0", ...raw });
  }
  assert.equal(fixture.runtime_evidence, false);
  assert.equal(state.presence, fixture.expected.presence);
  assert.equal(state.model, fixture.expected.model);
  assert.equal(state.form, fixture.expected.form);
  assert.equal(state.notice, fixture.expected.notice);
  assert.equal(state.activeTurn, fixture.expected.active_turn);
  assert.equal(state.nextTokenSequence, fixture.expected.next_token_sequence);
  assert.equal(state.messages.at(-1).text, fixture.expected.message_text);
  assert.equal(state.messages.at(-1).complete, fixture.expected.message_complete);
  assert.equal(state.jobs.at(-1).status, fixture.expected.job_status);
  assert.equal(state.jobs.at(-1).summary, fixture.expected.job_summary);
  assert.equal(state.jobs.at(-1).milestones.length, fixture.expected.milestone_count);
  assert.equal(state.jobs.length + state.jobs.at(-1).milestones.length + 1, fixture.expected.receipt_count);
});
