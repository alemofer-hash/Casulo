# Estado de execução — Teorema da Interlocução

Atualizado em: 2026-08-19

## Estado científico

- campanha: `2026-08-18-interlocution-live-instance-attempt1`;
- trilha isolada: `research/interlocution/`;
- TI0–TI14: executados;
- autoridade causal: `9/9`, portanto `A_T=1.00`;
- mutações causais: `9/9 PASS`;
- falsos HARD aceitos: `0` nos ataques implementados;
- FloodSurrogate completo: equivalência `PASS` em três casos, diferença máxima
  de parâmetros `2.220446049250313e-16` e de predições
  `1.7763568394002505e-15`;
- holdouts: regressão linear/MAE e classificação logística/BCE com working set
  parcial, ambos `PASS` por verificador independente;
- redução end-to-end D/A observada: razão mediana de wall time
  `0.1695562192953054`, IC bootstrap pareado 95%
  `[0.16736001125675595, 0.1812736194534004]`, `7/7` direções;
- razão de pico RSS D/A: `0.1320337117991297`;
- energia: não medida; package joules e total-system joules permanecem
  indisponíveis, nunca convertidos em zero;
- estado terminal conservador:
  `T_CAUSAL_AUTHORITY_VALIDATED_PHYSICAL_INSTRUMENT_PENDING`.

Esse estado valida uma instância causal e uma redução material em wall time,
tempo de CPU observado, ciclos steady-state e RSS neste host/workload. Ele não
autoriza alegação energética nem prova universal.

## Autoridade e fronteiras

T decide e sela, antes do trabalho: dataset, inicialização, precisão, loss,
update, estado do otimizador, working set, stopping e política de
equivalência/aceitação. O publicador consome o receipt do juiz T. Kernels,
NumPy, PyTorch, Rust, operações elementares e alocação continuam estrangeiros e
manifestados; executam primitives, não concedem `PASS`.

O receipt criptográfico do Flood é envolvido pelo supervisor governado após o
filho síncrono retornar, mas seus contadores vêm do kernel nativo. Essa é uma
fronteira residual: o envelope ainda não é assinado dentro do kernel x86-64.
O verificador separado recompõe binário, contadores, hashes e cadeias sem
importar trainer, worker ou `analysis.json`.

## Protocolo e tentativas preservadas

- `baselines/ti10-v1`: interrompido no warm-up porque o harness confundiu a
  recusa esperada do juiz no braço pós-fato com falha; preservado;
- `baselines/ti10-v2`: protocolo definitivo, sete blocos A/B/C/D;
- `demo/live-v1`: inválida para o passo de adulteração por causa errada,
  preservada com `ERRATA.md`;
- `demo/live-v2`: demonstração qualificável, 12 eventos reais;
- nenhuma amostra energética anterior foi reutilizada;
- o fator 656× permanece formalmente invalidado.

## Baseline de produto preservado

- branch inicial: `product/semantic-multiverse`;
- commit inicial: `df12e916c90d9bd2b966326275dc191573f38abd`;
- worktree histórico não foi limpo;
- release T85 permanece com manifest
  `87c046056ee16dbc2f02350f50bde62f9bb617ebfe002eb993536a794393f8ee`;
- Cloud `RELEASE_LOCKED`; owner/public/native e launcher não foram alterados por
  esta trilha; API externa, USB, block device e publicação continuam proibidos.

## Evidência principal

- `authority-after.json`;
- `causal_mutations-attempt2/summary.json`;
- `equivalence/flood-v1/equivalence.json`;
- `baselines/ti10-v2/analysis-expanded.json`;
- `holdouts/v1/summary.json`;
- `demo/live-v2/events.jsonl`;
- `independent_verification.json`;
- `compression.json`;
- `report.md`;
- `MANIFEST.json` e `SHA256SUMS`.

## Próximo experimento exato

Um laboratório independente deve reconstruir a campanha em outro host a partir
do manifesto, auditar a solidez do verificador e medir energia do pacote e da
tomada em protocolo pareado. A generalização deve adicionar arquiteturas
convolucionais/atenção e primitives independentes; não se deve aumentar o claim
com os três workloads atuais.
