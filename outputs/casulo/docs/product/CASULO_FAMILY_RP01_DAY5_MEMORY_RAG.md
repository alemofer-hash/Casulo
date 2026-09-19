# CASULO FAMILY RP0.1 — Dia 5: memória isolada e RAG local

Data: 2026-09-19
Status: **PASS**

## Resultado

O Family Gateway agora oferece ingestão, busca, reindexação e exclusão de memória autenticada em SQLite/FTS5. O namespace é derivado exclusivamente do dispositivo autenticado; o cliente não escolhe `user_id`. A recuperação híbrida usa FTS5 e o embedding first-party local `casulo-exact-embedding-v1`, sem rede, pesos externos ou alegação neural. As citações internas acompanham o evento `ACCEPTED` e a PWA apresenta sua origem e hashes sem registrar o conteúdo integral no audit log.

O gate real autoritativo é `evidence/family/day5/attempt-5`. Ele integrou o contexto recuperado a uma única geração Qwen2.5-7B Q2_K/Vulkan, por HTTPS no Gateway, enquanto o runtime permaneceu em loopback.

## Fatos comprovados

- Baseline: commit `e575690a71b0d577de8ec66416b5ffe64b876cc4`, tree `7a74c6603df2f4554efbdbf90f0e75a325a665bc`, branch `rp0.1-family`.
- SQLite 3.45.3 com FTS5 foi exercitado pelo runtime da biblioteca padrão; nenhuma dependência de runtime foi adicionada.
- O card do embedding foi verificado pelo SHA-256 `0876987a6ef2ab29f4a93d0b3947b4b08fd3931466c086a90be1978435d36961`.
- Duas identidades (`alice` e `bob`) receberam sessões distintas e documentos com ACL `OWNER_ONLY`.
- Três consultas adversariais de Bob — marcador exato, injeção SQL aparente e `UNION SELECT` aparente — retornaram zero citações do namespace de Alice.
- A tentativa de Bob excluir o documento de Alice recebeu HTTP 404; o identificador não foi revelado como acessível.
- A busca de Alice recuperou uma citação interna com origem e hashes; essa citação foi anexada ao evento `ACCEPTED` do chat.
- Uma geração real Qwen entregou 24 caracteres incrementais e concluiu com evento terminal `COMPLETED`; o runtime ouviu em `127.0.0.1:56834` e o Gateway em `192.168.1.4:56856`.
- O contexto RAG expandido e excerpts permaneceram voláteis; `jobs.sqlite3` persistiu somente a pergunta original e referências hashadas.
- Reindexação recompôs um chunk e a verificação do namespace retornou `PASS`.
- Após exclusão, a busca de Alice retornou zero hits, o documento de Bob permaneceu, e o marcador apagado não foi encontrado no arquivo SQLite nem no WAL após fechamento/checkpoint.
- Audit logs contêm hashes, contagens e identificadores, mas não o conteúdo privado integral nem o owner token.
- O encerramento deixou zero processo `llama-server` e zero listener correspondente.

## Comportamento observado

A tentativa 1 identificou uma suposição incorreta no runner sobre o nome do campo público (`results` em vez de `citations`) e terminou fail-closed. A tentativa 2 comprovou streaming real, porém o limite absoluto padrão de cinco segundos cancelou a geração depois de oito deltas. O default foi corrigido para 300 segundos; a detecção de desconexão continua independente e imediata. A tentativa 3 passou o fluxo, mas revelou que o coletor procurava `CHUNK` em vez de `DELTA` e registrava comprimento zero. A tentativa 4 corrigiu essa instrumentação. A revisão de privacidade então eliminou a persistência do contexto expandido; a tentativa 5 validou esse endurecimento e tornou-se autoritativa.

Durante a tentativa autoritativa, a RAM disponível mínima foi 5.205.594.112 bytes, o working set máximo observado do runtime foi 3.640.262.656 bytes e o disco livre mínimo foi 104.232.906.752 bytes. Não houve violação dos pisos de 1 GiB de RAM e 30 GiB de disco.

## Inferências

O isolamento observado é consequência tanto do filtro SQL por `user_id` autenticado quanto da API que não aceita namespace fornecido pelo cliente. Os testes adversariais e a inspeção dos resultados sustentam o gate de dois usuários, mas não constituem prova formal contra toda classe futura de falha de autorização.

O embedding signed-hash oferece recuperação local determinística e reproduzível. Ele é adequado ao gate offline-first e à busca lexical/semântica limitada adotada aqui, mas não equivale à qualidade de um encoder neural treinado.

## Limitações

- O banco SQLite está em texto claro sob o perfil do usuário do sistema operacional; criptografia de dados em repouso ainda não foi implementada.
- O embedding first-party é uma projeção signed-hash de 64 dimensões, não um modelo neural; recall semântico multilíngue e robustez a paráfrases complexas não foram qualificados.
- As citações são internas e verificam origem/hash do item ingerido; elas não certificam a veracidade externa do conteúdo.
- O purge verificou o banco de memória e WAL fechados desta execução. Saídas de conversas já entregues pertencem ao histórico de jobs e exigirão uma política de retenção própria; não há claim de apagamento físico irrecuperável em SSD.
- A suíte Product exigiu repetição de cinco testes de launchers fora do sandbox porque o Windows Script Host teve acesso à própria configuração negado; os cinco passaram com permissão de host.
- `temperature_monitoring=EXTERNAL_MANUAL_HWINFO`, `temperature_telemetry_collected_by_runner=false`, `temperature_claim=NONE`.

## Ainda não validado

- criptografia em repouso e rotação de chaves;
- migração de schema entre versões instaladas;
- qualidade de recuperação em corpus familiar grande e multilíngue;
- concorrência de ingestão em múltiplos dispositivos físicos;
- backup/restauração seletiva de memória por usuário;
- comportamento sob desligamento abrupto durante mutação.

## Reprodutibilidade

O runner é `scripts/15-verify-family-day5.py`. As tentativas 1–5 foram preservadas em `evidence/family/day5/`; `attempt-5` é a execução autoritativa. `final-receipt.json` resume o gate e `SHA256SUMS.txt` sela todos os arquivos de evidência.

Nenhuma biblioteca térmica foi instalada ou consultada. O usuário permaneceu responsável pelo HWiNFO e por interromper manualmente a execução diante de comportamento térmico inadequado.
