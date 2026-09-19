from __future__ import annotations

import ipaddress
from dataclasses import dataclass

from .contracts import FamilyContractError


@dataclass(frozen=True, slots=True)
class FamilyConfig:
    bind_host: str = "127.0.0.1"
    bind_port: int = 0
    max_request_bytes: int = 16_384
    stream_wait_seconds: float = 5.0
    queue_capacity: int = 2
    max_stream_chunk_chars: int = 2_048
    max_stream_events: int = 512
    minimum_available_ram_bytes: int = 1_024**3
    minimum_disk_free_bytes: int = 30 * 1_024**3
    disconnect_policy: str = "cancel"
    mock_only: bool = True

    def __post_init__(self) -> None:
        try:
            address = ipaddress.ip_address(self.bind_host)
        except ValueError as error:
            raise FamilyContractError("bind_host deve ser endereço IP literal") from error
        if not address.is_loopback:
            raise FamilyContractError("Day 1 gateway aceita somente loopback")
        if not 0 <= self.bind_port <= 65_535:
            raise FamilyContractError("bind_port inválida")
        if not 1_024 <= self.max_request_bytes <= 1_048_576:
            raise FamilyContractError("max_request_bytes inválido")
        if not 0.1 <= self.stream_wait_seconds <= 600.0:
            raise FamilyContractError("stream_wait_seconds inválido")
        if not 1 <= self.queue_capacity <= 32:
            raise FamilyContractError("queue_capacity inválida")
        if not 64 <= self.max_stream_chunk_chars <= 16_384:
            raise FamilyContractError("max_stream_chunk_chars inválido")
        if not 8 <= self.max_stream_events <= 4_096:
            raise FamilyContractError("max_stream_events inválido")
        if self.minimum_available_ram_bytes < 1_024**3:
            raise FamilyContractError("piso de RAM abaixo de 1 GiB")
        if self.minimum_disk_free_bytes < 30 * 1_024**3:
            raise FamilyContractError("reserva de disco abaixo de 30 GiB")
        if self.disconnect_policy not in {"cancel", "drain"}:
            raise FamilyContractError("disconnect_policy inválida")
        if not isinstance(self.mock_only, bool):
            raise FamilyContractError("mock_only inválido")
