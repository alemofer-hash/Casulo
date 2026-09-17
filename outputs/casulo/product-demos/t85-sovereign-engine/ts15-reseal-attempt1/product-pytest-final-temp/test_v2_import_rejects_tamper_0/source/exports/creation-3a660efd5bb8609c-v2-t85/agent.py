from __future__ import annotations
import json, os, subprocess, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parent
DESCRIPTOR = json.loads((ROOT / "agent-descriptor.json").read_text(encoding="utf-8"))
def main():
    payload = json.loads(sys.stdin.read() or "{}")
    with tempfile.TemporaryDirectory(prefix="casulo-t-agent-") as temporary:
        input_path = Path(temporary) / "input.json"
        input_path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
        completed = subprocess.run([
            str(ROOT / DESCRIPTOR["runtime"]), str(ROOT / DESCRIPTOR["tcap_root"]),
            DESCRIPTOR["entry_module"] + "::" + DESCRIPTOR["entry_function"], str(input_path),
            "", "materialized_agent", "agent:" + DESCRIPTOR["agent_id"], "0" * 64,
        ], capture_output=True, text=True, encoding="utf-8", errors="replace", shell=False, timeout=30)
    if completed.returncode != 0:
        sys.stderr.write(completed.stderr); return completed.returncode
    document = json.loads(completed.stdout)
    print(json.dumps(document, ensure_ascii=False, sort_keys=True)); return 0
if __name__ == "__main__": raise SystemExit(main())
