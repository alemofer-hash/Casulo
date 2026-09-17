# Estado de execução — I/O paginado do modelo Native

Data: 2026-08-20

Estado: `NATIVE_COMPLETE_MODEL_PAGED_IO_VALIDATED_FIRST_TOKEN_PENDING`

## Resultado

O gate NP4 foi aprovado. O Casulo Native abriu o GGUF owner completo por uma
fonte read-only paginada, analisou sua estrutura sem materializar o arquivo no
heap, localizou tensores dinamicamente e consumiu bytes autênticos do início,
do meio e da cauda do objeto de 2.497.280.256 bytes.

Este resultado prova acesso esparso, limitado e fail-closed ao modelo inteiro.
Ele não prova inferência, geração de token, desempenho, compressão ou vantagem
energética.

## Fronteira implementada

- `os/native-model/src/lib.rs`: trait `ReadAt`, parser `PagedQwenGguf`, travessia
  limitada de metadados e busca dinâmica de tensores;
- `os/kernel/src/fw_cfg.rs`: transporte QEMU `fw_cfg` DMA read-only, uma página
  DMA de 4 KiB, cache bounded e contadores de leitura;
- `os/kernel/src/model_paged_probe.rs`: identidade estrutural, amostras F32,
  Q4_K e Q6_K, leitura da cauda, corrupção local e offset inválido;
- `os/tools/run_native_model_paged_qemu.py`: host verifica tamanho e SHA-256 do
  modelo antes e depois, monta somente o item exato e executa controles
  negativos;
- `os/tools/build_native_neural_port_image.py`: estágio append-only `np4`.

O item exposto ao guest é exatamente:

`opt/com.teloscorp.casulo/model.gguf`

O runner não aceita caminho arbitrário ou symlink, não usa shell, não liga
rede e não anexa dispositivo de bloco físico.

## Modelo e estrutura confirmados

| Campo | Valor |
| --- | ---: |
| Bytes | 2.497.280.256 |
| SHA-256, verificado pelo host | `7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5` |
| GGUF | versão 3 |
| Metadados | 28 |
| Tensores | 398 |
| Data offset | 5.956.352 |
| Blocos Qwen3 | 36 |
| Embedding | 2.560 |
| FFN | 9.728 |
| Heads Q / KV | 32 / 8 |

Tensores localizados a partir do diretório GGUF real:

| Tensor | Tipo | Offset absoluto |
| --- | --- | ---: |
| `output_norm.weight` | F32 | 5.956.352 |
| `token_embd.weight` | Q6_K | 5.966.592 |
| `blk.0.attn_k.weight` | Q4_K | 325.032.192 |

A leitura da cauda alcançou o offset 2.497.280.192. O arquivo completo foi
alcançável, mas não carregado integralmente no guest.

## Contabilidade observada

No boot de métricas:

| Medida | Resultado |
| --- | ---: |
| Bytes consumidos por parser e verificadores | 2.433.301 |
| Bytes trazidos ao cache bounded | 5.375.232 |
| Páginas de cache carregadas | 1.334 |
| Operações DMA | 2.668 |
| Fração do arquivo trazida ao cache | 0,215243% |

Essa fração é uma contabilidade de I/O do probe esparso, não uma medição de
compressão do modelo e não uma previsão do working set de uma inferência
completa. O comportamento de residência do processo QEMU no host não foi
medido; somente a residência no guest e os bytes solicitados pelo transporte
foram contabilizados.

## Controles negativos

- item ausente: rejeitado com `Transport(ModelMissing)`;
- arquivo truncado para 4.096 bytes: rejeitado com `Transport(ModelSize)`;
- corrupção da amostra: `QUARANTINE`;
- offset fora dos limites: `QUARANTINE`;
- imagem e modelo: hashes idênticos antes e depois.

O hash integral do modelo foi calculado e conferido pelo host. O guest não
calculou o SHA-256 integral e declara isso literalmente como
`NOT_COMPUTED`; sua confiança na identidade depende do runner owner verificado.

## Validação executada

| Gate | Resultado |
| --- | --- |
| Pytest focal NP1–NP4 | 16 PASS |
| Unit tests `casulo-native-model` | 7 PASS |
| Build release freestanding | PASS |
| Smoke QEMU | 1/1 PASS |
| Gate definitivo QEMU | 3/3 PASS |
| Modelo ausente | rejeitado |
| Modelo truncado | rejeitado |
| Primeiro token | não executado |

O comando Rust correto parte do workspace `os`:

```powershell
cargo test --locked --offline -p casulo-native-model
```

## Artefatos selados

- imagem: `release/casulo-native-neural-port-np4.img`;
- manifest da imagem: `release/casulo-native-neural-port-np4.manifest.json`;
- smoke: `outputs/casulo/native-neural-port/2026-08-20-np4/qemu-smoke-and-negative-controls.json`;
- três boots: `outputs/casulo/native-neural-port/2026-08-20-np4/qemu-definitive-3boots.json`;
- métricas: `outputs/casulo/native-neural-port/2026-08-20-np4/qemu-metrics-1boot.json`.

## Limites e transição física

`fw_cfg` é um transporte de qualificação de VM. A especificação QEMU trata
arquivos fornecidos externamente como read-only, mas isso não o transforma no
driver de armazenamento físico final. O Casulo OS em hardware precisará de uma
fonte read-only equivalente, com identidade content-addressed, paginação,
cancelamento e os mesmos contratos de erro, sem depender de QEMU.

## Próximo gate exato

`NP5_TOKENIZER_AND_EMBEDDING`:

1. interpretar vocabulário, merges e template diretamente do GGUF bounded;
2. comparar tokenização congelada com o runtime owner adotado;
3. localizar e decodificar a linha Q6_K de embedding para tokens reais;
4. emitir receipts de tokenizer e embedding com offsets, hashes e contadores;
5. rejeitar metadata incompatível, token fora do vocabulário e leitura parcial;
6. manter explícito que ainda não há token de saída do modelo.
