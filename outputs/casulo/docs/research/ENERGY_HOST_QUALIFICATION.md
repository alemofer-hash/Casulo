# Qualificação física do host para campanha energética

## Estado

`BLOCKED_AC_OR_BATTERY`

A tentativa autoritativa é
`outputs/casulo/preflight/2026-08-09-energy-host-qualification-02/`.
Nenhum TCAP, PyTorch Eager, build, teste, compilação ou empacotamento foi
executado.

## Atestação humana

O usuário declarou, com proveniência `USER_ATTESTED` e sem representação como
verificação por sensor/câmera:

- shutdown/cooldown completo;
- HWiNFO configurado em 250 ms;
- superfície rígida;
- traseira elevada;
- resfriamento ativo presente;
- entradas e saídas de ar livres.

## Instrumentação

Foi encontrado exatamente um CSV ativo:
`benchmarks/results/2026-08-02-sprint025-ablation/hwinfo-live-ablation.CSV`.
Em 61 novas amostras, os timestamps foram estritamente crescentes, a potência
do pacote foi finita e não negativa e o intervalo foi 0,225/0,250/0,2602/0,276
s para mínimo/mediana/p95/máximo. O gate de polling passou.

O watcher `append-only-incremental-v1` consumiu 0,140625 s de CPU em 14,782 s,
equivalente a 0,951% de um núcleo. Leu 101.458 bytes novos, com chunk máximo de
3.348 bytes e redução de 4.575.232 bytes no working set. O orçamento passou.

## Alimentação e bateria

AC permaneceu conectado em todas as observações. A bateria, porém, estava em
67,5–67,8% e recebia 25,732–25,986 W, mediana 25,868 W. Isso é carga material e
está distante da condição próxima de 100%/sem troca material exigida. Esta é a
causa primária.

## Perfil e atividade de fundo

O plano Windows já era `Equilibrado`, GUID
`381b4222-f694-41f0-9685-ff5bb260df2e`; nenhuma alteração foi necessária e o
perfil foi congelado para a futura tentativa.

Como causa secundária, a utilização total ficou em 38,7% de mediana e 49,1%
no p95, contra limites de 5% e 15%. O snapshot pontual mostrou OneDrive,
HWiNFO, Explorer e processos de interface entre os consumidores relevantes.
Nenhum deles foi encerrado. Não foram encontrados workers TCAP/Eager, runners,
watchers ou QEMU órfãos comprovadamente pertencentes ao projeto.

## Térmica preliminar

Nas 61 amostras preliminares, a temperatura dos cores teve mediana 56 °C,
p95 60 °C e máxima 62 °C, sem thermal throttling. Esses valores não equivalem
a uma qualificação idle de 20 minutos.

## Decisão

P0–P7 não passaram por bateria em carga material e atividade de fundo. Por
isso, iniciar P8 teria violado o protocolo. `idle_20min.csv` permanece vazio e
as métricas de 20 minutos, inclusive tendência final de 30 s, são
`NOT_STARTED`/indisponíveis, não zero.

A próxima tentativa exige uma única condição operacional composta: aguardar a
bateria atingir carga próxima de 100% sem fluxo material e o host ficar
quiescente, mantendo AC, HWiNFO 250 ms, plano Equilibrado e o resfriamento
declarado.

## Requalificação após bateria em 100%

O usuário informou posteriormente que a bateria atingiu 100%. A tentativa
autoritativa mais recente passou a ser
`outputs/casulo/preflight/2026-08-09-energy-host-qualification-04/`, com estado
`BLOCKED_BACKGROUND_ACTIVITY`.

Os sensores confirmaram 100% constante, 0 W de carga/descarga e AC contínuo.
Também passaram:

- polling: 60 novas amostras, mediana 0,253 s e p95 0,2663 s;
- watcher: 1,139% de um núcleo, 99.718 bytes lidos, chunk máximo 1.677 bytes e
  ausência de crescimento de memória;
- thermal throttling preliminar: zero;
- plano Windows: Equilibrado e inalterado.

O bloqueio restante foi atividade de fundo: 30,5% de CPU mediana e 44,06% no
p95, contra 5%/15%. O snapshot apontou OneDrive como maior consumidor, seguido
por HWiNFO e atividade do sistema. Nenhum processo foi encerrado.

Uma espera append-only adicional de cinco minutos preservada em
`2026-08-09-energy-host-quiescence-wait-01.json` confirmou que a carga não se
dissipou. A observação rolante final registrou 35,3% de mediana e 71,66% no
p95, com bateria 100%, 0 W, AC e zero throttling.

A janela qualificatória de 20 minutos continuou proibida. A próxima condição
única é tornar o host efetivamente quiescente sem encerrar à força OneDrive,
Windows, HWiNFO, segurança ou aplicativos com dados do usuário.

## Requalificação após pausa manual do OneDrive

O usuário pausou o OneDrive pela interface oficial. Duas novas tentativas foram
preservadas, sendo a mais recente e autoritativa
`outputs/casulo/preflight/2026-08-09-energy-host-qualification-06/`, novamente
com estado `BLOCKED_BACKGROUND_ACTIVITY`.

O OneDrive deixou de aparecer entre os processos relevantes, confirmando que o
bloqueio anterior foi removido. Permaneceram aprovados: bateria em 100% e 0 W,
AC contínuo, polling mediano de 0,250 s, zero thermal throttling e watcher
append-only dentro do orçamento.

A carga de fundo, contudo, permaneceu acima do protocolo: CPU total de 19,3%
na mediana e 30,24% no p95, contra limites congelados de 5% e 15%. O snapshot
pontual identificou o HWiNFO64 como maior consumidor, com 23,8% agregados sobre
os processadores lógicos durante sua amostragem; Codex, Xbox, System e processos
de interface apareceram em níveis menores. Nenhum deles foi encerrado e a
configuração do HWiNFO não foi alterada.

Como P0–P7 não passaram, a janela idle de 20 minutos permaneceu `NOT_STARTED` e
nenhum TCAP, Eager, build, teste, compilação ou empacotamento foi executado.

## Errata de semântica do sensor e espera corrigida

As tentativas até `-07` selecionavam `Utilização total da CPU [%]`, que no
HWiNFO representa CPU Utility ponderada por frequência, como se fosse ocupação
do host. Os julgamentos de `BLOCKED_BACKGROUND_ACTIVITY` dessas tentativas não
são mais evidência válida de uso real da CPU. Bateria, AC, polling, potência,
temperatura e throttling registrados por elas permanecem preservados e não são
afetados por esta errata.

O seletor agora distingue explicitamente `Uso total da CPU [%]` de
`Utilização total da CPU [%]`; somente o primeiro participa do gate de
quiescência. Uma regressão foi adicionada em
`tests/test_energy_host_qualification_sensor_semantics.py`, mas não foi
executada nesta qualificação, em respeito à proibição de testes do protocolo.

A tentativa corrigida `-08` ainda reprovou com uso real de CPU de 18,5% na
mediana e 27,2% no p95. Em seguida, a espera append-only corrigida observou 999
amostras entre 02:25:35,256 e 02:29:44,983 UTC: mediana 36,0%, p95 74,31% e
máxima 99,9% de uso real.

Quatro amostras consecutivas de thermal throttling ocorreram entre
02:29:04,437 e 02:29:05,196 UTC. O pacote atingiu 92 °C e 45,742 W. O
observador foi interrompido assim que o gate ficou definitivamente reprovado;
o HWiNFO permaneceu ativo. Estado autoritativo: `BLOCKED_THERMAL_THROTTLING`.
Nenhum TCAP, Eager, build, teste, compilação ou empacotamento foi executado.

Evidência: `outputs/casulo/preflight/2026-08-09-energy-host-quiescence-wait-02.json`.

## Cross-check simultâneo com o Windows — 2026-08-10

Após o bloqueio explícito do OneDrive, uma nova espera de cinco minutos terminou
em `BLOCKED_BACKGROUND_ACTIVITY`, sem thermal throttling. Para excluir nova
ambiguidade de sensor, foi executada uma comparação simultânea de 60 segundos
entre `Uso total da CPU [%]` do HWiNFO e `psutil.cpu_percent` do Windows.

Os contadores concordaram: medianas de 28,8% e 28,1%, p95 de 34,8% e 34,04%,
diferenças absolutas de 0,70 e 0,76 ponto percentual. O cross-check passou nos
limites congelados de 2 e 5 pontos.

A carga real foi atribuída principalmente a Windows Defender (`MsMpEng.exe`,
8,09% da capacidade total), Search Indexer (4,92%), Search Protocol Host
(4,18%), HWiNFO (3,12%) e aos processos da sessão. OneDrive permaneceu ausente.
Defender e indexação não foram interrompidos ou desativados. A janela idle de 20
minutos permaneceu proibida e nenhum workload foi executado.

Evidências:

- `outputs/casulo/preflight/2026-08-10-energy-host-quiescence-wait-01.json`;
- `outputs/casulo/preflight/2026-08-10-cpu-telemetry-crosscheck-02.json`.

## Piso de baixa carga e contabilidade por processo

Uma espera transacional posterior permaneceu ativa por 15 minutos. O melhor
piso sustentado foi 7,0% de mediana e 12,31% no p95, com bateria estável e zero
thermal throttling. Como o limite de mediana permaneceu em 5%, a qualificação
de 20 minutos não foi iniciada.

Em seguida, um cross-check de baixa carga por 120 segundos adicionou
contabilidade cumulativa por processo. O HWiNFO registrou 6,3% de mediana e
12,1% no p95; o contador Windows/psutil registrou 4,1% e 8,94%. A diferença de
mediana, 2,2 pontos, ultrapassou por 0,2 ponto o limite de consistência
pré-fixado. O resultado foi `BLOCKED_SENSOR_SEMANTICS`, sem escolher
retroativamente o contador que aprovava o gate.

O consumo atribuído incluiu HWiNFO (1,79% da capacidade total), DWM (0,46%),
Xbox (0,21%), System (0,20%) e processos Codex/ChatGPT (0,43% combinados). O
observador custou 0,033% da capacidade total e 1,22% ficou não atribuído pelos
processos estáveis inventariados.

A documentação do autor do HWiNFO define `Total CPU Usage` como a média
aritmética dos usos dos threads/cores e diferencia esse contador legado de CPU
Utility. Como a campanha já havia congelado `Uso total da CPU [%]` do HWiNFO,
ele permanece a fonte primária do gate; o contador Windows não foi promovido
após produzir o valor favorável.

Evidências:

- `outputs/casulo/preflight/2026-08-10-energy-host-quiescence-wait-04.json`;
- `outputs/casulo/preflight/2026-08-10-cpu-telemetry-crosscheck-03.json`.
