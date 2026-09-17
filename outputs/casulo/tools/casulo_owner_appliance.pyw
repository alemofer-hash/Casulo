from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from pathlib import Path


def repo_from_script() -> Path:
    return Path(__file__).resolve().parents[1]


def prepare(repo: Path):
    sys.path[:0] = [str(repo), str(repo / "src"), str(repo / "private/casulo-owner/src")]
    from tools.casulo_semantic_multiverse_vm_inspect import prepare_semantic_controller

    state = repo / "outputs/casulo/revolution-owner-vm/live"
    controller = prepare_semantic_controller(repo / "release/casulo-native-generative-interactive.img", state)
    return controller, controller.doctor()


def doctor_json(repo: Path) -> int:
    try:
        controller, report = prepare(repo)
        payload = {
            "schema": "casulo.owner-appliance-doctor/1.0",
            "ready": report["ready"],
            "base_read_only": report["base_os_read_only"],
            "overlay_exists": controller.overlay_path.is_file(),
            "network": report["network"],
            "host_block_devices": report["host_block_devices"],
            "cloud": report["cloud"],
            "recovery": "restore requires an existing named snapshot",
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if payload["ready"] else 2
    except Exception as error:
        print(json.dumps({"schema": "casulo.owner-appliance-doctor/1.0", "ready": False, "recovery_message": "Não foi possível preparar a VM. Execute VERIFY_CASULO_OWNER e preserve owner-data.", "error_type": type(error).__name__, "message": " ".join(str(error).split())[:500]}, ensure_ascii=False))
        return 2


class ApplianceWindow:
    def __init__(self, repo: Path) -> None:
        import tkinter as tk
        from tkinter import messagebox

        self.tk = tk
        self.messagebox = messagebox
        self.repo = repo
        self.root = tk.Tk()
        self.root.title("Casulo owner · Teloscorp")
        self.root.geometry("920x620")
        self.root.configure(bg="#07101d")
        self.status = tk.StringVar(value="Verificando o ambiente local…")
        tk.Label(self.root, text="CASULO", bg="#07101d", fg="#e5a33b", font=("Segoe UI", 13)).pack(anchor="w", padx=36, pady=(28, 2))
        tk.Label(self.root, text="Presença owner", bg="#07101d", fg="#f5f0df", font=("Segoe UI Light", 28)).pack(anchor="w", padx=36)
        tk.Label(self.root, textvariable=self.status, bg="#07101d", fg="#7ea7d8", font=("Segoe UI", 11)).pack(anchor="w", padx=36, pady=(6, 18))
        self.log = tk.Text(self.root, bg="#0b1728", fg="#e8e4d6", insertbackground="#e5a33b", relief="flat", wrap="word", font=("Segoe UI", 11), state="disabled")
        self.log.pack(fill="both", expand=True, padx=36, pady=8)
        row = tk.Frame(self.root, bg="#07101d")
        row.pack(fill="x", padx=36, pady=(10, 26))
        self.start = tk.Button(row, text="Iniciar Casulo", command=self.boot, state="disabled")
        self.start.pack(side="left")
        self.verify = tk.Button(row, text="Verificar", command=self.verify)
        self.verify.pack(side="left", padx=8)
        self.snapshot = tk.Button(row, text="Criar ponto seguro", command=self.make_snapshot, state="disabled")
        self.snapshot.pack(side="left", padx=8)
        self.restore = tk.Button(row, text="Restaurar ponto seguro", command=self.restore_snapshot, state="disabled")
        self.restore.pack(side="left", padx=8)
        self.controller = None
        threading.Thread(target=self._prepare, daemon=True).start()

    def append(self, text: str) -> None:
        def update() -> None:
            self.log.configure(state="normal")
            self.log.insert("end", text + "\n")
            self.log.see("end")
            self.log.configure(state="disabled")
        self.root.after(0, update)

    def _prepare(self) -> None:
        try:
            controller, report = prepare(self.repo)
            self.controller = controller
            if not report["ready"]:
                raise RuntimeError("o doctor não aprovou o ambiente")
            self.root.after(0, lambda: self.status.set("Pronto · local · Cloud bloqueado · guest sem rede"))
            self.root.after(0, lambda: self.start.configure(state="normal"))
            self.root.after(0, lambda: self.snapshot.configure(state="normal"))
            self.root.after(0, lambda: self.restore.configure(state="normal"))
            self.append("Ambiente verificado. A base é imutável e seus dados ficam no overlay owner.")
        except Exception as error:
            self.root.after(0, lambda: self.status.set("Ação necessária"))
            self.append("Não foi possível preparar a VM: " + " ".join(str(error).split())[:400])

    def _background(self, label: str, action) -> None:
        self.status.set(label)
        def worker() -> None:
            try:
                result = action()
                self.append(json.dumps(result, ensure_ascii=False, sort_keys=True))
                self.root.after(0, lambda: self.status.set("Pronto · nenhuma falha bruta foi exposta"))
            except Exception as error:
                self.append("A operação não foi concluída; estado anterior preservado. " + " ".join(str(error).split())[:400])
                self.root.after(0, lambda: self.status.set("Recuperável · estado anterior preservado"))
        threading.Thread(target=worker, daemon=True).start()

    def boot(self) -> None:
        if self.controller is not None:
            self._background("Iniciando a VM local…", lambda: self.controller.bridge_boot("owner-appliance-presence-ready", acceleration="tcg", timeout=60))

    def verify(self) -> None:
        if self.controller is not None:
            self._background("Verificando sem modificar…", self.controller.doctor)

    def make_snapshot(self) -> None:
        if self.controller is not None:
            self._background("Criando ponto seguro…", lambda: self.controller.snapshot("owner-live"))

    def restore_snapshot(self) -> None:
        if self.controller is not None:
            self._background("Restaurando ponto seguro…", lambda: self.controller.restore("owner-live"))

    def run(self) -> None:
        self.root.mainloop()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=repo_from_script())
    parser.add_argument("--doctor-json", action="store_true")
    args = parser.parse_args()
    repo = args.repo.resolve()
    if args.doctor_json:
        return doctor_json(repo)
    try:
        ApplianceWindow(repo).run()
        return 0
    except Exception as error:
        try:
            from tkinter import messagebox
            messagebox.showerror("Casulo", "O Casulo não iniciou. Seus dados foram preservados.\n\n" + " ".join(str(error).split())[:500])
        except Exception:
            pass
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
