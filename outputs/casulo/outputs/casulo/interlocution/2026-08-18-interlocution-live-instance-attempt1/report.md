# Prova viva do Teorema da Interlocução — relatório

Estado: `T_CAUSAL_AUTHORITY_VALIDATED_PHYSICAL_INSTRUMENT_PENDING`.

## Resultado

Esta campanha valida uma instância causal, reproduzível e falsificável em três
workloads. Ela não prova universalidade e não mede energia. T governou as nove
decisões críticas, cada mutação T alterou a decisão/contrato ou causou recusa, e
o publicador só aceitou D após o receipt do juiz T.

- `A_T=9/9=1.00`; mutações causais `9/9 PASS`;
- Flood completo: três candidatos e três oráculos, equivalência `PASS`;
- holdouts: MAE linear e BCE logístico/working-set parcial, dois casos por
  candidato e por oráculo, ambos `PASS`;
- TI10: sete blocos A/B/C/D; D/A wall end-to-end mediano
  `0.1695562192953054`, IC95%
  `[0.16736001125675595, 0.1812736194534004]`;
- pico RSS D/A `0.1320337117991297`;
- tempo de CPU observado D/A `0.10609480812641084`;
- package joules e total-system joules: `UNAVAILABLE`, não zero.

## Respostas vinculantes

1. T governou dataset, inicialização, precisão, loss, update, estado do
   otimizador, working set, stopping e aceitação.
2. Kernels x86-64, Rust, NumPy, PyTorch, alocador e hardware continuaram
   estrangeiros; nenhum deles concedeu autoridade sem T.
3. As nove mutações alteraram TCAP e execução/recusa sem mudança em Python/C.
4. Os artefatos principais documentam 79 treinamentos completos: smoke 1;
   equivalência 6; TI10 63 incluindo warm-ups/oráculos; holdouts 8; demo v2 1.
5. Equivalência foi preservada no Flood e nos dois holdouts.
6. A matemática declarada da rede não foi eliminada. Eliminou-se overhead
   observável de framework/import/dispatch/estado ao usar primitive AOT lean.
7. Overhead D mediano por janela: arquitetura T
   `0.352868 s`,
   auditoria `0.0307725 s`,
   julgamento `0.0386681 s`,
   publicação `0.0022317 s`.
8. Redução exata de operações matemáticas: não. Estado/overhead reduzidos são
   sustentados por RSS, CPU, ciclos e tempo, não por contagem de toda instrução.
9. Houve redução física não energética em wall, CPU, ciclos e RSS neste protocolo.
10. Não houve redução energética validada; nenhum joule foi medido.
11. Os ataques implementados produziram zero falso PASS, sem provar ausência de ataques desconhecidos.
12. Dois holdouts sustentam a fronteira, mas não generalizam para toda rede.
13. Sustenta-se a proposição condicional e uma instância empírica sob R,
    autoridade causal T, receipts e V_R delimitado.
14. Universalidade, solidez completa de V_R, outros hosts e energia permanecem hipótese.
15. Próximo experimento: replicação multi-host independente com wattímetro,
    package energy válido e arquiteturas convolucionais/atenção pré-congeladas.

## Limites

O receipt Flood é envelopado pelo supervisor governado após o kernel síncrono;
contadores são internos, mas o hash ainda não é assinado dentro do kernel. A
redução end-to-end inclui overhead T e imports; compilação foi medida separada.
Tempo humano de interlocução não tinha timestamp válido e é `UNAVAILABLE`.
Nenhum claim energético, universal, PyTorch/Inductor geral, GPU, datacenter ou
produto é autorizado.
