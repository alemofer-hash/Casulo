# Estado de execução — tokenizer e embedding Native

Data de fechamento: 2026-08-21

Campanha: `2026-08-20-np5`

Estado: `NATIVE_BOUNDED_TOKENIZER_AND_EMBEDDING_VALIDATED_ONE_BLOCK_PENDING`

## Resultado

O NP5 foi aprovado em três boots QEMU reproduzíveis. O Casulo Native leu do
GGUF owner os metadados do tokenizer GPT-2/Qwen2, executou byte-BPE causal para
três entradas comuns congeladas e obteve os mesmos IDs que o
`llama-tokenize.exe` b10362 offline. Em seguida, o primeiro ID de `Casulo`
selecionou e dequantizou sua linha autêntica no tensor Q6_K
`token_embd.weight`.

Isso ainda não é inferência do Qwen3. O chat template não foi executado,
nenhum bloco Transformer foi avaliado, não existem logits e nenhum token de
saída derivado do modelo foi produzido.

## Fonte e oráculo congelados

| Componente | Identidade |
| --- | --- |
| GGUF | 2.497.280.256 bytes |
| SHA-256 do GGUF | `7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5` |
| Tokenizer | `gpt2`, pre-tokenizer `qwen2` |
| Vocabulário | 151.936 tokens |
| Merges | 151.387 regras |
| Oráculo | `llama-tokenize.exe` b10362, offline |
| SHA-256 do oráculo | `4b63587d19ac1fecabce65aa4e7da41212865cb323804882b9f68ed44a5ec573` |
| System pack válido | `casulo-native-neural-port-system-pack-v3.cspk` |
| SHA-256 do pack | `c209aae87feb8549ddadca6ff6b454060fcb99783d1a07ee5849402baaf0ee4d` |

Hashes integrais das regiões GGUF foram conferidos no guest:

- tokens: `adab67cd4451390df3c68d6b3e74f5095d857769780735c7e7044e571db2a89e`;
- tipos: `fd28e1c1092285f1de6c3c1d3c78105e1a63f503d7eef2fb8cb00017c05c0979`;
- merges: `907981a313a6e78ef2223229042674a39cd4995ee4c4ed40a31b58754e82c26c`;
- chat template: `57f1fd00f0013a2be96aa79b857391f27e23df5b5f847072b524c897e24d0361`.

O template possui 4.100 bytes. NP5 valida sua identidade, mas não o interpreta.

## Equivalência observada

| Entrada UTF-8 | IDs do oráculo | IDs no Native |
| --- | --- | --- |
| `Casulo` | `[49242, 8763]` | `[49242, 8763]` |
| `hello world` | `[14990, 1879]` | `[14990, 1879]` |
| `Olá, Casulo.` | `[42719, 1953, 11, 11054, 8763, 13]` | `[42719, 1953, 11, 11054, 8763, 13]` |

Cada boot varreu 454.161 regras de merge ao total e 106.954 entradas de
vocabulário para os três casos. O algoritmo é causal: as regras e tokens são
lidos do GGUF durante a execução, não codificados como respostas fechadas.

## Escopo honesto do tokenizer

O caminho corrente suporta texto ordinário ASCII e latino bounded, incluindo o
caso pt-BR congelado. Falha de modo explícito para:

- sintaxe de special tokens como `<|im_start|>`;
- scripts não latinos;
- contractions e whitespace de controle ainda não cobertos;
- execução do chat template Jinja.

Esses casos são `Unsupported`, não aproximações silenciosas. Portanto NP5 não
autoriza a alegação de compatibilidade total com o tokenizer Qwen2.

## Embedding autêntico

O token `49242` selecionou uma linha completa de `token_embd.weight`:

| Campo | Valor |
| --- | ---: |
| Tipo | Q6_K |
| Dimensão decodificada | 2.560 F32 |
| Offset absoluto | 109.374.792 |
| Bytes quantizados | 2.100 |
| SHA-256 bruto | `3ba52dc117730ee5d8533687c629c39fa66b96aa6de98a6361e427ccc956886b` |
| SHA-256 F32 decodificado | `3007f5b6e6517db829162dfdfe541d1762cb72ce23676453006db25b699b2d7f` |
| Soma F32 em bits | `3f7e76a4` |

ID fora do vocabulário foi rejeitado antes da leitura da linha.

## Contabilidade do probe

Por boot NP5, o transporte carregou 26.425.728 bytes em 6.554 páginas de cache
e realizou 13.108 operações DMA. Esse total inclui varreduras repetidas de
tokens e merges pelo algoritmo simples de qualificação.

Não é benchmark, working set de inferência nem compressão do modelo. O desenho
correto para produto deverá construir índices bounded/content-addressed em vez
de varrer o vocabulário para cada entrada.

## Falhas encontradas e preservadas

1. O primeiro inventário escreveu JSON UTF-8 corretamente, mas a impressão no
   console CP-1252 falhou ao encontrar `Ġ`. A saída passou a usar escapes ASCII;
   o artifact inicial foi preservado.
2. O builder ainda usava por default o system pack histórico v1. O NP5 neural
   passou, mas o gate global recusou corretamente a primitive Q4 antiga com
   `CASULO_NATIVE_GGUF_PROBE_REJECT=Dot`. O default foi corrigido para v3,
   recebeu teste de regressão e uma terceira imagem append-only foi criada.

Nenhum resultado negativo foi apagado ou reclassificado.

## Validação

| Gate | Resultado |
| --- | --- |
| Testes Python focais NP1–NP5 | 21 PASS |
| Unit tests `casulo-native-model` | 9 PASS |
| Build freestanding release | PASS |
| Smoke final | 1/1 PASS |
| Boots definitivos | 3/3 PASS |
| Seriais definitivos distintos | 1, determinístico |
| Modelo ausente | rejeitado |
| Modelo truncado | rejeitado |
| Rede guest | OFF |
| Dispositivo físico | nenhum |
| Primeiro token de saída | não |

## Artefatos autoritativos

- `release/casulo-native-neural-port-np5-attempt-3.img`;
- `release/casulo-native-neural-port-np5-attempt-3.manifest.json`;
- `outputs/casulo/native-neural-port/2026-08-20-np5/tokenizer-inventory-attempt-3.json`;
- `outputs/casulo/native-neural-port/2026-08-20-np5/qemu-smoke-attempt-2.json`;
- `outputs/casulo/native-neural-port/2026-08-20-np5/qemu-definitive-3boots.json`.

## Próximo gate exato

`NP6_ONE_TRANSFORMER_BLOCK`:

1. implementar RMSNorm F32 bounded;
2. executar matvec Q4_K/Q6_K/F32 sobre tensores reais do bloco zero;
3. implementar Q/K norm, RoPE e grouped-query attention para contexto mínimo;
4. implementar projeções, SwiGLU e residuais;
5. comparar cada tensor intermediário com oráculo independente congelado;
6. introduzir índice/prefetch bounded para evitar varreduras integrais repetidas;
7. manter logits, sampling e token de saída proibidos até NP7/NP8.
