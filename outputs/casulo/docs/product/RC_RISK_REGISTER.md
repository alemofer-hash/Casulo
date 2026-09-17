# Registro de riscos — Revolution Closure

| ID | Severidade | Risco | Gate/controle | Estado RC1 |
|---|---|---|---|---|
| RC-R01 | P0 | perda/corrupção de memória ou criação | hash chain, backup/restore, crash suite | aberto para RC10 |
| RC-R02 | P0 | efeito não autorizado | T + broker deny-by-default | contrato congelado |
| RC-R03 | P0 | privado/secret no public | builds exclusivos + auditoria extraída | baseline PASS |
| RC-R04 | P1 | falsa conclusão sem cumprir HARD | RequirementGraph/evidência independente | contrato congelado |
| RC-R05 | P1 | project bleed | scope obrigatório e holdout de 3 projetos | aberto para RC2 |
| RC-R06 | P1 | prompt injection vira instrução | taint DATA/INSTRUCTION | contrato congelado |
| RC-R07 | P1 | update adulterado/bricking | assinatura, A/B, rollback | aberto para RC10 |
| RC-R08 | P1 | voz bloqueia caminho primário | ASR/VAD/barge/TTS + fallback acessível | aberto para RC8 |
| RC-R09 | P1 | licença TTS incompatível | ledger e decisão explícita | `LICENSE_DECISION_PENDING` |
| RC-R10 | P2 | latência/underrun | thresholds pré-registrados por Machine Profile | aberto |
| RC-R11 | P2 | estética/voz sem aprovação humana | status provisório e rubric de Guilherme | pendente humano |
| RC-R12 | P2 | QLoRA 4B inviável neste host | router pequeno real + defer honesto | deferido |

Stop imediato: integridade do baseline, reserva abaixo de 25 GiB, licença
material sem decisão, consentimento físico ausente, P0/P1 suportado, dispositivo
externo ou tentativa de liberar Cloud.

## Estado no handoff RC13

- RC-R01–RC-R07: controles automatizados aprovados no caminho owner suportado;
- RC-R08: implementação e testes sintéticos aprovados; experiência física é parte da prova humana, não foi simulada;
- RC-R09: o TTS first-party usado no candidato é MIT e não inclui pesos; forks sem decisão continuam fora;
- RC-R10–RC-R12: permanecem P2/limites declarados (latência CPU, timbre provisório e treino 4B deferido);
- P0 automatizado aberto: `0`;
- P1 automatizado aberto no caminho suportado: `0`;
- dimensões exclusivamente humanas: voz, química, beleza, utilidade pessoal e desejo de retorno.
