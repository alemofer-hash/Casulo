# CASV/0.1 — formato visual causal do Casulo

Estado: `IMPLEMENTED_BOUNDED_VERTICAL_SLICE`

## Finalidade

CASV é um formato audiovisual executável próprio. MP4, HEVC e outros formatos
podem ser fontes de importação, mas não são o conteúdo interno canônico. Um
arquivo `.casv` descreve como reconstruir a mídia a partir de estrutura,
aparência, dinâmica e correções exatas.

O corte 0.1 implementa vídeo bounded RGB8 e `YUV444P10LE`, sem áudio. A rota
generativa aceita apenas RGB8, com retângulos pixel-aligned, materiais de cor,
brilho inteiro e movimento linear. `YUV444P10LE` usa fallback canônico exato.
Existe um importador FFmpeg limitado e um player de referência por pipe para
ffplay, ambos ainda sem decode incremental ou seek. O corte existe para validar
o contrato e a direção do fluxo; ainda não é um codec de vídeo natural nem um
player final.

## Contratos de equivalência

Três contratos são diferentes e não podem ser misturados:

1. `SOURCE_CONTAINER_EXACT`: reproduzir os bytes do arquivo de origem. CASV/0.1
   não promete nem precisa fazer isso.
2. `EXACT_MEDIA`: reproduzir a sequência canônica de pixels RGB8 byte a byte.
   É o único modo aceito em CASV/0.1.
3. `PERCEPTUAL_MEDIA`: preservar percepção dentro de tolerâncias. É futuro e
   sempre deverá ser chamado de compressão com perda.

Quando uma fonte MP4 for usada, a prova principal de CASV será:

```text
decode do MP4 -> mídia canônica X
CASV -> decoder independente -> X'
SHA-256(X) == SHA-256(X')
```

O adaptador oferece duas rotas explícitas:

- `EXACT_AFTER_RGB8_CANONICALIZATION`: RGB8 produzido por FFmpeg; não prova
  identidade com samples nativos de maior precisão;
- `EXACT_FFMPEG_DECODED_NATIVE_SAMPLE_STREAM`: preserva o raw pixel format
  suportado pelo contrato. Em 0.1, isso inclui `yuv444p10le`.

A segunda rota prova identidade com o fluxo decodificado pela versão hasheada
do FFmpeg, não identidade do contêiner comprimido nem equivalência entre todos
os decoders possíveis. Metadados de cor da fonte são preservados como
proveniência, mas ainda não participam do renderer.

O tamanho deverá ser comparado tanto ao arquivo MP4 recebido quanto a baselines
maduros. Comparar somente com RGB cru é insuficiente para alegar vantagem sobre
codecs de vídeo.

## Representação

Para mídia canônica `X`, o encoder propõe:

```text
P = G(B, A, D)
R = X XOR P
X = G(B, A, D) XOR R
```

- `B`: base estrutural e geometria;
- `A`: materiais, cores e brilho;
- `D`: transições temporais;
- `G`: renderer determinístico identificado por versão;
- `R`: residual exato.

Na rota RGB8 generativa, CASV/0.1 armazena `B` e `A` juntos na seção `base`,
armazena `D` na seção `dynamics` e mantém `R` explicitamente na seção
`residual`. Um residual todo zero é representado por `ZERO` e não ocupa seção.
Residual não zero usa `XOR_ZLIB`; zlib é uma primitive declarada, não um
bitstream de vídeo encapsulado.

O encoder também calcula os fallbacks `CANONICAL_ZLIB` e `CANONICAL_RAW`. Isso
garante que a arquitetura possa recusar uma representação generativa pior. Em
formatos sem renderer implementado, a política T marca o candidato generativo
como indisponível antes de escolher o fallback. Um fallback válido continua
sendo CASV, mas não conta como ganho generativo.

## Busca mínima

O encoder não afirma descobrir a descrição mínima absoluta. Esse problema não
é computável em geral. Ele minimiza o comprimento dentro de uma família
congelada de candidatos:

```text
L_candidato = L(base) + L(dynamics) + L(residual)
```

O juiz final usa o arquivo inteiro:

```text
ACCEPT se bytes(CASV) < bytes(mídia canônica)
REJECT caso contrário
```

Provas futuras também deverão publicar:

- tamanho marginal do `.casv`;
- tamanho do runtime/renderer/modelo obrigatório;
- custo cold-system;
- custo amortizado quando o runtime for compartilhado;
- comparação com o arquivo de mídia originalmente recebido.

## Layout binário

Todos os inteiros do envelope são big-endian.

```text
offset  tamanho  conteúdo
0       8        magic CASV 00 01 CR LF
8       8        comprimento UInt64 do manifesto
16      N        JSON UTF-8 canônico
16+N    ...      seções contíguas na ordem manifestada
```

Cada seção possui nome confinado, papel, offset relativo ao payload,
comprimento e SHA-256. Não são permitidos gaps, sobreposição, bytes finais não
manifestados ou nomes que se comportem como caminhos.

### `base`

Binary schema `CVB1`:

- largura, altura, frames e frame rate;
- material de fundo;
- materiais RGB de aparência, acompanhados por um byte de brilho Q8;
- retângulos com posição inicial, dimensões, material e ordem Z;
- brilho ambiente Q8;
- edge mode fixo `PIXEL_ALIGNED_HARD`.

### `dynamics`

Binary schema `CVD1`:

- uma velocidade inteira `(dx, dy)` por retângulo e por frame.

### `residual`

- `ZERO`: residual lógico integralmente zero, sem payload físico;
- `XOR_ZLIB`: XOR integral, comprimido por zlib, com hash da forma não
  codificada e contagem de bytes não zero.

## Determinismo do renderer

O renderer `casulo.rectilinear-rgb8/0.1`:

- usa RGB8;
- resolve brilho com aritmética inteira e arredondamento especificado;
- pinta fundo e retângulos por ordem Z;
- não possui floating point;
- recusa qualquer track que saia da moldura;
- não implementa antialiasing, alpha, gradientes, texturas ou iluminação
  espacial nesta versão.

O decoder independente repete essa especificação sem importar encoder, IR,
autoridade T ou proposer.

## Autoridade T

A política `examples/t-v2/compression_casv.t` atravessa o pipeline geral T/2:

```text
fonte T -> AST -> semântica -> IR -> grafo -> TCAP -> runtime Rust
```

Ela decide antes do commit entre:

- `GENERATIVE_EXACT`;
- `CANONICAL_ZLIB`;
- `CANONICAL_RAW`.

Após o decoder independente, ela julga `ACCEPT` ou `REJECT` pelo custo do
arquivo inteiro. A mutação `compression_casv_force_raw.t` muda a representação
persistida sem alteração em Python.

Escopo ainda estrangeiro e explicitamente não atribuído a T:

- proposição da cena;
- tracking;
- inferência de materiais;
- implementação numérica do renderer;
- zlib.

## Segurança e limites

- manifesto limitado a 4 MiB;
- mídia canônica limitada a 256 MiB no decoder 0.1;
- encoder atual recusa workloads maiores que seu limite in-memory;
- seções são contíguas, hasheadas e fechadas contra trailing bytes;
- zlib é descomprimido com limite declarado;
- output usa publicação temporária e substituição atômica;
- arquivo existente não é sobrescrito sem opção explícita;
- nenhum source container ou bitstream de vídeo é aceito como seção.

## O que abrir um CASV significa

O player de referência atual valida o envelope com o decoder independente e
envia RGB8 ou `YUV444P10LE` por pipe ao ffplay, usando argv seguro e sem arquivo
temporário de mídia. Ele comprova abertura real do formato, mas não é o player
nativo: o decoder ainda reconstrói todo o segmento em memória, não entrega
frames sob demanda e não possui seek. Exportar um MP4 será somente uma ação
posterior de compatibilidade. O `.casv`, e não esse MP4 exportado, é a obra
canônica.
