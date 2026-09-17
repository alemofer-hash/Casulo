from __future__ import annotations

import pytest

from tools.inventory_native_qwen import tensor_storage_bytes


def test_tensor_storage_bytes_accounts_native_formats_exactly() -> None:
    assert tensor_storage_bytes(0, (16,)) == 64
    assert tensor_storage_bytes(12, (256,)) == 144
    assert tensor_storage_bytes(14, (256,)) == 210
    assert tensor_storage_bytes(12, (2560, 1024)) == 1_474_560


def test_tensor_storage_bytes_rejects_unknown_or_partial_blocks() -> None:
    with pytest.raises(ValueError, match="block aligned"):
        tensor_storage_bytes(12, (255,))
    with pytest.raises(ValueError, match="unaccounted"):
        tensor_storage_bytes(99, (256,))
