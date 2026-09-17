from __future__ import annotations

import dis
import sys
import types
from pathlib import Path

from PyInstaller.archive.readers import CArchiveReader


EXECUTABLE = Path(
    r"C:\Users\guimo\Downloads\telencefalus_desktop_v0_4_0\dist\Telencefalus.exe"
)


def find_code(root: types.CodeType, qualname: str) -> types.CodeType:
    queue = [root]
    while queue:
        code = queue.pop(0)
        if code.co_qualname == qualname or code.co_name == qualname:
            return code
        queue.extend(value for value in code.co_consts if isinstance(value, types.CodeType))
    raise KeyError(f"Code object not found: {qualname}")


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit("usage: dis_pyz.py MODULE QUALNAME")
    module, qualname = sys.argv[1:]
    archive = CArchiveReader(str(EXECUTABLE)).open_embedded_archive("PYZ.pyz")
    code = find_code(archive.extract(module), qualname)
    print(f"# {module}:{code.co_qualname}")
    print(f"# names={code.co_names}")
    print(f"# constants={tuple(x for x in code.co_consts if not isinstance(x, types.CodeType))}")
    dis.dis(code)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
