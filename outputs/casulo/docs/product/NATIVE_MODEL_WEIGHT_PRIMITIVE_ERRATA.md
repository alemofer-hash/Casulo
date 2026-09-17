# Errata — primitive Q4_K Native

Data: 2026-08-20

## Escopo afetado

Os gates append-only `NP1` e a primeira/segunda coleta de `NP2` provaram que
bytes autênticos e content-addressed do modelo foram consumidos no Casulo
Native. Eles **não** provam compatibilidade aritmética Q4_K com `ggml`.

## Causa

A implementação inicial reutilizava um único par escala/mínimo para cada grupo
de 64 valores. O formato Q4_K aplica dois pares independentes, um para cada
metade de 32 valores. A referência primária é `dequantize_row_q4_K` em
`ggml/src/ggml-quants.c` do projeto `ggml-org/llama.cpp`.

## Consequência

- hashes do modelo, tensor e bloco: preservados e válidos;
- parsing GGUF e proveniência: preservados e válidos;
- resultado numérico Q4_K de NP1/NP2: invalidado;
- alegação `NATIVE_ALL_MODEL_WEIGHT_FORMATS_VALIDATED` anterior: superseded;
- nenhuma alegação de token ou inferência havia sido feita.

## Correção e regressão

A primitive passou a consultar oito pares de escala/mínimo. Foram adicionadas
regressões com oito grupos deliberadamente distintos, independentes do builder
do probe. O gate corrigido deve usar nova projeção, nova imagem e novos
receipts; nenhum artefato histórico será sobrescrito.
