from __future__ import annotations

import json
import platform
import shutil
import subprocess


def main() -> int:
    system = platform.system().lower()
    if system == "windows":
        command = [
            "powershell", "-NoProfile", "-Command",
            "Get-Disk | Select-Object Number,FriendlyName,SerialNumber,BusType,PartitionStyle,Size,IsBoot,IsSystem | ConvertTo-Json -Depth 3",
        ]
    elif system == "linux" and shutil.which("lsblk"):
        command = ["lsblk", "--json", "--bytes", "--output", "NAME,PATH,MODEL,SERIAL,SIZE,TYPE,RM,RO,MOUNTPOINTS"]
    else:
        print(json.dumps({"status": "unavailable", "system": system, "write_supported": False}, indent=2))
        return 0
    completed = subprocess.run(command, check=False, text=True, encoding="utf-8", errors="replace", stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    print(json.dumps({
        "schema": "casulo-device-preflight/0.1",
        "status": "listed" if completed.returncode == 0 else "error",
        "system": system,
        "write_supported": False,
        "warning": "READ ONLY: this program cannot flash an image",
        "inventory": completed.stdout.strip() if completed.returncode == 0 else None,
        "error": completed.stderr.strip() or None,
    }, ensure_ascii=False, indent=2))
    return 0 if completed.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

