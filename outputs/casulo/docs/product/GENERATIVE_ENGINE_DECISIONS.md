# Decisões do motor generativo owner

## GE-001 — Modelo é componente, CasuloEngine é o motor

O modelo neural é substituível e não recebe grants, secrets ou acesso livre a
tools. A inteligência owner é a composição entre inferência, Living Memory,
contrato relacional, planner, T Forge, verificação, simulação e materialização.

## GE-002 — Runtime local isolado

O primeiro runtime será llama.cpp oficial atrás de `LocalModelRuntime`, iniciado
com argv estruturado e loopback restrito. Não há shell textual, endpoint remoto
ou SDK comercial. Output do modelo permanece dado não confiável.

## GE-003 — Candidato inicial

Qwen3-4B Q4_K_M foi preferido ao Qwen3-1.7B Q8 porque, neste host, adiciona
aproximadamente 663 MB de peso para uma capacidade nominal muito maior de
diálogo, raciocínio, código e tool use. Ambos são Apache-2.0 e oficiais; a
decisão não é claim de benchmark. A qualidade real continua sujeita à inspeção.

## GE-004 — Criatividade estocástica, consolidação determinística

O caminho normal não fixa seed. Dialogue, planning e code usam políticas
distintas. Schema, capability, compile, sandbox, approvals, transactions e
rollback nunca dependem de sampling.

## GE-005 — Referência determinística sai do artifact generativo

`LocalGuidePolicy` permanece regressão/reference do Product Alpha. Ela não pode
ser importada pelo entrypoint owner generativo nem satisfazer G1–G10. Doubles
continuam permitidos apenas em testes de contratos e são rotulados como tal.

## GE-006 — Inferência host, autoridade no guest

Para não duplicar pesos, a primeira VM usará um bridge first-party estreito e
capability-scoped. O guest contém a experiência e a autoridade owner; o host
executa somente a inferência verificada. Clipboard, shared folder, rede externa
e túnel genérico permanecem ausentes.

## GE-007 — Bridge serial explícito e guest de baixa potência

O Casulo Native habilita interrupções antes do laço `hlt`; sem isso, o guest não
acordava para dados seriais tardios. O transporte envia envelopes versionados e
capability-scoped. O cronômetro do worker só inicia após o receipt do guest, e a
resposta chega antes da consolidação. Tentativas falhas e a causa foram
preservadas; não existe fallback silencioso por shared folder ou rede.

## GE-008 — Texto é fallback honesto do primeiro handoff

O primeiro handoff prioriza o motor generativo e entrega texto pt-BR streaming.
Voz duplex continua requisito do produto, mas não é simulada nem declarada
presente no guest. Química, beleza e voz final continuam sob avaliação humana.

## GE-009 — Artifact owner e public são auditados separadamente

O ZIP owner inclui somente o frontend generativo privado allowlisted e não
embute pesos. O wheel public é auditado como conjunto exato e não pode conter
adapter owner, modelo, secrets ou fallback. Cloud permanece `RELEASE_LOCKED`.

## GE-010 — Reasoning oculto desligado, sampling preservado

O processo llama.cpp inicia com `--reasoning off`. A decisão impede que o
orçamento estruturado seja consumido por tokens ocultos e deixa JSON/conteúdo
visível para auditoria. Temperatura, top-p, top-k, min-p e seed normal continuam
estocásticos; esse parâmetro não converte o motor em fixture determinística.

## GE-011 — Modelo propõe; três autoridades recusam

Saída estruturada precisa passar por JSON, frontend/semântica/Forge T e testes
executáveis. Projetos ou revisões recusados nunca entram na criação. Cada
rejeição preserva operation ID, causa, hash e StochasticTrace. Síntese admite no
máximo dois projetos candidatos; revisão, no máximo três candidatos por reparo;
o loop semântico admite no máximo quatro reparos.

## GE-012 — Testes gerativos precisam ser satisfatíveis

`expected_contains` é substring curta, não serialização de schema ou
CreationSpec. Cada expectativa neural possui até 48 caracteres, a reserva
gerada por unidade é 120 e todos os testes, incluindo holdout humano, precisam
caber no `emit_literal` de 200. Inviabilidade é rejeitada antes do verifier.

## GE-013 — Timeout ocioso distingue CPU lenta de runtime travado

O timeout de socket para inferência local é finito em 180 segundos. O antigo
limite de 30 segundos encerrava prompts legítimos do Qwen3-4B neste i5 antes do
primeiro token. Conclusão com zero conteúdo visível agora é falha terminal, não
`COMPLETED`.
