"use strict";
(() => {
  const record = document.querySelector("#voice-record");
  const stop = document.querySelector("#voice-stop");
  const stateNode = document.querySelector("#voice-state");
  const output = document.querySelector("#voice-output");
  const privateRoute = document.querySelector("#private-audio");
  let state = "IDLE", stream = null, context = null, processor = null;
  let frames = [], samples = 0, sampleRate = 16000, timer = null;
  let turn = null, objectUrl = null, epoch = 0;

  function setState(next) {
    state = next;
    stateNode.textContent = next;
    stop.disabled = next === "IDLE";
    record.disabled = !["IDLE", "RECORDING"].includes(next);
    record.textContent = next === "RECORDING" ? "Enviar gravação" : "Falar com Cleo";
    document.querySelector("#send").disabled = next !== "IDLE";
  }
  async function stopMic() {
    clearTimeout(timer);
    if (processor) { processor.onaudioprocess = null; processor.disconnect(); processor = null; }
    if (stream) { stream.getTracks().forEach(track => track.stop()); stream = null; }
    if (context) { await context.close(); context = null; }
  }
  function dropAudio() {
    output.pause(); output.removeAttribute("src"); output.load(); output.hidden = true;
    if (objectUrl) URL.revokeObjectURL(objectUrl);
    objectUrl = null;
  }
  async function cancel() {
    epoch++;
    await stopMic(); frames = []; samples = 0; dropAudio();
    const oldTurn = turn; turn = null;
    if (oldTurn) {
      try { await api(`/v1/voice/${oldTurn}/cancel`, {method: "POST", body: "{}"}); } catch (_) {}
    }
    setState("IDLE");
  }
  function wav() {
    const source = new Float32Array(samples); let offset = 0;
    for (const frame of frames) { source.set(frame, offset); offset += frame.length; }
    const count = Math.min(320000, Math.floor(samples * 16000 / sampleRate));
    const raw = new ArrayBuffer(44 + count * 2), view = new DataView(raw);
    const ascii = (at, text) => { for (let i = 0; i < text.length; i++) view.setUint8(at+i, text.charCodeAt(i)); };
    ascii(0, "RIFF"); view.setUint32(4, 36+count*2, true); ascii(8, "WAVEfmt ");
    view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
    view.setUint32(24, 16000, true); view.setUint32(28, 32000, true);
    view.setUint16(32, 2, true); view.setUint16(34, 16, true); ascii(36, "data");
    view.setUint32(40, count*2, true);
    for (let i = 0; i < count; i++) {
      const start = Math.floor(i*sampleRate/16000), end = Math.max(start+1, Math.floor((i+1)*sampleRate/16000));
      let sum = 0; for (let j = start; j < end && j < source.length; j++) sum += source[j];
      const value = Math.max(-1, Math.min(1, sum/(end-start)));
      view.setInt16(44+i*2, Math.round(value * (value < 0 ? 32768 : 32767)), true);
    }
    const bytes = new Uint8Array(raw); let binary = "";
    for (let i = 0; i < bytes.length; i += 8192) binary += String.fromCharCode(...bytes.subarray(i, i+8192));
    return btoa(binary);
  }
  async function sendRecording() {
    const thisEpoch = epoch;
    await stopMic();
    if (thisEpoch !== epoch) return;
    try {
      if (!privateRoute.checked) throw new Error("Confirme a rota privada antes de enviar.");
      const audio = wav(); frames = []; samples = 0; setState("TRANSCRIBING");
      const accepted = await (await api("/v1/voice", {method:"POST", body:JSON.stringify({wav_base64:audio})})).json();
      if (thisEpoch !== epoch) {
        await api(`/v1/voice/${accepted.turn_id}/cancel`, {method:"POST",body:"{}"}); return;
      }
      turn = accepted.turn_id;
      const deadline = Date.now()+180000;
      while (thisEpoch === epoch) {
        if (Date.now() > deadline) throw new Error("Tempo limite de voz.");
        const status = await (await api(`/v1/voice/${turn}`)).json();
        if (thisEpoch !== epoch) return;
        setState(status.state);
        if (status.register) stateNode.textContent += ` · ${status.register}`;
        if (["FAILED", "CANCELLED"].includes(status.result)) throw new Error(status.result);
        if (status.result === "READY_FOR_PLAYBACK") {
          const blob = await (await api(`/v1/voice/${turn}/audio`)).blob();
          if (thisEpoch !== epoch) return;
          if (blob.size > 1920128) throw new Error("Áudio excede o limite.");
          objectUrl = URL.createObjectURL(blob); output.src = objectUrl; output.hidden = false;
          try { await output.play(); } catch (_) { stateNode.textContent = "PLAYING · pressione reproduzir"; }
          // A revoked session/route must also stop already-delivered playback.
          const playbackTurn = turn;
          (async () => {
            while (turn === playbackTurn && thisEpoch === epoch) {
              await new Promise(resolve => setTimeout(resolve, 250));
              if (turn !== playbackTurn || thisEpoch !== epoch) return;
              try {
                const current = await (await api(`/v1/voice/${playbackTurn}`)).json();
                if (current.result !== "READY_FOR_PLAYBACK") { await cancel(); return; }
              } catch (_) { await cancel(); return; }
            }
          })();
          return;
        }
        await new Promise(resolve => setTimeout(resolve, 150));
      }
    } catch (error) { await cancel(); stateNode.textContent = `IDLE · ${error.message}`; }
  }
  record.addEventListener("click", async () => {
    if (state === "RECORDING") return sendRecording();
    if (state !== "IDLE" || activeJob || !privateRoute.checked) {
      stateNode.textContent = "Confirme a saída privada e conclua a conversa atual."; return;
    }
    const thisEpoch = ++epoch;
    try {
      await api("/v1/session");
      const acquired = await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true},video:false});
      if (thisEpoch !== epoch) { acquired.getTracks().forEach(t => t.stop()); return; }
      stream = acquired; context = new AudioContext(); await context.resume();
      sampleRate = context.sampleRate; frames = []; samples = 0;
      const source = context.createMediaStreamSource(stream);
      processor = context.createScriptProcessor(4096,1,1);
      processor.onaudioprocess = event => {
        if (state !== "RECORDING") return;
        const remaining = Math.floor(sampleRate*20)-samples;
        if (remaining <= 0) return;
        const data = event.inputBuffer.getChannelData(0).slice(0, remaining);
        frames.push(data); samples += data.length;
      };
      source.connect(processor); processor.connect(context.destination);
      setState("RECORDING"); timer = setTimeout(sendRecording, 20000);
    } catch (error) { await cancel(); stateNode.textContent = `IDLE · ${error.message}`; }
  });
  stop.addEventListener("click", cancel);
  output.addEventListener("ended", async () => {
    const completed = turn; turn = null; dropAudio();
    try { if (completed) await api(`/v1/voice/${completed}/finished`, {method:"POST",body:"{}"}); }
    finally { setState("IDLE"); }
  });
  privateRoute.addEventListener("change", async () => {
    if (privateRoute.checked) return;
    await cancel();
    try { await api("/v1/voice/private-route-lost", {method:"POST",body:"{}"}); } catch (_) {}
  });
  document.querySelector("#logout").addEventListener("click", cancel);
  document.addEventListener("visibilitychange", () => { if (document.hidden) cancel(); });
  window.addEventListener("pagehide", () => {
    if (stream) stream.getTracks().forEach(track => track.stop());
    dropAudio();
    if (turn) fetch(`/v1/voice/${turn}/cancel`, {method:"POST",credentials:"same-origin",keepalive:true,
      headers:{"Content-Type":"application/json","X-Casulo-CSRF":csrf()},body:"{}"}).catch(()=>{});
  });
})();
