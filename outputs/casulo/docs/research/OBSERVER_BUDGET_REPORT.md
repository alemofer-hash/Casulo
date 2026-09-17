# Orçamento do observador HWiNFO

## Limites pré-registrados

- CPU do watcher: até 2% de um núcleo;
- acréscimo de potência idle: até 1,0 W;
- acréscimo de temperatura mediana: até 2 °C;
- acréscimo de temperatura máxima: até 3 °C;
- p95 de polling: até 0,300 s;
- zero thermal throttling;
- leitura somente dos bytes anexados, com chunk máximo de 1 MiB.

## Defeito encontrado e corrigido

O primeiro guard pré-janela relia uma cauda de 256 KiB a cada 250 ms. Sob o
CSV ativo, o processo chegou a aproximadamente 45% de um núcleo. A campanha
foi interrompida antes do Controle B. O caminho crítico foi substituído por um
watcher append-only que lê somente bytes novos, mantém uma única linha parcial
e falha se atrasar mais de 1 MiB.

A regressão cobre leitura incremental, linha parcial, chunk limitado e estado
térmico localizado. A suíte direcionada passou com 43 testes.

## Controle completo preservado, mas não aprovado

Uma sessão A/B/C anterior, sem throttling, observou:

| Medida | HWiNFO | + watcher | + runner idle |
|---|---:|---:|---:|
| potência média | 10,2673 W | 9,8158 W | 8,8850 W |
| temperatura mediana | 52 °C | 51 °C | 49 °C |
| temperatura máxima | 70 °C | 76 °C | 65 °C |
| CPU do processo observador | — | 1,4271% | 1,3854% |

O watcher ficou dentro dos orçamentos de CPU, potência, mediana, polling,
throttling e chunk (máximo observado 15.449 bytes). A sessão, porém, foi
reprovada porque a máxima de B ficou 6 °C acima de A, excedendo o limite
congelado de 3 °C. A potência e a mediana não mostram uma assinatura causal do
watcher; ainda assim, o gate não foi reclassificado.

Consequentemente, o observador incremental está implementado e testado, mas o
orçamento físico final só pode ser aprovado por uma repetição A/B/C com
condições iniciais térmicas simétricas.
