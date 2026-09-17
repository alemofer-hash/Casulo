# Living Memory v1

## Fonte de verdade

Cada evento ocupa um arquivo próprio em `memory/events/`, cifrado pelo
`SecretBox` do perfil hosted. O nome começa pela sequência decimal fixa; o
conteúdo canônico contém `previous_hash` e `event_hash`. Reabertura verifica
schema, hash, sequência e cadeia antes de produzir qualquer projeção.

Projeções são derivadas e descartáveis:

- episódica: tempo, kind, subject e fontes;
- semântica: índice lexical local;
- criação: último payload e todos os eventos de proveniência;
- colaboração: preferência mais recente e sua história.

A busca combina Jaccard lexical e um vetor local determinístico por hashing.
Isso não é embedding neural nem depende de API. Respostas carregam event IDs;
empates próximos e consultas sem contexto retornam `AMBIGUOUS`.

## Criptografia e secrets

No Hosted Windows, `DpapiSecretBox` usa `CryptProtectData`/
`CryptUnprotectData`, vinculado ao usuário do sistema e sem chave no
repositório. `TestSecretBox` é marcado `production_safe=false` e o runtime o
recusa salvo opt-in explícito de teste. Não existe fallback silencioso sem
criptografia.

Export é plaintext canônico somente quando o usuário o solicita. Delete total
exige a frase literal `DELETE MY CASULO MEMORY`. Sincronização remota e treino
com conteúdo do usuário permanecem negados por padrão.

## Concorrência e limites

V1 admite um writer por perfil. Cada evento é escrito atomicamente, mas lock
multi-processo e compactação não fazem parte deste corte. Tamanho, quota e
streaming de export serão endurecidos antes do release. Corrupção falha fechada;
nenhuma projeção parcial é servida.
