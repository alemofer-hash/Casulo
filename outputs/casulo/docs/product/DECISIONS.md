# Decisões de produto

## D-001 — Hosted antes da completude native

O Hosted Product Profile valida domínio, voz, memória, Guia, Forge, simulação e
materialização sobre HAL comum. O Native Profile converge sem bloquear a
experiência por ausência inicial de drivers.

## D-002 — Python de referência permanece

Não haverá reescrita total. O compilador e os slices atuais em Python continuam
como referência; Rust entra gradualmente em kernel, serviços long-lived,
segurança, áudio e renderer após contratos e testes de paridade.

## D-003 — Pesquisa é opt-in histórico

Adotada por ADR-0001. Nenhuma medição científica nova integra o caminho padrão.

## D-004 — Cloud nasce locked

O servidor first-party existe desde o monorepo privado inicial, mas produção é
fail-closed. Desenvolvimento public usa somente `CloudTestHarness`.

## D-023 — Cloud standby possui controle real sem superfície de produção

O gateway de desenvolvimento autentica principals exclusivamente test-only,
aplica policy antes de criar job, limita concorrência, sela replay idempotente e
expõe somente métricas agregadas. `CloudReleaseLock.production_bind` falha de
forma incondicional: nenhuma configuração do cliente ou ambiente é caminho de
liberação. Uma futura produção exigirá nova decisão e outro target assinado.

## D-024 — Doctor observa; initializer exige consentimento derivado do plano

O Machine Profile usa somente observacao local e separa campos volateis do hash
de identidade. `doctor`, `plan` e a microcalibracao nao escrevem nem acessam a
rede. A primeira mutacao usa staging confinado, exige a frase literal do plano,
cria memoria protegida e nunca cria conta ou executa download.

## D-025 — Native Product gate separa correcao de pesquisa historica

O gate Native do produto observa somente boot, memoria, isolamento, syscalls,
capabilities e execucao/quarentena TCAP. Ele nao coleta tempo, energia, loss ou
speedup. QEMU usa TCG, rede desativada, imagem regular read-only e nunca recebe
um block device do host.

## D-005 — Fronteira por build, não identidade do usuário

Owner e public são targets mutuamente exclusivos. Nenhum dado de identidade ou
flag runtime pode conceder acesso ao motor privado.

## D-006 — T vNext exige RFC antes de sintaxe

Cada capacidade nova precisa de semântica, AST, diagnósticos, lowering,
IR/grafo, goldens e migração. O atalho `learn` permanece legado até integração
comprovada ou arquivamento.

## D-007 — T/1.1 é opt-in e preserva T/1.0 byte-for-byte

`language T/1.1` habilita expression AST própria, records, enums, `Result`, CFG
e requirements de capability. A serialização T/1.0 remove os campos vNext e o
corpus congelado continua sendo o oráculo de compatibilidade.

## D-008 — Módulos ligam interfaces, não arquivos por convenção

Cada módulo exporta tipos e schemas por uma interface canônica com SHA-256.
`use` liga essa interface; colisões entre imports ou entre import/local são
falhas `T3103`. O hash entra no workspace e no lock de build.

## D-009 — Requirements TCAP nunca são grants

TCAP 1.1 transporta `capability_requirements`; o broker externo continua sendo
a única fonte de grants. TCAP 1.0 permanece o formato padrão para fonte legado.

## D-010 — Memória bruta é cifrada; projeções são descartáveis

O log por evento, com cadeia SHA-256, é a única fonte de verdade da Living
Memory. Índices episódico, semântico, criação e colaboração são reconstruídos.
No Hosted Windows, DPAPI liga ciphertext ao usuário; não existe fallback
produtivo sem criptografia.

## D-011 — Recall ambíguo pergunta, não inventa

Busca lexical/vetorial sempre retorna proveniência. Consulta sem pista ou
resultados próximos produz `AMBIGUOUS`; o Guia pede desambiguação em vez de
escolher silenciosamente.

## D-012 — Voice Duplex é contrato; ASR/TTS são adapters substituíveis

Endpointing, transcript parcial/final, barge-in e integração com `PRESENCE`
pertencem ao produto. Engines e modelos de ASR/TTS são bootstrap substituível,
pinado e licenciado; ausência de ASR pt-BR deve falhar honestamente. Nenhum
modelo é baixado ou ativado sem consentimento e verificação de hash.

## D-013 — Inferência de voz fica fora do loop de presença

Frames são enviados a um processo local por protocolo JSONL limitado e sem
shell; parciais são coletadas de forma assíncrona. Captura e Guide Presence não
aguardam inferência. O registry só habilita o adapter após source receipt,
modelo por hash e bridge first-party verificados.

## D-014 — Adoção de modelo é uma transação explícita e separada do build

`doctor` é somente leitura; `adopt-asr` é o único comando com rede e exige
consentimento literal; `build-asr` opera offline sobre cache verificado. Falha
de hash ou checkout executa rollback dos artefatos criados pela tentativa.
Reexecução sobre cache integralmente verificado não acessa rede.

## D-015 — Maria é fallback buffered, não TTS streaming do produto

O sistema do Windows produz PCM local comprovado, mas exige stream seekable.
Após falha do stdout e travamento do forwarding experimental, a claim de
streaming foi removida. Maria usa buffer seekable e sink cancelável, permanece
não redistribuída e não fecha o gate de TTS streaming/licenciado.

## D-016 — Hosted Windows separa streaming de playback de streaming PCM

`WindowsDirectStreamingTts` envia fala diretamente ao dispositivo padrão pelo
processo isolado do SAPI: playback começa antes do fim da síntese e barge-in
termina o processo. Isso é `streaming_playback=true`, mas continua
`streaming_pcm=false`, Windows-only e não redistribuído. O adapter buffered
permanece para loopback/testes sem dispositivo. A implementação não autoriza
alegar playback físico antes do smoke consentido nem resolve o TTS native ou
cross-platform.

## D-017 — ASR local aceita múltiplos modelos sobre um source selado

Cada modelo possui receipt próprio por SHA-256; o source/bridge pinado é
reutilizado sem novo checkout. `base-q5_1` é o perfil rápido deste i5 e
`small-q5_1` permanece perfil de maior precisão. A seleção vem de micro-medida
de UX local, nunca de campanha científica nem claim geral.

## D-018 — Guide Presence não possui workers nem autoridade generativa

O Guia mantém o diálogo e recebe eventos canônicos de workers, mas não fabrica
progresso, grants ou decisões. `PRESENCE` preempta a apresentação; não cancela
o job por acidente. Adaptações do contrato de colaboração são propostas e só
entram na memória após aprovação humana explícita. Pressão é invariavelmente
zero no mecanismo de adaptação.

## D-019 — IntentDelta é proposto antes de compilar ou alterar a criação

O ingress determinístico inicial aceita somente formas explícitas `defina ...
como ...` e `remova ...`; toda outra fala continua diálogo/clarificação. Um
delta proposto não altera estado. Após “confirmo”, o Forge compila a criação
candidata pelo pipeline T geral e só então efetiva o commit. `affected_paths`
seleciona sementes, mudança de source é sempre detectada e dependentes são
recompilados a jusante.

## D-020 — Creation Field é projeção, não autoridade nem canvas

O Campo consome `CreationSpec`, `IntentDelta` e receipts; nunca inicia trabalho
ou infere progresso. Posições derivam de identidade estável, fingerprints
incluem hashes dos artifacts e relações vêm do grafo de dependências. A
interface visual é orgânica e conversacional; não expõe drag-and-drop como
caminho principal.

## D-021 — Simulação aceita somente doubles estáticos first-party

O runtime não recebe callbacks, brokers reais ou objetos duck-typed. Cada
double é uma instância first-party com respostas pré-registradas, e o preflight
valida toda a DAG/capabilities antes da primeira tentativa. Falhas produzem
caminhos de correção; não grants nem mudanças automáticas.

## D-022 — Materialização publica estado selado, nunca engine nem effect

O pacote local contém criação, receipts, manifest, SBOM, hashes e uma API
loopback simulation-only. Ele não transporta `OwnerEngineAdapter`, pesos,
secrets ou grants executáveis. A exportação é reprodutível e overwrite é
fail-closed; nova versão exige novo package ID.

## D-026 — Budget neural é autoridade do produto, não decisão do modelo

Cada operação neural possui teto próprio de entrada, saída, memória e conversa.
O roteador determinístico exige confirmação/requisito HARD antes de síntese e
diagnostic real antes de reparo. Contexto descartado aparece no receipt. O teto
físico usa bytes UTF-8 mais saída e margem contra os 8.192 tokens do runtime;
policy customizada pode reduzir, nunca ampliar o budget.

## D-027 — T governa adoção matemática; não recebe crédito pela primitive

Uma especialização matemática só entra no owner depois de equivalência,
tráfego lógico, perfil curto e fallback serem verificados. T/2.0 decide a
adoção e o resultado é consumido antes da troca. Python pode executar a
primitive selecionada, mas não reconstruir aprovação. Qwen/llama.cpp,
Whisper/whisper.cpp e kernels estrangeiros permanecem manifestados como tal;
orquestração T não transforma implementação estrangeira em álgebra T.

## D-028 — A interface consome eventos tipados, nunca stdout como estado

Presença, modelo, tokens e jobs atravessam um protocolo JSONL validado. Texto
incidental pode ser mostrado como aviso, mas não cria progresso nem conclusão.
`PRESENCE_READY` autoriza entrada antes de `MODEL_READY`; essa espera é declarada,
não escondida. Milestones exigem evidência com hash e porcentagem/ETA são
proibidos. A interface pode conversar durante trabalho em background sem obter
autoridade sobre o worker; cancelamento invalida publicação tardia.

## D-029 — Native converge o plano de controle antes dos adapters pesados

Hosted e Native compartilham o contrato `casulo.hosted-native-ux-contract/1.0`
por bytes selados e conformance, não por duas descrições semelhantes. O kernel
implementa fila, prioridade, stream e lifecycle bounded; Qwen, áudio, DPAPI,
renderer e materializador permanecem adapters Hosted declarados. Isso permite
migração incremental sem reescrever primitives estrangeiras nem apresentar a
Native Foundation como SO voice-first completo.

## D-030 — A pessoa imagina; o Casulo assume a tradução para engenharia

O caminho principal de criação começa com uma única descrição livre. O usuário
não escolhe linguagem, framework, API, banco, arquitetura, algoritmo, modelo,
servidor ou hardware. O reconstrutor registra essas consequências internamente,
separa explícito de inferido e apresenta apenas um espelho cotidiano da criação.
Uma pergunta só é admitida quando uma escolha humana material permanece aberta,
e precisa falar de experiência, comportamento, prioridade, autonomia, risco ou
gosto observável. Engenharia continua auditável no modo avançado, mas não é
transferida para quem só quer inventar.

## D-031 — Nome do Guia é identidade persistida, não privilégio nem prompt

O nome escolhido pelo usuário é limitado a um identificador humano curto,
persistido atomicamente com proveniência e hash. Ele personaliza presença e
contexto, mas não concede capability, não seleciona edição e não pode carregar
instruções. Owner/public continuam separados por build e supply chain.

## D-032 — Pesquisa científica entra em pausa preservativa

Energia, PyTorch, compressão física e paper gates permanecem preservados, mas
fora do trabalho default desde 2026-08-20. São permitidos apenas testes curtos de
produto, profiling causal de UX e guardas de hardware. Uma retomada científica
requer Goal explícito e nova campanha append-only.

## D-033 — Stark + Jobs é um protocolo de cena; Tauri é seu primeiro adapter

A superfície Hosted usa React/Vite/Tauri 2 porque reaproveita o protótipo e os
eventos existentes sem reescrever o motor. React não ganha autoridade: um
bridge Rust valida bytes, hash, path e lifecycle antes de emitir; o reducer é
projeção pura. O modo sintético é manual, rotulado e inelegível como evidência.

O design será promovido ao Native pela dupla `ProductEvent -> SceneState`, não
pela incorporação de DOM/WebView ao kernel. O scene schema e o event contract
são as fontes compartilhadas; Hosted e Native terão renderers distintos e
conformance semântica. Rive, sidecar empacotado, fonte redistribuível e
installer exigem gates futuros próprios.
