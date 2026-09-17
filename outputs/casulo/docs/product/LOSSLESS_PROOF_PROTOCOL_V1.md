# Protocolo v1 das provas reais de compressão sem perda

Congelado em 2026-09-09 antes de qualquer resultado sobre a fonte real.

## Pergunta falsificável

O contêiner Casulo atual reduz o número de bytes necessários para armazenar e
transportar fontes reais, preservando cada byte da entrada, e como ele se
compara com zstd e 7-Zip executados sob o mesmo host?

Não é hipótese deste protocolo que toda entrada seja compressível. Um arquivo
maior que a fonte ou maior que os baselines é um resultado negativo válido.

## Invariantes comuns

- a fonte é imutável durante cada braço;
- o SHA-256 da fonte é calculado em streaming antes da prova;
- cada compressor recebe os bytes originais, sem transcodificação;
- cada resultado é descomprimido e hasheado integralmente;
- `PASS_BIT_EXACT` exige tamanho e SHA-256 restaurados idênticos à fonte;
- resultados com falha de restauração são `INVALID`, nunca vantagem;
- nenhum arquivo sintético é evidência das provas reais;
- inicialização, compressão, restauração e verificação têm tempos separados;
- versões, caminhos e SHA-256 das ferramentas ficam no relatório;
- nenhum resultado de uma fonte autoriza generalização universal.

## Classificação congelada

A comparação de tamanho usa o menor baseline bit-exact.

| Classe | Regra |
|---|---|
| `BREAKTHROUGH_CANDIDATE` | redução da fonte >= 90% e Casulo >= 50% menor que o melhor baseline |
| `SUBSTANTIAL_ADVANTAGE` | Casulo >= 25% menor que o melhor baseline |
| `MATERIAL_ADVANTAGE` | Casulo >= 10% menor que o melhor baseline |
| `SMALL_ADVANTAGE` | Casulo entre 5% e 10% menor que o melhor baseline |
| `COMPETITIVE` | Casulo entre 5% menor e 5% maior que o melhor baseline |
| `NEGATIVE` | Casulo > 5% maior que o melhor baseline |
| `INVALID` | qualquer quebra de fonte, protocolo ou round-trip |

Os limiares foram escolhidos antes dos resultados das fontes reais e não serão
alterados dentro da campanha.

## Prova A — vídeo 8K real

Identidade congelada:

| Campo | Valor |
|---|---|
| Dataset | `VIDEA-8K-60FPS` |
| Página de origem | `https://github.com/talshoura/VIDEA-8K-60FPS-Dataset` |
| Artigo | `https://doi.org/10.1145/3746027.3758278` |
| Arquivo | `000_10sec_8K.mp4` |
| Google Drive file ID | `1L3NwO2tYK5lJ7rKBTYK2C1eI1z2R3fO8` |
| Tamanho remoto esperado | `18.381.885.157` bytes |
| Resolução declarada | `8192x4320` |
| Quadros declarados | `600` |
| FPS declarado | `60000/1001` |
| Licença | não declarada explicitamente na página inspecionada |
| Uso autorizado por este protocolo | avaliação interna; não redistribuir a fonte |

O download só se torna fonte aceita depois de tamanho, SHA-256 e `ffprobe`
locais. O hash local ainda não existia no momento do congelamento e será
acrescentado como observação, nunca escolhido depois do resultado.

Observação acrescentada após a aquisição, sem alterar o protocolo:

- tamanho local: `18.381.885.157` bytes;
- SHA-256 local: `68011a473a3c3f963dfe716620991eb92d87473e9a7204ae323a1dceb0502d24`;
- stream: HEVC, `8192x4320`, `yuv444p10le`;
- duração: `10,010000 s`;
- quadros: `600`;
- taxa: `60000/1001` fps;
- decisão: `SOURCE_ACCEPTED_FOR_INTERNAL_8K_PROOF`.

Braços predefinidos, em ordem rotacionada registrada:

1. Casulo genérico `balanced`, chunks fixos de 4 MiB;
2. zstd 1.5.7, nível 19, uma thread;
3. 7-Zip 26.03, `-mx=9`, uma thread.

A métrica primária é o tamanho do contêiner bit-exact. Tempo de encode/decode,
memória e expansão são métricas secundárias. Análise pixel-exact não substitui
a identidade binária do MP4.

## Prova B — 100 milhões de registros

O candidato de aquisição é ClickBench `hits_compatible`, um conjunto real de
pageviews anonimizadas com 100.000.000 linhas. O arquivo e a representação
exatos serão congelados antes do download. DuckDB 1.5.5 será o oráculo de
contagem e schema.

Se a alegação pretendida continuar sendo “dataset de treinamento”, esta fonte
não será renomeada: ClickBench é uma base analítica. Uma fonte de ML realmente
composta por 100 milhões de exemplos será selecionada como campanha distinta.

O gate da prova B exige, além dos invariantes comuns:

- exatamente 100.000.000 registros segundo o oráculo;
- schema, tipos, nulos e ordem registrados;
- representação recebida preservada na prova bit-exact;
- equivalência lógica de uma forma colunar reportada separadamente;
- bytes por registro e pico de working set.

## Orçamento de armazenamento

Raiz operacional: `C:\CasuloLab`. Reserva rígida: 30 GiB. A prova não começa
se fonte + maior temporário + restauração transitória violarem a reserva.
Restaurações verificadas podem ser removidas imediatamente pelo runner, mas
fontes, arquivos comprimidos, manifests, hashes e relatórios são append-only.

## Fronteira de alegação

Até as duas campanhas reais terminarem, a única alegação autorizada é:

> Existe um núcleo de compressão sem perda determinístico e verificável, e o
> laboratório está adquirindo as fontes reais sob protocolo pré-registrado.

“Compressão próxima de 100%”, “Pied Piper real” ou economia de infraestrutura
global permanecem proibidos sem os bytes observados e replicação independente.
