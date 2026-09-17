# Mapa de fontes e evidências

## Evidência principal

| Tema | Fonte primária |
|---|---|
| estado terminal | `evidence/campaign/independent_verification.json` |
| autoridade 9/9 | `evidence/campaign/authority-after.json` |
| mutações | `evidence/campaign/causal_mutations-attempt2/summary.json` |
| equivalência Flood | `evidence/campaign/equivalence/flood-v1/equivalence.json` |
| holdouts | `evidence/campaign/holdouts/v1/summary.json` |
| A/B/C/D | `evidence/campaign/baselines/ti10-v2/analysis-expanded.json` |
| compressão | `evidence/campaign/compression.json` |
| demonstração | `evidence/campaign/demo/live-v2/events.jsonl` |
| cadeia/selagem | `evidence/campaign/MANIFEST.json` e `SHA256SUMS` |
| fontes T | `evidence/campaign/t_sources/` |
| TCAP/IR | `evidence/campaign/tcap/` |
| implementação | `evidence/research_code/` |

## Contexto necessário

- `evidence/research_docs/`: definições, protocolo, autoridade e estado;
- `evidence/full_worker/`: unidade científica completa anterior;
- `evidence/scientific_history/`: auditoria do canário e errata energética;
- `evidence/compiler/`: frontend, IR, graph e emissão T selecionados;
- `evidence/runtime/`: runtime nativo selecionado;
- `evidence/architecture/`: contexto de produto e limites, não prova central.

## Precedência temporal

O arquivo histórico `CLAIM_BOUNDARY.md` registra a fronteira antes do fechamento
da campanha e contém `A_T=0.00` naquele instante. Não o use para negar ou provar
o estado posterior. O fechamento corrente deve ser recomposto dos artefatos da
campanha e do verificador.

## Literatura externa

`template/bibliography/references.bib` é apenas um núcleo inicial. Cada entrada
precisa ser verificada em fonte primária antes de ser citada no PDF. O manuscrito
deve acrescentar literatura de requisitos, linguagens com efeitos, PCC/TAL,
compilação de ML, sistemas de treinamento, benchmarking, energia e
reprodutibilidade — sempre separando trabalho relacionado de analogia retórica.
