"use strict";
// Isolated automated test browser, not a controller for the user's browser.
// Credentials arrive through stdin only and are never written to artifacts.
const fs = require("node:fs");
const { chromium } = require("playwright");

(async () => {
  const input = JSON.parse(fs.readFileSync(0, "utf8"));
  const errors = [], requests = [], observations = [];
  const browser = await chromium.launch({headless: true, chromiumSandbox: true, args: [
    "--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream", "--mute-audio",
    `--use-file-for-fake-audio-capture=${input.fixture}`,
    // The runner first verifies this server using its CA. Pin only that SPKI in
    // the disposable test browser; no OS trust changes or global TLS bypass.
    `--ignore-certificate-errors-spki-list=${input.serverSPKI}`
  ]});
  try {
    const context = await browser.newContext({viewport:{width:1100,height:1000},
      permissions:["microphone"], serviceWorkers:"block"});
    await context.route("**/*", route => {
      const url = route.request().url();
      if (url.startsWith(input.base + "/")) route.continue(); else route.abort();
    });
    await context.addCookies(input.cookies);
    const page = await context.newPage();
    page.on("pageerror", error => errors.push(error.name));
    page.on("request", request => requests.push({method:request.method(),path:new URL(request.url()).pathname}));
    await page.addInitScript(() => {
      window.__voiceTracks = [];
      const original = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
      navigator.mediaDevices.getUserMedia = async constraints => {
        const stream = await original(constraints);
        window.__voiceTracks.push(...stream.getTracks());
        return stream;
      };
    });
    await page.goto(input.base, {waitUntil:"domcontentloaded"});
    await page.locator("#chat").waitFor({state:"visible"});
    if (await page.evaluate(() => window.__voiceTracks.length) !== 0) throw Error("unexpected initial microphone");
    await page.locator("#private-audio").check();
    await page.locator("#voice-record").click();
    await page.waitForFunction(() => document.querySelector("#voice-state").textContent === "RECORDING");
    await page.waitForTimeout(500);
    await page.locator("#voice-stop").click();
    await page.waitForFunction(() => document.querySelector("#voice-state").textContent === "IDLE");
    if (!(await page.evaluate(() => window.__voiceTracks.every(track=>track.readyState==="ended")))) throw Error("mic leak on cancel");
    observations.push({recording_cancel:"PASS", no_upload_before_send:!requests.some(r=>r.path==="/v1/voice")});
    await page.locator("#voice-record").click();
    await page.waitForFunction(() => document.querySelector("#voice-state").textContent === "RECORDING");
    await page.waitForTimeout(4300);
    await page.locator("#voice-record").click();
    await page.waitForFunction(() => document.querySelector("#voice-state").textContent !== "RECORDING");
    if (!(await page.evaluate(() => window.__voiceTracks.every(track=>track.readyState==="ended")))) throw Error("mic active after submission");
    await page.waitForFunction(() => !document.querySelector("#voice-output").hidden, null, {timeout:120000});
    await page.screenshot({path:input.screenshot});
    const playing = await page.locator("#voice-state").textContent();
    if (!playing.startsWith("PLAYING")) throw Error("not in PLAYING");
    if (!(await page.locator("#voice-record").isDisabled())) throw Error("ASR allowed while playing");
    const metadata = await page.locator("#voice-output").evaluate(audio=>({duration:audio.duration,readyState:audio.readyState}));
    await page.waitForFunction(() => document.querySelector("#voice-state").textContent === "IDLE", null, {timeout:30000});
    observations.push({completed_to_idle:"PASS",mic_tracks_ended:true,half_duplex:true,audio:metadata});
    if (errors.length) throw Error("browser page errors");
    fs.writeFileSync(input.receipt, JSON.stringify({status:"PASS", browser:browser.version(),
      playwright:require("playwright/package.json").version, test_microphone:"neutral WAV fake device",
      physical_microphone_claim:false, physical_speaker_claim:false,
      tls:"CA verified before launch; disposable browser pins exact server SPKI",
      os_trust_changed:false, requests, observations, errors},null,2)+"\n");
    console.log("PWA_BROWSER_PASS");
  } catch (error) {
    fs.writeFileSync(input.receipt, JSON.stringify({status:"FAIL",error:error.message,
      requests, observations, errors},null,2)+"\n");
    throw error;
  } finally { await browser.close(); }
})().catch(error=>{console.error("PWA_BROWSER_FAILED",error.message);process.exitCode=1;});
