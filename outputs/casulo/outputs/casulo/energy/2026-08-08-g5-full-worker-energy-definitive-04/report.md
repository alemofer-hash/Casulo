# Energia TCAP completo × PyTorch Eager completo

**Estado científico:** `BLOCKED_PHYSICAL_COOLING_REQUIRED`

A campanha parou antes de qualquer workload. O host não sustentou a condição
idle simétrica pré-registrada de 30 segundos dentro de uma faixa de ±1 °C.
O maior trecho observado foi 7.293 s.
Além disso, o HWiNFO registrou 4 amostras
instantâneas de throttling do núcleo/P-core 1 durante esse idle sem workload.

O evento anterior a 68 °C foi confirmado como thermal throttling instantâneo
por três sensores HWiNFO. Como o gate térmico falhou antes dos probes, `K` não
foi calibrado e nenhum dos 21 pares foi iniciado. Não existem joules
comparativos válidos para TCAP ou Eager nesta campanha.

## Próxima ação física única

Fornecer resfriamento ativo e um host quiescente capaz de sustentar o gate idle
de 30 segundos; depois executar uma nova identidade de campanha.

`TOTAL_SYSTEM_WALL=BLOCKED_PHYSICAL_INSTRUMENT`

`CASULO_NATIVE_ENERGY=BLOCKED_PHYSICAL_INSTRUMENT`
