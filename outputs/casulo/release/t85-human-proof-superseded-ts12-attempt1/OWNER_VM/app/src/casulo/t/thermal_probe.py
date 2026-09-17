"""Sonda CPU curta e limitada para validar o Thermal Covenant."""

from __future__ import annotations

import argparse
import json
import multiprocessing
import time
from typing import Sequence


def _bounded_integer_work(seconds: float) -> None:
    deadline = time.perf_counter() + seconds
    state = 0x9E3779B9
    iterations = 0
    while time.perf_counter() < deadline:
        state ^= (state << 13) & 0xFFFFFFFF
        state ^= state >> 17
        state ^= (state << 5) & 0xFFFFFFFF
        iterations += 1
    if iterations < 1 or state < 0:
        raise RuntimeError("sonda não executou trabalho")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="casulo-thermal-probe")
    parser.add_argument("--seconds", type=float, required=True)
    parser.add_argument("--workers", type=int, choices=(1, 2), required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not 0 < args.seconds <= 15:
        raise SystemExit("--seconds precisa estar entre 0 e 15")
    started = time.perf_counter()
    if args.workers == 1:
        _bounded_integer_work(args.seconds)
    else:
        context = multiprocessing.get_context("spawn")
        processes = [
            context.Process(
                target=_bounded_integer_work,
                args=(args.seconds,),
            )
            for _ in range(args.workers)
        ]
        for process in processes:
            process.start()
        for process in processes:
            process.join()
        if any(process.exitcode != 0 for process in processes):
            return 1
    print(
        json.dumps(
            {
                "kind": "THERMAL_VALIDATION_PROBE",
                "workers": args.workers,
                "requested_seconds": args.seconds,
                "elapsed_seconds": time.perf_counter() - started,
                "claim": None,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
