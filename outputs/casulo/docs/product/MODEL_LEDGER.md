# Ledger de modelos — Casulo generativo

## Já presentes

| ID | Papel | Natureza | Estado |
|---|---|---|---|
| `casulo-guide-policy-v1` | policy Alpha | determinística first-party | reference only |
| `casulo-exact-embedding-v1` | seleção Alpha | hash embedding first-party | reference only |
| `casulo-semantic-router-nb-char4-v1` | roteamento entre seis universos | Multinomial NB realmente treinado em dados sintéticos first-party | OWNER_PROMOTED_RC5; sem autoridade de capability/PASS |
| `whisper.cpp base/small q5_1` | ASR pt-BR | pesos locais de bootstrap | adopted voice |

Nenhum dos itens acima é um modelo generativo de linguagem.

## Candidato generativo

| Campo | Valor |
|---|---|
| ID | `qwen3-4b-q4km-llamacpp-b10362` |
| Modelo | `Qwen/Qwen3-4B-GGUF` |
| Revisão | `bc640142c66e1fdd12af0bd68f40445458f3869b` |
| Arquivo | `Qwen3-4B-Q4_K_M.gguf` |
| Bytes | `2497280256` |
| SHA-256 | `7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5` |
| Licença | `Apache-2.0` |
| Runtime | `llama.cpp b10362`, commit `4801e3c...` |
| Runtime bytes | `18426883` |
| Runtime SHA-256 | `a9d95d26cf00664f2902f73cb0fd9b167a3a1f252294bb2f8b236305f57d6363` |
| Estado | `ADOPTED_VERIFIED_LOCAL` |
| Manifest SHA-256 | `42b2c54788298c10c781695d48f9f7867f5cb25e6407f90dcf0ff45466c70562` |
| Cache | `%LOCALAPPDATA%/Casulo/cache/generative/qwen3-4b-q4km-llamacpp-b10362` |
| Adoption receipt SHA-256 | `915c3a7ede5894f179b99d56d48c547949c75667731b865d4bfd279080bd52cc` |
| `llama-server.exe` SHA-256 | `76008a268ba602b0a398a5d7d542a686ac279b662d97abc7eee84536d049264e` |
| Gate neural local | `LOCAL_STOCHASTIC_INFERENCE_PASS` |
| Evidência G1 SHA-256 | `899c0d25b3d3c48b25c5c4acb930e3c66d98c2001a42d4182a6aa2ca2b3f8edd` |
| Modo de reasoning | `off` no runtime; sampling normal permanece estocástico |
| Timeout ocioso | `180 s`, finito |
| Gate integrado G10 | `READY_FOR_GUILHERME_GENERATIVE_VM_INSPECTION` |
| Gate Semantic Multiverse reseal | `READY_FOR_GUILHERME_SEMANTIC_MULTIVERSE_REINSPECTION` |
| API externa no reseal | nenhuma |
| Pesos no pacote owner | nao embutidos; cache local verificado |

Fontes primárias: model card/licença do repositório oficial Qwen, blog Qwen3 e
release oficial ggml-org/llama.cpp. O modelo declara português entre mais de
100 idiomas/dialetos. A adoção foi autorizada literalmente em 2026-08-11; os
bytes e hashes foram verificados antes da promoção do staging. Nenhum dado do
usuário será usado para treino.
