# Campanha energética HWiNFO: TCAP × PyTorch Eager

**Estado científico:** `BLOCKED_PHYSICAL_INSTRUMENT`

## Escopo autorizado

HWiNFO-reported CPU package energy on bare-metal Windows. O resultado não mede energia total na tomada nem energia do Casulo Native.

## Instrumento e desenho

- Campo literal: `Potência total da CPU [W]` (w)
- Conversão: integração trapezoidal nos timestamps reais
- Amostragem mediana: 2.001000 s
- Pares válidos: 0/21
- Rejeitados: 3
- Épocas por treinamento: 400
- Threads/afinidade: 1 / [4]
- Idle medido: 3.887657158 W

## Resultado primário

- TCAP: unavailable J/treinamento
- PyTorch Eager: unavailable J/treinamento
- Razão TCAP/Eager: unavailable
- IC bootstrap pareado 95%: [unavailable, unavailable]
- Teste de sinais: `null`

## Equivalência

Gate: `PASS`; tolerância absoluta congelada 1e-9; mesmas 400 épocas, dataset, parâmetros iniciais, precisão e threads.

## Limites invariantes

- `TOTAL_SYSTEM_WALL=BLOCKED_PHYSICAL_INSTRUMENT`
- `CASULO_NATIVE_ENERGY=BLOCKED_PHYSICAL_INSTRUMENT`
- Nenhuma alegação sobre Inductor, datacenter, GPU/TPU ou potência elétrica calibrada externamente.
- Nenhum outlier foi removido após observação.

## Bloqueio físico observado

`THERMAL_ENVELOPE_INCOMPATIBLE_WITH_REQUIRED_HWINFO_WINDOW`: The host reached 76 C on the final short-probe attempt and an earlier rejected attempt recorded 81 C with HWiNFO thermal throttling; K was never frozen and no definitive pair started.

Ação humana única restante: Provide an active cooling configuration that keeps a one-thread PyTorch Eager 120-second validation below 75 C with zero HWiNFO throttling, then rerun the frozen casulo-energy command.
