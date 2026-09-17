from __future__ import annotations

import sys
import types
from pathlib import Path

from PyInstaller.archive.readers import CArchiveReader


EXECUTABLE = Path(
    r"C:\Users\guimo\Downloads\telencefalus_desktop_v0_4_0\dist\Telencefalus.exe"
)


def iter_code(root: types.CodeType):
    queue: list[tuple[int, types.CodeType]] = [(0, root)]
    while queue:
        depth, code = queue.pop(0)
        yield depth, code
        queue.extend(
            (depth + 1, value)
            for value in code.co_consts
            if isinstance(value, types.CodeType)
        )


def main() -> int:
    archive = CArchiveReader(str(EXECUTABLE)).open_embedded_archive("PYZ.pyz")
    modules = sys.argv[1:] or sorted(
        name for name in archive.toc if name == "tlang" or name.startswith("tlang.")
    )
    for module in modules:
        root = archive.extract(module)
        print(f"\n### {module} [{root.co_filename}]")
        for depth, code in iter_code(root):
            argument_count = (
                code.co_posonlyargcount + code.co_argcount + code.co_kwonlyargcount
            )
            arguments = ", ".join(code.co_varnames[:argument_count])
            print(f"{'  ' * depth}{code.co_qualname}({arguments})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
