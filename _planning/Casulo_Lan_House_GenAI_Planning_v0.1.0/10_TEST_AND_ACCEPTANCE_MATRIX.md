# Matriz de testes e aceitação

## Funcional

| ID | Teste | Aprovação |
|---|---|---|
| F01 | chat em português | resposta completa e streaming recuperável |
| F02 | fila com três clientes | exatamente uma geração pesada ativa |
| F03 | cancelamento | job termina e recursos são liberados |
| F04 | troca de modelo | sem processo duplicado ou vazamento de RAM |
| F05 | RAG | resposta aponta documento/chunk correto |
| F06 | patch de código | diff explícito, teste e receipt |
| F07 | rollback | conteúdo anterior restaurado e verificado |
| F08 | voz | ASR -> resposta -> TTS inteiramente local |
| F09 | barge-in | reprodução e geração interrompidas consistentemente |
| F10 | reinício | estado persistente íntegro |

## Segurança

| ID | Teste | Aprovação |
|---|---|---|
| S01 | dispositivo não pareado | 401/403 sem informação sensível |
| S02 | dispositivo revogado | acesso encerra imediatamente |
| S03 | usuário A busca memória B | zero resultados/vazamento |
| S04 | prompt pede shell irrestrito | bloqueio/pedido de aprovação |
| S05 | path traversal | bloqueado e auditado |
| S06 | arquivo com prompt injection | conteúdo tratado como dado, não política |
| S07 | listeners | somente 8443 na LAN; internos em loopback |
| S08 | internet bloqueada | capacidades essenciais continuam |
| S09 | segredo em logs | zero valor secreto |
| S10 | exaustão | limites de fila, tempo e saída funcionam |

## Recursos

| ID | Teste | Aprovação inicial |
|---|---|---|
| R01 | espaço livre | sempre >= 30 GB |
| R02 | RAM | sem paginação sustentada destrutiva |
| R03 | térmica 120 min | sem throttling persistente |
| R04 | crash do modelo | gateway permanece controlável |
| R05 | log/snapshot | limites e rotação respeitados |

## Independência

| ID | Teste | Aprovação |
|---|---|---|
| I01 | DNS/internet bloqueados | chat local passa |
| I02 | chaves externas ausentes | processo inicia e funciona |
| I03 | modelo em cache local | nenhuma tentativa de download |
| I04 | documentação offline | owner consegue recuperar serviço |
| I05 | bundle/backup | restauração em diretório limpo verificada |

## Evidência mínima por teste

- timestamp;
- commit;
- versão/hash do modelo;
- configuração;
- comando ou procedimento;
- resultado esperado/observado;
- logs relevantes redigidos;
- RAM, disco e temperatura quando aplicável;
- PASS/FAIL/BLOCKED.

