from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import queue
import subprocess
import sys
import threading
import time
import uuid
from datetime import UTC, datetime
from importlib.machinery import SourceFileLoader
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from casulo.product.discovery_session import DiscoverySessionRecorder
from casulo.product.discovery_transport import DIALOGUE_TRANSPORTS, IncrementalLineFramer
from casulo.product.pleasant_interface import UxEvent, UxEventKind, UxStreamValidator, decode_ux_event


VOICE_CONSENT = "AUTORIZO VOZ LOCAL POR 8 SEGUNDOS SEM SALVAR PCM"
COMMANDS = frozenset({":criar", ":universos", ":rota", ":memoria", ":nota", ":snapshot", ":restore", ":export", ":cancelar", ":sair"})


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_sealed_window(release: Path):
    source = release / "OWNER_VM/app/tools/human_proof_window.pyw"
    loader = SourceFileLoader("casulo_t85_sealed_human_window_m1", str(source))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    if spec is None:
        raise RuntimeError("janela owner selada nao carregavel")
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module.HumanProofWindow


def default_session_root() -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Casulo/monday-discovery/2026-08-17" / f"session-{stamp}-{uuid.uuid4().hex[:8]}"


def make_window(base, *, dialogue_transport: str = "vm-bridge"):
    if dialogue_transport not in DIALOGUE_TRANSPORTS:
        raise ValueError("transporte de diálogo fora da allowlist")

    class MondayDiscoveryWindow(base):
        def __init__(self, release_root: Path, session_root: Path) -> None:
            self.dialogue_transport = dialogue_transport
            self.discovery = DiscoverySessionRecorder(
                session_root,
                session_id=f"m1:{session_root.name}",
                release_manifest_sha256=sha256(release_root / "MANIFEST.json"),
            )
            self.voice_authorized = False
            self.turn_counter = 0
            self.last_answered_turn = 0
            self._suppressed_tts_recorded = False
            self._discovery_finalized = False
            self._process_observer_done = threading.Event()
            self._ux_validator = UxStreamValidator()
            self._assistant_buffers: dict[str, list[str]] = {}
            self._pending_inputs: list[str] = []
            self._stdin_lock = threading.RLock()
            self._model_ready = False
            self._orb_started_ns = time.monotonic_ns()
            self.discovery.record_automated("SESSION_OPENED", {"mode": "M1_DISCOVERY", "voice": "LOCKED_PENDING_LITERAL_CONSENT"})
            super().__init__(release_root)
            if self.dialogue_transport == "host-direct":
                # The sealed UI remains the visual base, while the opt-in M1
                # fast profile executes current checkout code.  This profile is
                # evidence for UX discovery, never a replacement release seal.
                self.repo = ROOT
            self.root.title("Casulo Owner · descoberta M1")
            if self.dialogue_transport == "host-direct":
                self._install_arc9_surface()
                self.status.set("Estou aqui · o motor local está acordando")
                self.append("Estou aqui. Pode começar a escrever enquanto o motor termina de acordar.\n", "presence")
            else:
                self.status.set("Carregando presença real · voz bloqueada até consentimento literal")
                self.append(f"[M1 append-only: {session_root}]\n")

        def _install_arc9_surface(self) -> None:
            tk = self.tk
            for child in self.root.winfo_children():
                child.destroy()
            self.root.title("Casulo")
            self.root.geometry("1120x780")
            self.root.minsize(820, 620)
            self.root.configure(bg="#05080e")

            header = tk.Frame(self.root, bg="#05080e")
            header.pack(fill="x", padx=42, pady=(28, 4))
            tk.Label(header, text="CASULO", bg="#05080e", fg="#d9953f", font=("Segoe UI Semibold", 11)).pack(side="left")
            tk.Label(header, text="owner · local", bg="#05080e", fg="#64748b", font=("Segoe UI", 9)).pack(side="right")

            self.orb = tk.Canvas(self.root, height=116, bg="#05080e", highlightthickness=0)
            self.orb.pack(fill="x", padx=42)
            self._orb_rings = [
                self.orb.create_oval(0, 0, 0, 0, outline="#142033", width=1),
                self.orb.create_oval(0, 0, 0, 0, outline="#24405f", width=1),
                self.orb.create_oval(0, 0, 0, 0, fill="#d9953f", outline=""),
            ]
            self.root.after(80, self._animate_orb)

            tk.Label(self.root, textvariable=self.status, bg="#05080e", fg="#8fa6bf", font=("Segoe UI", 10)).pack(anchor="center", pady=(0, 14))
            self.log = tk.Text(
                self.root, bg="#080d16", fg="#e8e5dc", insertbackground="#d9953f",
                relief="flat", borderwidth=0, wrap="word", font=("Segoe UI", 12),
                state="disabled", padx=26, pady=22, spacing1=2, spacing3=8,
            )
            self.log.pack(fill="both", expand=True, padx=42, pady=(0, 14))
            self.log.tag_configure("presence", foreground="#91a9c3", font=("Segoe UI", 11, "italic"))
            self.log.tag_configure("assistant-label", foreground="#d9953f", font=("Segoe UI Semibold", 9))
            self.log.tag_configure("assistant", foreground="#f2efe7", font=("Segoe UI", 12))
            self.log.tag_configure("user-label", foreground="#71849b", font=("Segoe UI Semibold", 9))
            self.log.tag_configure("user", foreground="#c9d3df", font=("Segoe UI", 12))
            self.log.tag_configure("job", foreground="#7fa6cf", font=("Segoe UI", 10, "italic"))
            self.log.tag_configure("error", foreground="#e08c83", font=("Segoe UI", 10))
            self.log.tag_configure("system", foreground="#64748b", font=("Segoe UI", 9))

            row = tk.Frame(self.root, bg="#05080e")
            row.pack(fill="x", padx=42, pady=(0, 8))
            self.entry = tk.Entry(
                row, bg="#0d1623", fg="#f2efe7", insertbackground="#d9953f",
                relief="flat", borderwidth=0, font=("Segoe UI", 12),
            )
            self.entry.pack(side="left", fill="x", expand=True, ipady=10)
            self.entry.bind("<Return>", lambda _event: self.send())
            self.send_button = tk.Button(
                row, text="Enviar", command=self.send, state="normal",
                bg="#d9953f", fg="#090b10", activebackground="#efb45f", relief="flat",
                padx=18, pady=8, font=("Segoe UI Semibold", 10),
            )
            self.send_button.pack(side="left", padx=(10, 0))

            actions = tk.Frame(self.root, bg="#05080e")
            actions.pack(fill="x", padx=42, pady=(0, 22))
            tk.Button(actions, text="Criar algo", command=lambda: self.send(":criar"), bg="#101a29", fg="#e8e5dc", relief="flat", padx=14).pack(side="left")
            tk.Button(actions, text="Falar", command=self.capture_voice, bg="#101a29", fg="#e8e5dc", relief="flat", padx=14).pack(side="left", padx=(8, 0))
            advanced = tk.Menubutton(actions, text="Mais", bg="#05080e", fg="#71849b", activebackground="#101a29", relief="flat")
            menu = tk.Menu(advanced, tearoff=False)
            for label, command in (("Universos", ":universos"), ("Rota", ":rota"), ("Memória", ":memoria"), ("Snapshot", ":snapshot"), ("Restore", ":restore"), ("Exportar", ":export"), ("Cancelar criação", ":cancelar")):
                menu.add_command(label=label, command=lambda value=command: self.send(value))
            menu.add_separator()
            menu.add_command(label="Registrar nota", command=self.note)
            advanced.configure(menu=menu)
            advanced.pack(side="left", padx=(10, 0))
            tk.Button(actions, text="Sair", command=self.close, bg="#05080e", fg="#64748b", relief="flat").pack(side="right")
            self.entry.focus_set()

        def _animate_orb(self) -> None:
            if not hasattr(self, "orb") or not self.orb.winfo_exists():
                return
            width = max(200, self.orb.winfo_width())
            center_x, center_y = width / 2, 57
            elapsed = (time.monotonic_ns() - self._orb_started_ns) / 1_000_000_000
            pulse = (math.sin(elapsed * (2.4 if self._model_ready else 1.2)) + 1) / 2
            radii = (48 + pulse * 5, 32 + pulse * 4, 9 + pulse * 2)
            for item, radius in zip(self._orb_rings, radii):
                self.orb.coords(item, center_x - radius, center_y - radius, center_x + radius, center_y + radius)
            self.orb.itemconfigure(self._orb_rings[2], fill="#d9953f" if self._model_ready else "#375d82")
            self.root.after(80, self._animate_orb)

        def append(self, text: str, tag: str = "system") -> None:
            self.log.configure(state="normal")
            self.log.insert("end", text, tag)
            self.log.see("end")
            self.log.configure(state="disabled")

        def command(self) -> list[str]:
            if self.dialogue_transport != "host-direct":
                return super().command()
            cache = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Casulo/cache/generative"
            vm_root = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Casulo/t85-human-proof/owner-vm"
            feedback = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Casulo/t85-owner-human-proof-feedback"
            return [
                sys.executable,
                "-u",
                str(ROOT / "tools/casulo_semantic_multiverse_vm_inspect.py"),
                "--source-image",
                str(self.release_root / "OWNER_VM/casulo-native-generative-interactive.img"),
                "--candidate",
                str(ROOT / "release/generative-candidates/qwen3-4b-q4km-llamacpp-b10362.json"),
                "--cache",
                str(cache),
                "--vm-root",
                str(vm_root),
                "--feedback-root",
                str(feedback),
                "--repo",
                str(ROOT),
                "--threads",
                "4",
                "--dialogue-transport",
                "host-direct",
                "--ui-mode",
                "arc-stream",
            ]

        def start_session(self) -> None:
            run_repo = ROOT if self.dialogue_transport == "host-direct" else self.repo
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            env["PYTHONPATH"] = os.pathsep.join([str(run_repo / "src"), str(run_repo / "private/casulo-owner/src")])
            self.discovery.record_automated(
                "OWNER_PROCESS_START_REQUESTED",
                {
                    "shell": False,
                    "network": "DENIED_BY_PROFILE",
                    "dialogue_transport": self.dialogue_transport.upper().replace("-", "_"),
                    "vm_creation_gate_preserved": True,
                },
            )
            try:
                self.process = subprocess.Popen(
                    self.command(),
                    cwd=run_repo,
                    env=env,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                    shell=False,
                )
                self.discovery.record_automated("OWNER_PROCESS_SPAWNED", {"pid": self.process.pid})
                assert self.process.stdout is not None
                with self._stdin_lock:
                    pending, self._pending_inputs = tuple(self._pending_inputs), []
                    for queued in pending:
                        assert self.process.stdin is not None
                        self.process.stdin.write(queued + "\n")
                    if pending:
                        self.process.stdin.flush()
                first_output = True
                if self.dialogue_transport == "host-direct":
                    for line in iter(self.process.stdout.readline, ""):
                        if first_output:
                            first_output = False
                            self.discovery.record_automated("FIRST_PROCESS_OUTPUT", {"line_sha256": hashlib.sha256(line.encode("utf-8")).hexdigest(), "chars": len(line), "streaming_visible": True, "protocol": "ARC_JSONL"})
                        try:
                            event = decode_ux_event(line.rstrip("\r\n"))
                        except ValueError as error:
                            self.discovery.record_automated("COMPONENT_FAILURE", {"component": "UX_EVENT_DECODER", "error_type": type(error).__name__})
                            self.output.put("\nA interface recusou um evento inválido; a sessão continua.\n")
                            continue
                        if event is not None:
                            try:
                                self._ux_validator.accept(event)
                            except ValueError as error:
                                self.discovery.record_automated("COMPONENT_FAILURE", {"component": "UX_EVENT_VALIDATOR", "error_type": type(error).__name__})
                                continue
                            self._observe_ux_event(event)
                            self.output.put(event)
                        else:
                            self._observe_output(line)
                else:
                    for line in iter(self.process.stdout.readline, ""):
                        if first_output:
                            first_output = False
                            self.discovery.record_automated("FIRST_PROCESS_OUTPUT", {"line_sha256": hashlib.sha256(line.encode("utf-8")).hexdigest(), "chars": len(line)})
                        self._observe_output(line)
                        self.output.put(line)
                code = self.process.wait()
                self.discovery.record_automated("OWNER_PROCESS_EXITED", {"exit_code": code})
                self.output.put(f"\n[Sessão owner encerrou com código {code}; a telemetria M1 permanece.]\n")
                self.root.after(0, lambda: self.status.set("Sessão owner encerrada · notas e eventos preservados"))
            except Exception as error:
                self.discovery.record_automated(
                    "COMPONENT_FAILURE",
                    {"component": "OWNER_PROCESS", "error_type": type(error).__name__, "message_sha256": hashlib.sha256(str(error).encode("utf-8", "replace")).hexdigest()},
                )
                self.output.put("\n[Owner não iniciou; estado anterior preservado. Use Nota para registrar contexto.]\n")
                self.root.after(0, lambda: self.status.set("Falha recuperável antes da presença"))
            finally:
                self._process_observer_done.set()

        def _observe_ux_event(self, event: UxEvent) -> None:
            safe = {"kind": event.kind.value, "event_hash": event.event_hash}
            if event.kind is UxEventKind.PRESENCE_READY:
                self.discovery.record_automated("PRESENCE_READY", safe)
            elif event.kind is UxEventKind.MODEL_LOADING:
                self.discovery.record_automated("MODEL_LOADING", safe)
            elif event.kind is UxEventKind.MODEL_READY:
                self.discovery.record_automated("MODEL_READY", safe)
            elif event.kind is UxEventKind.ASSISTANT_TOKEN and int(event.payload["sequence"]) == 1:
                self.discovery.record_automated("FIRST_RESPONSE_FRAGMENT", {**safe, "turn": self.turn_counter})
            elif event.kind is UxEventKind.ASSISTANT_END:
                status = str(event.payload.get("status", "COMPLETED"))
                receipt = {
                    **safe,
                    "turn": self.turn_counter,
                    "response_sha256": str(event.payload.get("response_sha256", "")),
                    "response_chars": int(event.payload.get("response_chars", 0)),
                    "finish_reason": str(event.payload.get("finish_reason", "unknown")),
                    "status": status,
                }
                if status == "COMPLETED":
                    self.last_answered_turn = self.turn_counter
                    self.discovery.record_automated("SUBSTANTIVE_RESPONSE", receipt)
                else:
                    self.discovery.record_automated("RECOVERABLE_FAILURE", receipt)
            elif event.kind.value.startswith("JOB_"):
                self.discovery.record_automated(
                    event.kind.value,
                    {**safe, "job_id": str(event.payload["job_id"]), "evidence_sha256": str(event.payload["evidence_sha256"]), "sequence": int(event.payload["sequence"])},
                )

        def _observe_output(self, line: str) -> None:
            normalized = " ".join(line.split())
            folded = normalized.casefold()
            fingerprint = hashlib.sha256(line.encode("utf-8", "replace")).hexdigest()
            if normalized.startswith("Casulo owner ·"):
                self.discovery.record_automated("PRESENCE_READY", {"output_sha256": fingerprint})
                if self.dialogue_transport == "host-direct":
                    self.root.after(0, lambda: self.status.set("Presença iniciada · carregando modelo local"))
                else:
                    self.root.after(0, lambda: self.send_button.configure(state="normal"))
                    self.root.after(0, lambda: self.status.set("Presença real disponível · texto ativo · voz ainda bloqueada"))
            if normalized.startswith("Catálogo retomado:"):
                self.discovery.record_automated("REBOOT_RECALL_STATUS", {"output_sha256": fingerprint, "chars": len(normalized)})
            if normalized == "Casulo status · MODEL_LOADING":
                self.discovery.record_automated("MODEL_LOADING", {"output_sha256": fingerprint})
                self.root.after(0, lambda: self.status.set("Carregando modelo local · interface permanece responsiva"))
            if normalized == "Casulo status · MODEL_READY":
                self.discovery.record_automated("MODEL_READY", {"output_sha256": fingerprint})
                self.root.after(0, lambda: self.send_button.configure(state="normal"))
                self.root.after(0, lambda: self.status.set("Presença local pronta · resposta incremental ativa"))
            if normalized.startswith("Casulo status · RESPONSE_LIMIT_REACHED"):
                self.discovery.record_automated(
                    "RESPONSE_LIMIT_REACHED",
                    {"finish_reason": "length", "response_preserved": True},
                )
                self.root.after(0, lambda: self.status.set("Resposta preservada no limite · peça para continuar"))
            if normalized.startswith("Perfil de interação: DISCOVERY_FAST_HOST_DIALOGUE"):
                self.discovery.record_automated(
                    "DISCOVERY_FAST_PATH_ACTIVE",
                    {"dialogue_vm_boot_per_turn": False, "creation_vm_gate_preserved": True, "release_proof": False},
                )
            if normalized.startswith("Casulo ›") and normalized.removeprefix("Casulo ›").strip():
                self.last_answered_turn = self.turn_counter
                self.discovery.record_automated(
                    "SUBSTANTIVE_RESPONSE",
                    {"turn": self.turn_counter, "response_sha256": fingerprint, "response_chars": len(normalized.removeprefix("Casulo ›").strip())},
                )
                spoken = normalized.removeprefix("Casulo ›").strip()
                self.root.after(0, lambda value=spoken: self.speak_response(value))
            if normalized.startswith("Artifact materializado:"):
                artifact = normalized.split(":", 1)[1].strip()
                self.discovery.record_automated("MATERIALIZATION_REPORTED", {"artifact_path": artifact})
            if normalized.startswith("Universos:"):
                self.discovery.record_automated("SEMANTIC_ROUTE_REPORTED", {"route_sha256": fingerprint, "chars": len(normalized)})
            if normalized.startswith("Mapa semântico:"):
                self.discovery.record_automated("SEMANTIC_VISUAL_REPORTED", {"path_sha256": fingerprint})
            if normalized.startswith("Forma da criação:"):
                visual = Path(normalized.split(":", 1)[1].strip())
                self.discovery.record_automated("CREATION_VISUAL_REPORTED", {"path": str(visual)})
                timeline = visual.parent / "timeline.json"
                try:
                    if timeline.is_file() and not timeline.is_symlink() and timeline.stat().st_size <= 1_000_000:
                        payload = json.loads(timeline.read_text(encoding="utf-8"))
                        for page in payload.get("pages", []):
                            state = str(page.get("state", ""))
                            if state:
                                self.discovery.record_automated("VISUAL_STATE_VISITED", {"visual_state": state})
                except Exception as error:
                    self.discovery.record_automated("COMPONENT_FAILURE", {"component": "TIMELINE_OBSERVER", "error_type": type(error).__name__})
            if "traceback (most recent call last)" in folded:
                self.discovery.record_automated("TRACEBACK_EXPOSED", {"line_sha256": fingerprint, "chars": len(line)})
            elif "recoverable_failure" in folded:
                self.discovery.record_automated("RECOVERABLE_FAILURE", {"output_sha256": fingerprint, "chars": len(line)})
            elif any(marker in folded for marker in ("modulenotfounderror", "filenotfounderror", "keyerror:", "winerror")):
                self.discovery.record_automated("INFRASTRUCTURE_EXPOSED", {"output_sha256": fingerprint, "chars": len(line)})

        def drain_output(self) -> None:
            while True:
                try:
                    item = self.output.get_nowait()
                except queue.Empty:
                    break
                if isinstance(item, UxEvent):
                    self._render_ux_event(item)
                else:
                    self.append(str(item), "system")
            self.root.after(24 if self.dialogue_transport == "host-direct" else 80, self.drain_output)

        def _render_ux_event(self, event: UxEvent) -> None:
            payload = event.payload
            if event.kind is UxEventKind.PRESENCE_READY:
                self.status.set(str(payload["text"]))
            elif event.kind is UxEventKind.MODEL_LOADING:
                self.status.set("Estou aqui · acordando o motor local")
            elif event.kind is UxEventKind.MODEL_READY:
                self._model_ready = True
                self.status.set("Pronto")
            elif event.kind is UxEventKind.INPUT_REQUEST:
                self.append("\nCasulo\n", "assistant-label")
                self.append(str(payload["prompt"]) + "\n", "assistant")
                self.status.set("Estou ouvindo")
            elif event.kind is UxEventKind.ASSISTANT_START:
                turn_id = str(payload["turn_id"])
                self._assistant_buffers[turn_id] = []
                self.append("\nCasulo\n", "assistant-label")
                self.status.set("Pensando em voz alta")
            elif event.kind is UxEventKind.ASSISTANT_TOKEN:
                turn_id = str(payload["turn_id"])
                token = str(payload["text"])
                self._assistant_buffers.setdefault(turn_id, []).append(token)
                self.append(token, "assistant")
            elif event.kind is UxEventKind.ASSISTANT_END:
                turn_id = str(payload["turn_id"])
                answer = "".join(self._assistant_buffers.pop(turn_id, []))
                self.append("\n", "assistant")
                completed = str(payload.get("status", "COMPLETED")) == "COMPLETED"
                self.status.set("Pronto" if completed else "A conversa foi preservada; tente novamente")
                if completed and answer.strip():
                    self.speak_response(answer.strip())
            elif event.kind in {UxEventKind.JOB_STARTED, UxEventKind.JOB_MILESTONE}:
                self.append("\n" + str(payload["summary"]) + "\n", "job")
                self.status.set("Criando em background · você pode continuar falando")
            elif event.kind is UxEventKind.JOB_COMPLETED:
                self.append("\n" + str(payload["summary"]) + "\n", "presence")
                self.status.set("Criação pronta para inspecionar")
            elif event.kind in {UxEventKind.JOB_FAILED, UxEventKind.JOB_CANCELLED, UxEventKind.RECOVERABLE_ERROR}:
                self.append("\n" + str(payload.get("summary", payload.get("text", "Falha recuperável."))) + "\n", "error")
                self.status.set("Sessão preservada · você pode continuar")
            elif event.kind is UxEventKind.NOTICE:
                self.append("\n" + str(payload["text"]) + "\n", "job")

        def send(self, value: str | None = None) -> None:
            text = (value if value is not None else self.entry.get()).strip()
            if not text:
                return
            active_tts = self.tts_session is not None and getattr(self.tts_session, "active", False)
            if active_tts:
                self.discovery.record_automated("BARGE_IN", {"turn": self.turn_counter + 1, "source": "TEXT_OR_ASR"})
            if text in COMMANDS:
                self.discovery.record_automated("COMMAND_SUBMITTED", {"command": text})
            else:
                self.turn_counter += 1
                self.discovery.record_automated(
                    "USER_TURN",
                    {"turn": self.turn_counter, "input_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "input_chars": len(text)},
                )
                turn = self.turn_counter
                self.root.after(10_000, lambda: self._silence_probe(turn, 10_000))
                self.root.after(30_000, lambda: self._silence_probe(turn, 30_000))
            self.cancel_tts()
            self.entry.delete(0, "end")
            if text not in COMMANDS:
                self.append("\nVocê\n", "user-label")
                self.append(text + "\n", "user")
            with self._stdin_lock:
                if self.process is None or self.process.stdin is None:
                    self._pending_inputs.append(text)
                    self.status.set("Recebi · o motor local ainda está acordando")
                    return
                if self.process.poll() is not None:
                    self.append("A sessão encerrou; sua mensagem não foi enviada.\n", "error")
                    return
                self.process.stdin.write(text + "\n")
                self.process.stdin.flush()

        def _silence_probe(self, turn: int, threshold_ms: int) -> None:
            if self.last_answered_turn < turn and self.process is not None and self.process.poll() is None:
                self.discovery.record_automated("SILENCE_THRESHOLD", {"turn": turn, "threshold_ms": threshold_ms})

        def capture_voice(self) -> None:
            from tkinter.simpledialog import askstring

            self.discovery.record_automated("PHYSICAL_VOICE_CONSENT_REQUESTED", {"scope": "MICROPHONE_8S_AND_SESSION_TTS"})
            typed = askstring(
                "Casulo M1 · consentimento de voz",
                "Nada será capturado sem sua autorização. O PCM bruto não será salvo.\n\n"
                f"Para autorizar microfone por 8 segundos e TTS nesta sessão, digite exatamente:\n{VOICE_CONSENT}",
            )
            if typed != VOICE_CONSENT:
                self.discovery.record_automated("PHYSICAL_VOICE_CONSENT_DENIED", {"reason": "LITERAL_MISMATCH_OR_CANCEL"})
                self.status.set("Voz não autorizada · texto continua disponível")
                return
            consent_sha = hashlib.sha256(typed.encode("utf-8")).hexdigest()
            self.voice_authorized = True
            self.discovery.authorize_physical_voice(consent_sha256=consent_sha)
            self.cancel_tts()
            self.status.set("Ouvindo por 8 segundos · PCM não será persistido")

            def worker() -> None:
                command = [
                    sys.executable,
                    "-m",
                    "casulo.product.voice_cli",
                    "capture-smoke",
                    "--consent",
                    "CAPTURE_MICROPHONE_8_SECONDS_NO_STORAGE",
                    "--seconds",
                    "8",
                    "--threads",
                    "4",
                ]
                env = os.environ.copy()
                env["PYTHONPATH"] = str(self.repo / "src")
                try:
                    completed = subprocess.run(
                        command,
                        cwd=self.repo,
                        env=env,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        check=False,
                        shell=False,
                        timeout=120,
                    )
                    payload = json.loads(completed.stdout)
                    transcript = str(payload.get("transcript", "")).strip()
                    if completed.returncode == 0 and transcript:
                        self.discovery.record_automated(
                            "VOICE_TRANSCRIPTION_READY",
                            {"transcript_sha256": hashlib.sha256(transcript.encode("utf-8")).hexdigest(), "transcript_chars": len(transcript), "pcm_persisted": False},
                        )
                        self.root.after(0, lambda: self.send(transcript))
                        self.root.after(0, lambda: self.status.set("Transcrição local enviada · PCM não persistido"))
                        return
                    raise RuntimeError("ASR sem transcrição final")
                except Exception as error:
                    self.discovery.record_automated("COMPONENT_FAILURE", {"component": "VOICE_ASR", "error_type": type(error).__name__})
                    self.output.put("\n[Voz indisponível nesta tentativa; texto permanece disponível.]\n")
                    self.root.after(0, lambda: self.status.set("Falha de voz recuperável · texto disponível"))

            threading.Thread(target=worker, daemon=True).start()

        def speak_response(self, text: str) -> None:
            if not self.voice_authorized:
                if not self._suppressed_tts_recorded:
                    self._suppressed_tts_recorded = True
                    self.discovery.record_automated("TTS_SUPPRESSED_NO_LITERAL_CONSENT", {"text_available": True})
                return
            self.discovery.record_automated("TTS_START_REQUESTED", {"utterance_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "utterance_chars": len(text)})
            try:
                super().speak_response(text)
                self.discovery.record_automated("TTS_STARTED", {"authorized": True})
            except Exception as error:
                self.discovery.record_automated("COMPONENT_FAILURE", {"component": "TTS", "error_type": type(error).__name__})

        def cancel_tts(self) -> None:
            active = self.tts_session is not None and getattr(self.tts_session, "active", False)
            super().cancel_tts()
            if active:
                self.discovery.record_automated("TTS_CANCELLED", {"reason": "TURN_OR_CLOSE"})

        def note(self) -> None:
            from tkinter.simpledialog import askstring

            note = askstring("Casulo M1 · nota humana", "O que você observou? Esta opinião ficará separada dos diagnósticos automáticos.")
            if not note:
                return
            category = askstring(
                "Casulo M1 · categoria",
                "Categoria: GENERAL, VOICE, CHEMISTRY, MEMORY, PROJECT_BLEED, INTENT_ARTIFACT_DIVERGENCE, CREATION, VISUAL, LATENCY, BUG, DESIRED_CHANGE ou SESSION_VERDICT",
                initialvalue="GENERAL",
            ) or "GENERAL"
            severity = askstring("Casulo M1 · severidade opcional", "UNASSESSED, P0, P1, P2 ou P3", initialvalue="UNASSESSED") or "UNASSESSED"
            try:
                source = (self.discovery.last_automated_event_id,) if self.discovery.last_automated_event_id else ()
                record = self.discovery.record_human_note(note, category=category, severity=severity, source_event_ids=source)
                self.output.put(f"\n[Nota humana {record['note_id']} preservada separadamente.]\n")
            except Exception as error:
                self.output.put(f"\n[Nota não gravada: {type(error).__name__}. Corrija categoria/severidade e tente novamente.]\n")

        def close(self) -> None:
            if self._discovery_finalized:
                return super().close()
            self.discovery.record_automated("SESSION_CLOSE_REQUESTED", {"turns": self.turn_counter})
            try:
                super().close()
            finally:
                self._process_observer_done.wait(timeout=2)
                code = self.process.poll() if self.process is not None else None
                self.discovery.finalize(outcome="CLOSED_BY_GUILHERME", process_exit_code=code)
                self._discovery_finalized = True

    return MondayDiscoveryWindow


def main() -> int:
    parser = argparse.ArgumentParser(description="Casulo M1 discovery session")
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--session-root", type=Path)
    parser.add_argument("--dialogue-transport", choices=DIALOGUE_TRANSPORTS, default="vm-bridge")
    args = parser.parse_args()
    release = args.release.resolve(strict=True)
    session_root = (args.session_root or default_session_root()).expanduser().resolve(strict=False)
    base = load_sealed_window(release)
    window = make_window(base, dialogue_transport=args.dialogue_transport)(release, session_root)
    window.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
