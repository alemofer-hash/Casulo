# ARC-8 — Fronteira matemática verificável

Estado: `PASS`  
Classificação: `PRODUCT_DIAGNOSTIC_NOT_SCIENTIFIC_BENCHMARK`

O kernel escolhido foi `living-memory/sparse-signed-cosine-python-v1`. A decisão foi `T_ADOPTED_SPECIALIZED` e o resultado T foi consumido pelo caminho owner. A equivalência máxima observada foi `0.0` sob tolerância `1e-15`.

O perfil curto mediu razão candidato/referência `0.763197` com limiar de adoção pré-fixado em `0.95`. O tráfego é contagem lógica de posições da representação (`86` contra `1280`), não bytes físicos, energia ou FLOPs.

## Fronteira honesta

Esta prova vale somente para o cosseno signed-hash de 64 dimensões usado pela LivingMemory. Qwen3-4B continua executando álgebra via llama.cpp/ggml; Whisper continua via whisper.cpp/ggml. A pilha tensorial histórica T não é o caminho owner atual. Não há alegação de superioridade matricial geral, energética ou científica.
