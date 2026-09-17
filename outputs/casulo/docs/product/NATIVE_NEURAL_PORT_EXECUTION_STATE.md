# Estado de execução — port neural Native

Data: 2026-08-20
Estado: `NATIVE_BOUNDED_TOKENIZER_AND_EMBEDDING_VALIDATED_ONE_BLOCK_PENDING`

## Promoção NP5

O gate posterior NP5 foi aprovado em três boots. Três entradas ordinárias
ASCII/latinas produziram no Native os mesmos IDs do `llama-tokenize.exe`
b10362 offline; o token `49242` selecionou e dequantizou uma linha autêntica
Q6_K de 2.560 valores. Special tokens e scripts fora do escopo são recusados.

O chat template não foi executado, nenhum bloco Transformer foi avaliado e não
houve token de saída. O estado autoritativo está em
`docs/product/NATIVE_TOKENIZER_EMBEDDING_EXECUTION_STATE.md`.

## Promoção NP4

O gate NP4 posterior a este histórico foi aprovado. O GGUF owner completo foi
exposto ao guest por `fw_cfg` DMA read-only; o parser paginado percorreu os
metadados, localizou três tensores autênticos e alcançou a cauda sem colocar os
2.497.280.256 bytes no heap. Três boots definitivos, item ausente e arquivo
truncado passaram pelos resultados esperados.

A contabilidade do probe trouxe 5.375.232 bytes para o cache bounded, ou
0,215243% da fonte. Isso descreve somente o padrão esparso deste gate, não
compressão, desempenho ou inferência. Nenhum token foi produzido.

O estado autoritativo do novo gate está em
`docs/product/NATIVE_MODEL_PAGED_IO_EXECUTION_STATE.md`. O restante deste
documento preserva o histórico NP3 e sua errata.

## Resultado principal

O Casulo Native agora possui um crate `no_std` próprio que lê GGUF v3 dentro de
limites explícitos, projeta a configuração Qwen3, localiza tensores e executa
primitives F32, Q4_K e Q6_K sobre bytes autênticos do modelo owner adotado.

Isso é uma fronteira real de implementação, mas ainda não é inferência neural.
O modelo completo não foi mapeado e nenhum token derivado dos pesos foi emitido.

## Modelo congelado

| Campo | Valor |
| --- | --- |
| Modelo | `Qwen3-4B-Q4_K_M.gguf` |
| Licença declarada | `Apache-2.0` |
| Bytes | `2.497.280.256` |
| SHA-256 | `7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5` |
| GGUF | v3, 28 metadados, 398 tensores |
| Arquitetura | Qwen3, 36 blocos, embedding 2.560, FFN 9.728 |
| Atenção | 32 heads Q, 8 heads KV |

O ledger do produto classifica esse modelo como `ADOPTED_VERIFIED_LOCAL`. O
manifest histórico de candidatura ainda contém o estado pré-adoção e não é
usado isoladamente como decisão de adoção.

## Contabilidade dos pesos

| Formato | Tensores | Payload exato |
| --- | ---: | ---: |
| F32 | 145 | 784.384 bytes |
| Q4_K | 216 | 1.765.048.320 bytes |
| Q6_K | 37 | 725.491.200 bytes |
| Total | 398 | 2.491.323.904 bytes |

O total coincide exatamente com a região de tensores depois do offset GGUF de
5.956.352 bytes. O inventário reproduzível da fonte corrente está em
`outputs/casulo/native-neural-port/2026-08-20-np3/model-inventory-current-source.json`.

## Implementação entregue

- `os/native-model`: parser GGUF `no_std`, projeção Qwen3, tensor lookup,
  contabilidade de armazenamento e primitives F32/Q4_K/Q6_K;
- `tools/build_native_gguf_probe.py`: lê o modelo adotado, verifica tamanho e
  SHA-256 e cria projeção content-addressed sem copiar o modelo inteiro;
- `tools/build_native_system_pack.py`: admite a projeção como entrada kind 4;
- `os/kernel/src/model_probe.rs`: valida proveniência, configuração, formatos,
  hashes, resultados numéricos e corrupção;
- `os/tools/run_native_model_probe_qemu.py`: três boots read-only, sem rede e
  sem dispositivo físico;
- `tools/inventory_native_qwen.py`: inventário integral, contabilidade por
  formato e fronteira de claims.

## Errata preservada

NP1 e NP2 consumiram bytes autênticos, mas a primeira primitive Q4_K reutilizava
um par escala/mínimo por 64 elementos. Q4_K exige dois pares independentes, um
por metade de 32. O número Q4_K desses probes foi formalmente invalidado em
`docs/product/NATIVE_MODEL_WEIGHT_PRIMITIVE_ERRATA.md`; os artefatos não foram
apagados nem sobrescritos.

NP3 contém a correção, regressão com oito escalas distintas e uma nova cadeia
de hashes. Q6_K não foi afetado.

## Gate NP3

| Evidência | Resultado |
| --- | --- |
| Boots QEMU | 3/3 PASS |
| Q4_K dot bits | `3e294826` |
| Q6_K dot bits | `bc705310` |
| Corrupção | `QUARANTINE` |
| Rede guest | OFF |
| Imagem | read-only, hash antes = depois |
| Dispositivo físico escrito | não |
| Modelo completo mapeado | não |
| Primeiro token | não |

Depois da formatação focal dos dois módulos Rust novos, a fonte corrente foi
recompilada numa imagem append-only distinta e o gate de três boots foi
reexecutado. Essa segunda imagem, e não uma mutação do artifact anterior, é a
evidência autoritativa do checkpoint atual.

Hashes principais da fonte corrente:

- projeção: `47b0f62fa715d0de910a7aef18005eaa27ef23b65326aa243253af85faedf495`;
- manifest da projeção: `a54dea2c1c652f7b98f497d427094c41d857f0193249dd2bf98b7bccb22d6246`;
- system pack: `c209aae87feb8549ddadca6ff6b454060fcb99783d1a07ee5849402baaf0ee4d`;
- imagem `np3-attempt-2`:
  `1793586e703116916f5f5ca3a2c00e3564b30aa6bfc69f3a46e37cd6ab5d3112`;
- manifest da imagem:
  `7fc4680838ade270dae3ee6d090246b0f475b6b60b4035334f3e0b191662b9e8`;
- relatório de três boots da fonte corrente:
  `bd8737a6c952b59149da11f5161995ce8c05deb0d3fffa99682aef8e8d48a38e`;
- inventário da fonte corrente:
  `90c6b2e99f3b2129076051e3eeffdb3d40e31da96c3aaa4c660255cf7a82bfb3`.

A imagem NP3 anterior (`9468e5...`) e seu relatório (`d453a4...`) permanecem
preservados como evidência append-only anterior, também com 3/3 boots PASS.

## Validação executada

| Gate | Resultado |
| --- | --- |
| Pytest focal | 13 PASS |
| Unit tests `casulo-native-model` | 6 PASS |
| `rustfmt --check` nos módulos Rust novos | PASS |
| Build release `x86_64-unknown-none` | PASS |
| QEMU da imagem da fonte corrente | 3/3 PASS |
| `SHA256SUMS` | PASS |

`cargo test --workspace` não é um gate host válido nesta árvore: o pacote raiz
usa artifact dependency do kernel para `x86_64-unknown-none`, enquanto outras
dependências do teste exigem `std`; a tentativa terminou em `E0463`. Isso não
foi contado como PASS. O crate novo foi testado isoladamente no host e o kernel
foi compilado para o target real e exercitado em QEMU. A suíte workspace deve
ser futuramente separada em gates host e freestanding, sem feature unification
entre os dois targets.

## Limite de memória observado

O runner atual fornece 256 MiB ao guest e o heap do kernel possui 2 MiB. O
arquivo de pesos possui aproximadamente 2,33 GiB. Portanto, copiar o GGUF para
o heap ou RAM corrente é impossível e seria a arquitetura errada.

O próximo gate deve ler o arquivo owner verificado como mídia virtual regular,
read-only e content-addressed, por páginas. Ele não deve duplicar 2,5 GB no
repositório, no system pack ou numa segunda imagem de VM.

## Claims autorizados

- o Native reconhece a configuração estrutural do Qwen3 adotado;
- bytes autênticos F32, Q4_K e Q6_K foram consumidos no Native;
- as primitives corrigidas foram reproduzidas em três boots isolados;
- corrupção da projeção foi rejeitada antes de execução.

## Claims não autorizados

- Qwen3 completo executado pelo Casulo Native;
- primeiro token derivado do modelo;
- conversa neural sem Windows/Linux;
- equivalência integral com `llama.cpp`;
- desempenho, energia, compressão ou superioridade.

## Próximo gate após a promoção NP5

`NP6_ONE_TRANSFORMER_BLOCK`:

1. RMSNorm, matvec e Q/K norm;
2. RoPE e grouped-query attention em contexto mínimo;
3. SwiGLU, residuais e tensor intermediário completo;
4. oráculo por etapa e controles de corrupção;
5. nenhum claim de token de saída antes dos 36 blocos e logits.

## 2026-08-21 — NP6 complete block zero

Estado promovido para
`NATIVE_ONE_COMPLETE_QWEN3_BLOCK_VALIDATED_36_BLOCKS_PENDING`.

- um token autêntico executou RMSNorm, Q/K/V, Q/K norm, RoPE, GQA/softmax,
  projeção de atenção, SwiGLU, down projection e ambos os residuais;
- 19/19 resumos intermediários coincidiram com o oráculo NumPy congelado;
- 100.925.440 MACs e 63.866.880 bytes de pesos foram contabilizados;
- hash final scalar Rust
  `487179f486f1df8a132b66f7ef1f542a4f1a8768278dfe67d8e5bcaab77b0b51`;
- 3/3 boots WHPX reproduziram o mesmo hash e mismatch mask zero;
- prefetch DMA bounded aumentou de 4 KiB para 256 KiB, sem mapear o GGUF
  inteiro e sem ultrapassar o heap de 2 MiB;
- host Rust adicional executou contexto 2 e passou 38/38 estágios;
- nenhum bloco posterior, logit, sampling ou output token foi executado.

Evidência autoritativa:

- `docs/product/NATIVE_TRANSFORMER_BLOCK_EXECUTION_STATE.md`;
- `outputs/casulo/native-neural-port/2026-08-21-np6/`;
- `release/casulo-native-neural-port-np6-attempt-4.img`.

Próximo gate: `NP7_ALL_36_BLOCKS_AND_LOGITS`.
