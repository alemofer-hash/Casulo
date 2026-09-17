from __future__ import annotations

import argparse
import json
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path


class HumanProofWindow:
    def __init__(self, release_root: Path) -> None:
        import tkinter as tk
        from tkinter import messagebox

        self.tk = tk
        self.messagebox = messagebox
        self.release_root = release_root.resolve(strict=True)
        self.repo = self.release_root.parents[1]
        self.root = tk.Tk()
        self.root.title("Casulo Owner · prova humana")
        self.root.geometry("1060x720")
        self.root.configure(bg="#07101d")
        self.status = tk.StringVar(value="Iniciando presença owner local…")
        tk.Label(self.root, text="CASULO", bg="#07101d", fg="#e5a33b", font=("Segoe UI", 13)).pack(anchor="w", padx=34, pady=(24, 2))
        tk.Label(self.root, text="Guia owner · candidato de prova humana", bg="#07101d", fg="#f5f0df", font=("Segoe UI Light", 25)).pack(anchor="w", padx=34)
        tk.Label(self.root, textvariable=self.status, bg="#07101d", fg="#7ea7d8", font=("Segoe UI", 10)).pack(anchor="w", padx=34, pady=(5, 14))
        self.log = tk.Text(self.root, bg="#0b1728", fg="#e8e4d6", insertbackground="#e5a33b", relief="flat", wrap="word", font=("Segoe UI", 11), state="disabled")
        self.log.pack(fill="both", expand=True, padx=34, pady=6)
        row = tk.Frame(self.root, bg="#07101d")
        row.pack(fill="x", padx=34, pady=(8, 4))
        self.entry = tk.Entry(row, bg="#111f32", fg="#f5f0df", insertbackground="#e5a33b", relief="flat", font=("Segoe UI", 11))
        self.entry.pack(side="left", fill="x", expand=True, ipady=7)
        self.entry.bind("<Return>", lambda _event: self.send())
        self.send_button = tk.Button(row, text="Enviar", command=self.send, state="disabled")
        self.send_button.pack(side="left", padx=(8, 0))
        actions = tk.Frame(self.root, bg="#07101d")
        actions.pack(fill="x", padx=34, pady=(4, 22))
        for label, command in (("Criar", ":criar"), ("Universos", ":universos"), ("Rota", ":rota"), ("Memória", ":memoria"), ("Snapshot", ":snapshot"), ("Restore", ":restore"), ("Exportar", ":export")):
            tk.Button(actions, text=label, command=lambda value=command: self.send(value)).pack(side="left", padx=(0, 6))
        tk.Button(actions, text="Falar (8 s)", command=self.capture_voice).pack(side="left", padx=(8, 6))
        tk.Button(actions, text="Nota", command=self.note).pack(side="left", padx=(0, 6))
        tk.Button(actions, text="Sair", command=self.close).pack(side="right")
        self.process: subprocess.Popen[str] | None = None
        self.output: queue.SimpleQueue[str] = queue.SimpleQueue()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        threading.Thread(target=self.start_session, daemon=True).start()
        self.root.after(80, self.drain_output)

    def append(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.configure(state="disabled")

    def command(self) -> list[str]:
        cache = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Casulo/cache/generative"
        vm_root = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Casulo/human-proof/owner-vm"
        feedback = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Casulo/owner-human-proof-feedback"
        return [
            sys.executable, "-u", str(self.repo / "tools/casulo_semantic_multiverse_vm_inspect.py"),
            "--source-image", str(self.release_root / "OWNER_VM/casulo-native-generative-interactive.img"),
            "--candidate", str(self.repo / "release/generative-candidates/qwen3-4b-q4km-llamacpp-b10362.json"),
            "--cache", str(cache), "--vm-root", str(vm_root), "--feedback-root", str(feedback),
            "--repo", str(self.repo), "--threads", "4",
        ]

    def start_session(self) -> None:
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONPATH"] = os.pathsep.join([str(self.repo / "src"), str(self.repo / "private/casulo-owner/src")])
        try:
            self.process = subprocess.Popen(self.command(), cwd=self.repo, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", bufsize=1, shell=False)
            assert self.process.stdout is not None
            self.output.put("[Presença local iniciada; Cloud e rede guest continuam bloqueados.]\n")
            self.root.after(0, lambda: self.send_button.configure(state="normal"))
            self.root.after(0, lambda: self.status.set("Pronto · voz local opcional · texto é fallback explícito"))
            for line in iter(self.process.stdout.readline, ""):
                self.output.put(line)
            code = self.process.wait()
            self.output.put(f"\n[Sessão encerrada com código {code}; memória e artifacts permanecem.]\n")
        except Exception as error:
            self.output.put("\n[Não foi possível iniciar; estado anterior preservado: " + " ".join(str(error).split())[:500] + "]\n")

    def drain_output(self) -> None:
        while True:
            try:
                self.append(self.output.get_nowait())
            except queue.Empty:
                break
        self.root.after(80, self.drain_output)

    def send(self, value: str | None = None) -> None:
        text = (value if value is not None else self.entry.get()).strip()
        if not text or self.process is None or self.process.stdin is None or self.process.poll() is not None:
            return
        self.entry.delete(0, "end")
        self.append(f"\nVocê › {text}\n")
        self.process.stdin.write(text + "\n")
        self.process.stdin.flush()

    def capture_voice(self) -> None:
        if not self.messagebox.askyesno("Casulo · voz", "Capturar o microfone local por 8 segundos? O PCM bruto não será salvo."):
            return
        self.status.set("Ouvindo por 8 segundos…")
        def worker() -> None:
            command = [sys.executable, "-m", "casulo.product.voice_cli", "capture-smoke", "--consent", "CAPTURE_MICROPHONE_8_SECONDS_NO_STORAGE", "--seconds", "8", "--threads", "4"]
            env = os.environ.copy(); env["PYTHONPATH"] = str(self.repo / "src")
            completed = subprocess.run(command, cwd=self.repo, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False, shell=False, timeout=120)
            try:
                payload = json.loads(completed.stdout)
                transcript = str(payload.get("transcript", "")).strip()
                if completed.returncode == 0 and transcript:
                    self.root.after(0, lambda: self.send(transcript))
                    self.root.after(0, lambda: self.status.set("Transcrição local enviada · PCM não persistido"))
                    return
            except json.JSONDecodeError:
                pass
            self.output.put("\n[Voz indisponível nesta tentativa; use texto e preserve o erro em Nota.]\n")
            self.root.after(0, lambda: self.status.set("Voz recuperável · texto disponível"))
        threading.Thread(target=worker, daemon=True).start()

    def note(self) -> None:
        from tkinter.simpledialog import askstring
        note = askstring("Casulo · nota", "O que você quer preservar?")
        if not note:
            return
        command = [sys.executable, str(self.repo / "tools/human_proof_control.pyw"), "feedback", "--release", str(self.release_root), "--note", note, "--json"]
        completed = subprocess.run(command, cwd=self.repo, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False, shell=False)
        self.output.put("\n" + completed.stdout + "\n")

    def close(self) -> None:
        if self.process is not None and self.process.poll() is None and self.process.stdin is not None:
            try:
                self.process.stdin.write(":sair\n"); self.process.stdin.flush()
                self.process.wait(timeout=5)
            except Exception:
                self.process.terminate()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release", type=Path, required=True)
    args = parser.parse_args()
    try:
        HumanProofWindow(args.release).run()
        return 0
    except Exception as error:
        try:
            from tkinter import messagebox
            messagebox.showerror("Casulo", "A sessão não iniciou; nenhum estado foi apagado.\n\n" + " ".join(str(error).split())[:500])
        except Exception:
            pass
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
