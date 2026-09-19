"""One-shot ASR worker. PCM and transcript exist only in process memory/pipes."""
import sys
from array import array

from casulo.product.whisper_worker import WhisperNativeBackend


def main():
    raw = sys.stdin.buffer.read(640001)
    if not raw or len(raw) > 640000 or len(raw) % 2:
        return 2
    pcm = array("h", raw)
    floats = array("f", (sample / 32768.0 for sample in pcm))
    backend = WhisperNativeBackend(sys.argv[1], sys.argv[2], threads=2, use_gpu=False)
    try:
        text = backend.transcribe(floats).strip().encode("utf-8")
        if not text or len(text) > 8192:
            return 3
        sys.stdout.buffer.write(text)
    finally:
        backend.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
