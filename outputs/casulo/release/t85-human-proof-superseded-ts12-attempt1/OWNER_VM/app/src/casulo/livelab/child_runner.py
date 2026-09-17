from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        return 64
    control = Path(args[0])
    config = json.loads((control / "config.json").read_text(encoding="utf-8"))
    (control / "ready").write_text(str(os.getpid()), encoding="ascii")
    start = control / "start"
    cancel = control / "cancel"
    while not start.exists():
        if cancel.exists():
            return 125
        time.sleep(0.005)
    completed = subprocess.run(
        config["argv"],
        cwd=config["cwd"],
        env={**os.environ, **config["environment"]},
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    limit = int(config["maximum_output_bytes"])
    (control / "stdout.bin").write_bytes(completed.stdout[:limit])
    (control / "stderr.bin").write_bytes(completed.stderr[:limit])
    (control / "result.json").write_text(json.dumps({
        "returncode": completed.returncode,
        "stdout_truncated": len(completed.stdout) > limit,
        "stderr_truncated": len(completed.stderr) > limit,
    }, sort_keys=True), encoding="utf-8")
    return 0 if completed.returncode == 0 else 126


if __name__ == "__main__":
    raise SystemExit(main())
