# Casulo HEVC GOP IR v1

Status: `IMPLEMENTED_SHORT_PROBE_PASS`  
Schema: `casulo.hevc-gop-transform-ir/1.0`  
Data: 2026-09-10

## Escopo

Esta IR descreve uma transformação sem perda de amostras HEVC completas
extraídas de um track primário ISO BMFF/MP4. Ela preserva os bytes do fluxo de
amostras, não afirma preservar sozinha o arquivo MP4 inteiro e não representa
pixels decodificados.

O caminho v1 é:

```text
MP4 imutável
  -> sample tables do track HEVC
  -> fronteiras de access units e NAL units
  -> corpus alinhado a amostras e iniciado em IRAP
  -> IR base + dynamics + residual
  -> candidates reversíveis permitidos por T
  -> seleção T anterior ao commit
  -> archive content-addressed
  -> reconstrução independente
```

## Unidade e identidade

A unidade estrutural é o corpo de uma NAL unit. Cada entrada possui identidade
derivada de sua posição, `sample_index`, `nal_index`, tipo, classe, tamanho e
hash do corpo. O corpus possui tamanho e SHA-256 próprios e referencia a
identidade aceita da fonte original.

O parser lê as tabelas `stsz`, `stsc` e `stco/co64`, obtém
`nal_length_size_minus_one` de `hvcC` e percorre todas as NALs com leituras
limitadas ao prefixo de comprimento e ao header de dois bytes. Corpos grandes
não são carregados durante o inventário.

## Partição reversível

Para cada NAL:

```text
base     = prefixo big-endian do comprimento + header HEVC de 2 bytes
dynamics = corpo persistido por transform diferente de raw
residual = corpo persistido por raw
```

Invariante global:

```text
base_source_bytes + dynamics_source_bytes + residual_source_bytes
  == source_bytes
```

Cada byte do corpus pertence a exatamente uma partição. Não há sobreposição,
lacuna, descarte implícito ou preenchimento inventado. `partition_exact` é uma
evidência produzida pelo contador estrutural e é novamente calculada pelo
decoder; não substitui a verificação independente.

## Transforms v1

| Transform | Entrada | Representação | Inversa |
|---|---|---|---|
| `raw` | corpo atual | bytes idênticos | identidade |
| `zlib` | corpo atual | DEFLATE zlib nível 9 | inflate limitado |
| `xor-reference-prefix-zlib` | corpo e referência anterior da mesma classe | tamanho do prefixo, residual XOR comprimido e cauda raw | inflate, XOR com referência e concatenação da cauda |

O candidato XOR usa no máximo 1 MiB do prefixo. A referência precisa ser uma
entrada anterior já reconstruível, identificada por hash. Ausência ou
divergência da referência fecha a operação. A primitive mede e valida sua
própria inversa antes que o resultado seja apresentado a T.

## Autoridade T

As fontes são:

```text
examples/t-v2/compression_hevc_gop.t
examples/t-v2/compression_hevc_gop_force_raw.t
```

Elas atravessam o frontend T/2, análise semântica, IR tipada, grafo, TCAP e
runtime Rust. T executa três decisões:

1. `plan`: determina `RAW_ONLY`, `RAW_ZLIB` ou `RAW_ZLIB_XOR` antes da
   execução das primitives;
2. `decide`: escolhe somente entre candidates presentes, reversíveis e
   medidos;
3. `judge`: aceita o custo total somente quando reconstrução e partição são
   exatas e o archive completo é menor que o corpus.

Python executa leitura, hashing, zlib e XOR, mas não pode ampliar a família
escolhida nem substituir uma decisão T recusada. Cada chamada produz receipt e
trace em cadeia hash.

## Archive e reconstrução

O archive ZIP é `ZIP_STORED`: cada payload já está na representação escolhida.
Ele contém IR, source T, TCAP, receipts, traces, manifest de primitives,
contabilidade e payloads content-addressed.

O decoder `independent_gop.py` usa somente a biblioteca padrão. Ele não importa
encoder, transforms, autoridade nem runtime T. Antes de gravar a saída, ele
valida:

- nomes e conjunto de entradas do ZIP;
- schemas e limites inteiros;
- hashes e seções do TCAP;
- cadeia, ordem, inputs e outputs dos receipts;
- família autorizada versus candidates realmente executados;
- prefixos, headers, offsets e cobertura exata de cada amostra;
- hashes e tamanhos de payloads;
- referência anterior e inversa de cada transform;
- contabilidade `base + dynamics + residual`;
- tamanho e SHA-256 finais.

A publicação da reconstrução é atômica e recusa sobrescrita.

## Contabilidade obrigatória

Cada execução registra, no mínimo:

```text
sample_count
nal_body_count
source_bytes
base_source_bytes
dynamics_source_bytes
residual_source_bytes
candidate_family_counts
candidate_primitive_invocations
candidate_encoded_bytes_total
candidate_encode_ns_observed
candidate_inverse_verify_ns_observed
selected_transform_operations_lower_bound
t_policy_calls
t_receipt_chain_head
```

Tempos de Python são observações de probe, não benchmark de desempenho. Bytes
de candidates são trabalho executado, não tamanho final nem tráfego físico.

## Limites v1

- O agrupamento em GOP usa presença de NAL IRAP; não decodifica slice headers.
- O probe atual contém duas amostras completas, mas não um GOP completo.
- O XOR é bytewise sobre bitstreams HEVC já comprimidos; ele não é motion
  compensation nem residual de pixels.
- Parameter sets carregados fora das samples, tiles, CABAC, reference picture
  sets e dependências de frames ainda não são modelados semanticamente.
- A IR não prova ganho no vídeo integral nem superioridade sobre HEVC.

## Critério de avanço

Antes de executar um GOP completo, o caminho precisa manter memória limitada e
processar payloads em streaming. O próximo modelo deve tratar estrutura
decodificável de parameter sets, slice headers e relações de referência. Uma
transformação que apenas recomprima o bitstream HEVC continua sendo controle,
não a hipótese principal.
