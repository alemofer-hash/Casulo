# Baseline congelado — Casulo Revolution Closure

- Gate: `RC0_BASELINE_FROZEN`
- Data UTC: `2026-08-14T19:39:42.107943+00:00`
- Branch real: `product/semantic-multiverse`
- Commit de origem: `df12e916c90d9bd2b966326275dc191573f38abd`
- Worktree: substancialmente modificado e integralmente preservado
- Evidência válida: `product-demos/revolution-closure/rc00-baseline-attempt2`
- SHA-256 do gate: `6e3a741006fe6fd1586d3376661d95d9b4f4722321b6d05353b18b4c8f79bb0d`
- SHA-256 do baseline manifest: `4bc45592356cf7051c1f68f910aaf86f2765e93288f82a4d2d32938aad3491e6`

## Pacote vinculante

O ZIP `CASULO_REVOLUTION_CLOSURE_GOAL_2026-08-14.zip` foi extraído em staging
confinado após rejeição de caminhos absolutos, traversal e symlinks. As 22
entradas de `MANIFEST.sha256` foram normalizadas, conferidas e cobrem exatamente
os arquivos do pacote.

| Item | SHA-256 |
|---|---|
| ZIP recebido | `f4bb65711916a50589cb278e2f52c4ce7253e5ddb77853dd52b95f49421efc2b` |
| `MANIFEST.sha256` | `673f35186479340caa31463135ea3abe5e2885eb6cece6de6cdc401ea882a095` |

## Baselines preservados e confirmados

Os quatro hashes do G10, o reseal Semantic Multiverse, a imagem Native, a
evidência Einstein e o archive original da terceira inspeção conferem byte a
byte. O archive original não foi aberto para escrita, normalizado ou
regenerado.

| Fronteira | Estado congelado |
|---|---|
| owner | generativo privado local; Qwen3-4B/llama.cpp verificados |
| human reinspection | `PENDING_GUILHERME` |
| public | 12 arquivos; zero componente privado |
| Cloud | `RELEASE_LOCKED` |
| rede guest | `OFF` |
| USB/block device | `PROHIBITED` |
| QPU | `UNAVAILABLE_DENY` |
| benchmark científico | `NOT_STARTED` |
| assinatura | desenvolvimento, nunca comercial |

## Worktree

O inventário completo `git status --porcelain=v1 -uall` foi selado antes de
qualquer implementação RC. Ele possui 16.494 linhas no freeze válido. Nenhum
`reset`, `clean`, checkout destrutivo, `git add -A` ou novo worktree foi usado.
Por haver um único worktree muito modificado, a opção segura foi continuar nele
com arquivos RC novos e alterações localizadas, sem tentar mover mudanças para
outra árvore.

## Checks read-only

- model doctor: `READY`, sem mutação nem rede;
- Semantic Multiverse doctor: todos os checks aprovados;
- VM doctor: base read-only, WHPX preferido, rede e block devices negados;
- public audit: 12 arquivos, zero achado privado;
- smoke focal: `8 passed in 3.76s`.

A tentativa `rc00-baseline` permanece preservada como falha ambiental: o
`pytest` não pôde usar o `%TEMP%` global (`WinError 5`). A tentativa válida
confinou `TMP/TEMP` ao evidence dir e não alterou o produto para obter PASS.

