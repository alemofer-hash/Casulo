# Sprint 025 — primeiro fechamento em blocos térmicos

O scheduler `shape-adaptive-flop-thresholds/0.1` gerou a agenda
`(2, 1, 1, 1, 2)` para o grafo `heldout-wide`. O caminho nativo compilou e
preservou paridade numérica com NumPy nos provedores próprio e OpenBLAS.

| Provedor | Janela | Amostras | CV | Mediana por invocação | Pico | Resultado |
|---|---:|---:|---:|---:|---:|---|
| próprio | 250 ms | 7 | 10,95% | 959.197 ns | 53 °C | passou |
| OpenBLAS | 250 ms | 7 | 7,68% | 625.370 ns | 54 °C | passou |

As duas sessões tiveram retorno zero, paridade `PASS`, telemetria integralmente
`SAFE`, nenhum warning e nenhum throttling. O operador confirmou ausência de
odor, fumaça e ruído anormal nas três sessões do ciclo. O gate térmico aceitou
3/3 sessões e autorizou a continuidade controlada do roadmap.

Essas medianas não constituem uma comparação de velocidade: cada provedor foi
avaliado em pré-registro próprio e não houve desenho pareado. O próximo passo é
pré-registrar e executar a ablação agenda fixa versus adaptativa, ainda sem
PyTorch ou Inductor.

## Cadeia própria

- pré-registro: `0a0d7cf6cba9999f8c5ee73d4561bbc40975c4ce1aedae2e9f2ac563d0cc334a`;
- amostras: `982cfc9bed1fe9b25b7fc0883e2190f6748e760e81f5caace7ddf8454917875d`;
- veredito: `97b08ab9c26ad525eeab413bea058d4bf0813ef7861aab31732a5ddd5e0a1b86`;
- sessão térmica: `a008da4b23f2eba15a834bf2a322fb0f6a8e64f85540bf024affb5f631f7377a`.
- atestação física: `069711d3bc39194b82373f298d993d0f9cb8c952b909869680bcd999cf6dee8c`.

## Cadeia OpenBLAS

- pré-registro: `6bc38148297d3a3ecda3d6a6a7529c5004561e7ca3b081e8b34da55edc455998`;
- amostras: `d6d0ae1718cae46a714063e2a2abb3716997d21d666565e6120b796d7c090625`;
- veredito: `9be73da4c9ff48c4da2cf452c0fe717dfb91a1d9e6a70aa4401850bb3eadee6f`;
- sessão térmica: `f7b85d574e7271e73a37e09224dd4b6cce9841da0403836f1a117e4a54d54777`.
- atestação física: `62d93e09d63f811f46272dc4fb89cd73843e91d572dbb50eb3374fb2d3cc3c12`.

## Gate do ciclo

- gate: `PASSED`;
- sessões aceitas: 3/3;
- continuidade controlada: autorizada;
- SHA-256: `ea8a20d89d5ec52acf8d6b6414f548b846f0513e35829f662ff6418689e9a2d1`.
