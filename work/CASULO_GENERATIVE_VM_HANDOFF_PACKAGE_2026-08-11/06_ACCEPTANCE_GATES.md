# GATES DE ACEITAÇÃO

## G0 — Alpha preservado

- baseline e worktree inventariados;
- alterações preexistentes preservadas;
- estado P0–P15 reconciliado;
- nenhuma campanha científica iniciada;
- Cloud/public continuam congelados;
- engine determinístico identificado e fora do release owner alvo.

## G1 — Inferência local realmente generativa

- pesos locais verificados por hash;
- licença/model card registrados;
- runtime sem API externa;
- streaming e cancelamento reais;
- sampling normal não usa seed fixa obrigatória;
- execuções repetidas conseguem produzir continuações diferentes;
- model output vem do runtime neural, não fixture/template;
- arquivo malformado e excesso de memória falham com segurança;
- download, se necessário, teve consentimento explícito.

## G2 — CasuloEngine owner generativo

- domínio consome somente `CasuloEngine`;
- build owner liga `OwnerGenerativeEngineAdapter`;
- `DeterministicFakeEngine` ausente do artifact owner;
- nenhum endpoint/SDK comercial;
- eventos streaming possuem operation/provenance;
- cancelamento impede consolidação tardia;
- constraints obrigatórias sobrevivem à seleção de contexto;
- `StochasticTrace` sanitizado existe.

## G3 — Conversa Science Bros

- sem respostas de abertura fixas;
- sem elogio automático;
- sem tom corporativo dominante;
- consegue discordar com razão;
- consegue inferir consequência não dita e apresentá-la como hipótese;
- pergunta quando a ambiguidade muda o agente;
- não interrompe por detalhes irrelevantes;
- mantém fio após barge-in;
- não inventa progresso;
- responde enquanto job roda sem conversa vazia;
- adaptação material do relacionamento exige consentimento;
- nenhuma regra usa diagnóstico, gênero ou estereótipo.

Este gate é contratual. O calor e a química finais permanecem `PENDING_GUILHERME_INSPECTION`.

## G4 — Síntese T generativa

- pedido novo produz `IntentDelta.PROPOSED`;
- confirmação humana separada da geração;
- CreationSpec/T/tests/manifests são gerados de fato;
- frontend -> semantics -> IR -> graph -> TCAP real;
- capability ausente falha;
- modelo não fabrica grant;
- source diff não pode esconder affected paths;
- correção preserva hashes fora do impacto.

## G5 — Reparo e agente inédito

- pelo menos uma tarefa holdout não presente em prompt, fixture ou template;
- candidato passa por compile/test/simulation reais;
- diagnóstico real alimenta reparo limitado;
- limite de tentativas respeitado;
- falha não resolvida aparece honestamente;
- agente materializado executa fora do processo de criação;
- round-trip preserva identidade e versão;
- nenhum efeito real durante simulação.

## G6 — Lifecycle da VM

- doctor é read-only;
- QEMU usa aceleração disponível ou informa fallback;
- OVMF/QEMU identificados e pinados;
- base é imutável;
- overlay é confinada e copy-on-write;
- start/stop/restart funcionam;
- crash/recovery testados;
- QMP não fica exposto;
- disco interno não é montado pelo guest;
- nenhum block device físico é target.

## G7 — Geração dentro da VM

- Casulo Native boota;
- Guide generativo responde dentro do perfil VM;
- voz pt-BR ou fallback explícito;
- barge-in cancela saída;
- memória persiste no owner data;
- conversa cria agente inédito;
- T Forge, simulação e materialização funcionam;
- reboot + “lembra daquilo?” retoma o ponto;
- rede externa não é necessária ao fluxo owner após instalação/cache.

## G8 — Primeira estética Stark + Jobs

- direção visual anterior reconhecível;
- estados visuais vêm de estado/receipts;
- nenhuma telemetria decorativa falsa;
- voz tem prioridade sobre renderer;
- informação não depende só de cor;
- tokens visuais externalizados;
- artefatos registram `design_status=PROVISIONAL_OWNER_REVIEW_REQUIRED`;
- ausência de claim de design final.

## G9 — Inspeção livre e reversível

- snapshot antes da sessão;
- restore reproduzível;
- reset não apaga base nem feedback exportado;
- Guilherme pode usar voz e fallback textual;
- notas de inspeção registram contexto correto;
- feedback é exportável e legível;
- áudio bruto não persiste por default;
- uma falha da VM não corrompe o Alpha ou o host.

## G10 — Handoff

Cenário final automatizado:

1. criar VM de uma base limpa;
2. bootar Casulo;
3. iniciar conversa generativa pt-BR;
4. propor ideia inédita;
5. Guide questiona/elabora com contrato Science Bros;
6. confirmar intenção;
7. gerar e reparar programa T;
8. observar estados vivos;
9. interromper e corrigir;
10. simular;
11. materializar agente;
12. reiniciar VM;
13. retomar criação;
14. criar nota de inspeção;
15. exportar feedback;
16. provar Cloud/USB ausentes.

Estado aprovado:

```text
READY_FOR_GUILHERME_GENERATIVE_VM_INSPECTION
```

## Testes transversais

### Segurança

- prompt injection em memória/model output;
- model/zip bomb;
- path traversal;
- tool argument injection;
- secret exfiltration;
- capability escalation;
- context poisoning;
- late result after cancellation;
- QMP exposure;
- VM path escape;
- overlay/base corruption;
- host command injection.

### Confiabilidade

- model process crash;
- timeout/retry limitado;
- out-of-memory controlado;
- partial stream interruption;
- write transaction recovery;
- snapshot consistency;
- disk quota;
- degraded text-only mode.

### Produto

- nenhuma unidade token na UI normal;
- nenhuma resposta ou progresso falso;
- conversa não morre durante geração longa;
- constraints confirmadas não somem;
- criação não depende de exemplo idêntico;
- usuário pode silenciar e interromper;
- design provisório não bloqueia funcionalidade.

## Evidência

Cada gate registra:

- commit/worktree state;
- comando;
- ambiente e Machine Profile;
- model/runtime hashes;
- resultado;
- logs sanitizados;
- artefatos;
- limitações;
- `PASS`, `FAIL` ou `BLOCKED_EXPLICIT_CONSENT`.

Não usar `PASS` com mocks no caminho generativo owner.

