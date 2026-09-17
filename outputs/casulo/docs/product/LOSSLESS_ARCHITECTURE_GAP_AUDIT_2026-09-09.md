# Auditoria da lacuna arquitetural da compressão sem perda

Data: 2026-09-09

Estado: `LC4_GENERIC_BASELINE_INTERRUPTED_ARCHITECTURE_GAP_CONFIRMED`

## Addendum — lacuna LC3 fechada em probe curto

Após esta auditoria, a IR reversível, o perfil MP4/HEVC, a representação
`base + dynamics + residual`, cinco transforms, CDC, autoridade T em duas
fases e decoder independente foram implementados. O gate curto está em
`LC3_STRUCTURAL_PATH_IMPLEMENTED_SHORT_PROBE_PASS`; detalhes e limites estão
em `docs/product/STRUCTURAL_COMPRESSION_IMPLEMENTATION_2026-09-09.md`.

Isso supersede apenas as linhas abaixo que dizem `LC3 NÃO IMPLEMENTADO`. Não
promove nem reinicia a campanha LC4 interrompida. O probe líquido expandiu
1,820171%, portanto nenhuma alegação de compressão forte foi criada.

## Veredito

Sim: a execução avançou prematuramente da aquisição da fonte real para uma
campanha grande antes de implementar o núcleo estrutural descrito no próprio
roadmap. O teste não foi falso e os bytes observados são reais, mas ele mede
somente o slice genérico de LC1. Ele não mede a hipótese central pretendida
para o Casulo.

O erro de processo foi tratar "o laboratório já consegue executar uma fonte
real" como se significasse "a invenção a ser julgada já está implementada".

## O que existe de verdade

O caminho `src/casulo/compression` possui sete arquivos Python e 1.305 linhas
físicas na inspeção atual. Seu caminho quente é:

```text
arquivo
-> chunks fixos de 4 MiB
-> SHA-256 de cada chunk
-> deduplicação somente de chunks byte a byte idênticos
-> zlib nível 9 ou raw no perfil balanced
-> ZIP_STORED determinístico com manifest
-> reconstrução e SHA-256
```

O perfil `max`, que não foi usado na campanha, também tenta `lzma` preset 6.
O menor payload vence; se nenhum codec reduzir o chunk, os bytes são guardados
como `raw`.

Isso é uma fundação correta de integridade e empacotamento. Não é ainda um novo
algoritmo estrutural de compressão.

## Evidência direta do código

- `chunking.py` implementa apenas `FixedChunkingPolicy` e
  `iter_fixed_chunks`;
- `codecs.py` delega compressão a `zlib` e `lzma` da biblioteca padrão;
- `archive.py` implementa o contêiner, hashes, deduplicação exata, validação e
  reconstrução;
- não há importação de `casulo.t` no pacote de compressão;
- não há CDC, Rabin, FastCDC, análise de entropia, parser MP4/HEVC, GOP, tiles,
  transformações preditivas, dicionário aprendido, residual, codificação
  colunar, delta, bit packing ou null maps;
- não há decisão atravessando T, AST, semântica, IR, grafo ou TCAP;
- não há runtime nativo Rust/C no caminho medido.

## O que a campanha chegou a provar

A fonte é um vídeo HEVC real de 18.381.885.157 bytes, 8192x4320, 600 frames.
Na retomada, dois braços chegaram a uma nova restauração integral:

| Braço | Arquivo | Redução da fonte | Round-trip |
|---|---:|---:|---|
| Casulo genérico LC1 | 18.361.315.876 bytes | 0,1118997362% | bit-exact PASS |
| zstd 1.5.7 nível 19 | 18.368.104.490 bytes | 0,0749687362% | bit-exact PASS |
| 7-Zip Ultra | parcial de 9.149.145.762 bytes | indisponível | interrompido/não validado |

O Casulo genérico possui 4.383 referências e 4.383 chunks únicos:
`deduplicated_bytes = 0`. Portanto, nessa fonte, a deduplicação por chunks
fixos não eliminou byte algum. A pequena redução veio do codec estrangeiro
aplicado aos chunks, menos o overhead do contêiner.

Esses números não são o relatório final da campanha: `report.json` não existe
e o braço 7-Zip não terminou. Eles permanecem evidência de engenharia parcial,
não prova comercial.

## Onde a ordem do roadmap foi quebrada

O roadmap vinculante declara:

1. LC2: aquisição real;
2. LC3: perfil estrutural de vídeo;
3. LC4: primeira prova 8K;
4. LC5: perfil estrutural de 100 milhões de registros;
5. LC6: prova do banco;
6. LC7: autoridade T;
7. LC8: runtime nativo e produto.

O estado real é:

| Marco | Estado real |
|---|---|
| LC0 | PASS |
| LC1 | PASS como fundação genérica |
| LC2-A | PASS para aquisição do vídeo |
| LC2-B | não concluído para a fonte de 100 milhões |
| LC3 | NÃO IMPLEMENTADO |
| LC4 | iniciado prematuramente apenas com LC1; interrompido |
| LC5 | NÃO IMPLEMENTADO |
| LC6 | NÃO INICIADO |
| LC7 | NÃO IMPLEMENTADO |
| LC8 | NÃO IMPLEMENTADO |

Logo, a campanha iniciou LC4 sem LC3. O protocolo até registrou que o braço
"Casulo estrutural" só entraria se estivesse implementado antes do resultado;
ele não estava e não entrou.

## Arquitetura mínima que precisa existir antes de outra prova grande

### 1. Contrato de transformação reversível

Formalizar uma IR de compressão que represente:

```text
fonte
-> análise somente leitura
-> decomposição estrutural
-> estado base explícito
-> dinâmica/deltas
-> residual completo
-> codificação entropy-aware
-> reconstrução independente
```

Todo estado necessário ao decoder deve estar no arquivo ou ser uma dependência
content-addressed contabilizada. Modelo, dicionário ou base externa escondida
não pode desaparecer da razão de compressão.

### 2. Perfil estrutural de vídeo real

Antes de comprimir, medir e registrar:

- entropia e compressibilidade por região;
- estrutura ISO-BMFF/MP4 e atoms;
- streams, sample tables e metadados;
- limites de unidades HEVC, GOPs e tiles quando parseáveis;
- repetição intra-arquivo e entre arquivos;
- custo do residual necessário para reconstrução bit a bit.

Separar reversivelmente contêiner e bitstream não garante economia. Como HEVC
já é comprimido, qualquer ganho grande precisa de um mecanismo causal explícito
e do residual integral contabilizado.

### 3. Família real de transformações

Implementar e ablar, ao menos:

- content-defined chunking;
- dicionários content-addressed;
- delta/xor preditivo reversível onde houver estrutura;
- seleção por entropia e custo total;
- compactação de metadados e tabelas estruturais;
- residual fail-closed;
- fallback raw quando transformar aumenta o arquivo.

### 4. Caminho de dados tabulares separado

Para 100 milhões de registros, implementar schema reversível, projeção
colunar, dicionário, delta, RLE, bit packing, null maps e preservação de ordem.
Vídeo e tabela não devem fingir compartilhar a mesma matemática apenas porque
usam o mesmo contêiner.

### 5. Autoridade T causal

Somente depois de as transformações existirem, T deve decidir segmentação,
transformação, dicionário, working set, fallback e aceitação. Uma mutação
isolada em T precisa mudar a execução ou produzir recusa. Strings, manifests
posteriores ou wrappers valem zero.

### 6. Gates antes do próximo arquivo gigante

Outra campanha de muitas horas fica proibida até que:

- exista ao menos um perfil estrutural implementado, não só documentado;
- cada transformação possua round-trip, corrupção e limite de memória testados;
- corpus de desenvolvimento e holdout sejam separados;
- tamanho total inclua índices, modelos, dicionários e residual;
- o Casulo genérico seja tratado somente como controle;
- o plano indique qual mecanismo espera remover quais bytes;
- um probe curto confirme que o caminho estrutural realmente foi executado;
- o verificador independente consiga reconstruir sem importar o encoder.

## Decisão

A campanha `2026-09-09-video8k-proof-v1-live-attempt3` está congelada como
`INTERRUPTED_FOR_ARCHITECTURE_AUDIT`. Seus artefatos não serão apagados nem
promovidos a resultado final.

O próximo trabalho correto não é reiniciar o 7-Zip. É fechar a especificação da
IR reversível, implementar o perfil estrutural de vídeo e demonstrar em probes
curtos que ele executa trabalho distinto do contêiner LC1. Somente então uma
nova campanha 8K recebe identidade própria e protocolo congelado.
