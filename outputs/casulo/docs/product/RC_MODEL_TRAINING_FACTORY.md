# RC5 — Data Foundry e primeira camada aprendida Casulo

## Artefato obrigatório local

O primeiro artefato aprendido first-party é o
`casulo-semantic-router-nb-char4-v1`: um classificador multinomial treinado
localmente sobre exemplos sintéticos first-party, sem conteúdo do usuário e sem
qualquer dado dos holdouts RC3. Ele seleciona um dos seis universos semânticos,
mas não concede capabilities e nunca é autoridade de `PASS`.

O dataset separa famílias de cenário entre `train`, `valid` e `test`, possui
licença `MIT-first-party-synthetic`, deduplicação exata e lineage por hash. A
política de promoção foi congelada em
`models/training/router-rc5-promotion.json`: acurácia mínima 0,75 e ganho
absoluto mínimo 0,15 contra o baseline declarado.

Resultados da execução local:

- candidato: 1,00 top-1 em 12 casos de teste;
- baseline exato: 0,25;
- ganho absoluto: 0,75;
- regressões críticas de segurança/constraints: zero;
- estado: `OWNER_PROMOTED` para a função restrita de roteamento;
- fallback sem adapter: disponível e não amplia capabilities.

Esses números validam apenas o pequeno conjunto declarado. Não medem qualidade
humana geral nem transformam o roteador em foundation model.

## Limites

`Qwen3-4B Q4_K_M.gguf` permanece peso bootstrap de inferência, atribuído à
Qwen. Treino LoRA/QLoRA 4B é
`DEFERRED_COMPUTE_NOT_AVAILABLE`; não houve download de checkpoint de treino.
`DPO=NOT_JUSTIFIED_YET`. Áudio e conversas pessoais não foram usados.

Evidência: `product-demos/revolution-closure/rc05-training/`.

