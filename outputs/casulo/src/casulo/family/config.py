from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from pathlib import Path

from .contracts import FamilyContractError


@dataclass(frozen=True, slots=True)
class FamilyConfig:
    bind_host: str = "127.0.0.1"
    bind_port: int = 0
    max_request_bytes: int = 16_384
    # Absolute upper bound for a complete local generation. Client disconnects
    # are monitored independently and still cancel immediately.
    stream_wait_seconds: float = 300.0
    queue_capacity: int = 2
    max_stream_chunk_chars: int = 2_048
    max_stream_events: int = 512
    minimum_available_ram_bytes: int = 1_024**3
    minimum_disk_free_bytes: int = 30 * 1_024**3
    disconnect_policy: str = "cancel"
    mock_only: bool = True
    lan_enabled: bool = False
    require_device_auth: bool = False
    approved_network: str | None = None
    tls_certfile: Path | None = None
    tls_keyfile: Path | None = None
    rag_result_limit: int = 4
    rag_max_context_chars: int = 4_096

    def __post_init__(self) -> None:
        try:
            address = ipaddress.ip_address(self.bind_host)
        except ValueError as error:
            raise FamilyContractError("bind_host deve ser endereço IP literal") from error
        if not address.is_loopback:
            if not self.lan_enabled:
                raise FamilyContractError(
                    "gateway aceita loopback; bind LAN exige lan_enabled"
                )
            if not address.is_private or address.is_unspecified or address.is_multicast:
                raise FamilyContractError("bind LAN exige endereço privado específico")
            if not self.require_device_auth:
                raise FamilyContractError("bind LAN exige autenticação de dispositivo")
            if self.approved_network is None:
                raise FamilyContractError("bind LAN exige sub-rede aprovada")
            try:
                network = ipaddress.ip_network(self.approved_network, strict=False)
            except ValueError as error:
                raise FamilyContractError("sub-rede aprovada inválida") from error
            if address not in network or not network.is_private:
                raise FamilyContractError("bind_host fora da sub-rede privada aprovada")
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
        if not 1 <= self.rag_result_limit <= 8:
            raise FamilyContractError("rag_result_limit inválido")
        if not 256 <= self.rag_max_context_chars <= 6_144:
            raise FamilyContractError("rag_max_context_chars inválido")
        if not isinstance(self.mock_only, bool):
            raise FamilyContractError("mock_only inválido")
        tls_paths = (self.tls_certfile, self.tls_keyfile)
        if any(path is not None for path in tls_paths) and not all(
            path is not None for path in tls_paths
        ):
            raise FamilyContractError("certificado e chave TLS são inseparáveis")
        if self.lan_enabled and not all(path is not None for path in tls_paths):
            raise FamilyContractError("bind LAN exige TLS")
