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
        if not 0.1 <= self.stream_wait_seconds <= 30.0:
            raise FamilyContractError("stream_wait_seconds inválido")
        if not self.mock_only:
            raise FamilyContractError("Day 1 recusa engine não mock")
