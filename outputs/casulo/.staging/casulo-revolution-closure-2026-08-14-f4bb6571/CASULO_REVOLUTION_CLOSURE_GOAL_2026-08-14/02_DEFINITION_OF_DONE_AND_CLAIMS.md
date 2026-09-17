# DEFINIÇÃO DE PRONTO E POLÍTICA DE CLAIMS

## Estado final

```text
READY_FOR_GUILHERME_CASULO_BETA_HUMAN_PROOF
```

Esse estado significa que uma máquina limpa e suportada consegue iniciar a VM
por um único launcher, o Guia mantém uma sessão longa por voz, constrói uma
criação holdout de ponta a ponta, materializa-a, executa-a fora do repositório,
reinicia e retoma a criação, e entrega a Guilherme um ambiente reversível para
uso livre.

Não significa que Guilherme aprovou a experiência. Só ele pode produzir:

```text
GUILHERME_HUMAN_PROOF_PASS
GUILHERME_HUMAN_PROOF_CHANGES_REQUIRED
GUILHERME_HUMAN_PROOF_ABORTED
```

## DoD dos nove itens

### RC-D1 — Guia

- sessão contínua de pelo menos duas horas é suportada sem confundir projetos;
- retomada após reboot usa memória com proveniência;
- hipóteses, decisões, rejeições e restrições são distintas;
- contradição é apontada com evidência e incerteza;
- Presence conversa durante jobs a partir de eventos reais;
- adaptação relacional é configurável, reversível e não estereotipada;
- química final permanece julgamento humano.

### RC-D2 — Fidelidade semântica

- todo pedido material vira `RequirementGraph` versionado;
- cada requisito duro possui verificador ou justificativa explícita;
- compilar nunca basta para declarar satisfação;
- lacuna epistêmica ou de ferramenta é recusada/explicada;
- reparo pode alterar arquitetura, não só sintaxe;
- holdouts atravessam domínios e incluem ao menos uma aplicação completa.

### RC-D3 — Soberania T

- políticas, intents, transitions, workflows, tests e manifests do produto são
  expressáveis/compiláveis em T;
- toda fuga a Python/C/C++/Rust está em `ForeignBoundaryManifest` tipado;
- nenhuma regra de produto crítica vive exclusivamente em script opaco;
- packages T possuem versões, effects, capabilities, testes e TCAP;
- kernels, drivers, pesos e bibliotecas maduras podem continuar externos.

### RC-D4 — Motor Casulo

- base Qwen permanece declarada como bootstrap;
- registry suporta adapters e especialistas Casulo first-party;
- existe dataset versionado, licenciado e com splits anticontaminação;
- pelo menos um adapter/especialista treinado pelo pipeline Casulo participa de
  uma rota real, se o Machine Profile suportar treinamento seguro;
- caso 4B não seja treinável localmente, isso não é falsificado: adota-se
  especialista menor e registra-se o limite;
- nenhuma afirmação diz que pesos fundacionais foram criados do zero.

### RC-D5 — Semantic Multiverse

- FROZEN/WARM/HOT e deltas são observáveis e reprodutíveis;
- universos irrelevantes permanecem inativos;
- transições preservam constraints, unidades, incerteza e proveniência;
- crescimento de disco é explicado e limitado;
- comparação interna contra caminho de referência usa workload declarado;
- resultados são validação de produto local, não superioridade universal.

### RC-D6 — VM produto

- launcher gráfico/atalho de um clique, sem PowerShell para uso normal;
- doctor automático e erro humano acionável;
- base read-only, overlay, snapshot, restore e recovery;
- nenhuma rede no guest por padrão;
- ponte de aceleração, se ainda necessária, usa RPC first-party estreita,
  autenticada, versionada e sem shell/path arbitrário;
- terminal só aparece em modo técnico opt-in.

### RC-D7 — Voz

- voz é entrada/saída normal, texto é fallback explícito;
- ASR pt-BR passa calibração por dispositivo e casos naturais;
- AEC/NS/AGC e barge-in funcionam em full duplex;
- TTS é local, cancelável e possui cadeia de licença auditada;
- perfil de voz, prosódia e velocidade são substituíveis;
- silêncio e fala durante jobs seguem política humana, não preenchimento vazio.

### RC-D8 — Materialização

- exporta ao menos pacote Casulo, CLI/executável, API local e uma aplicação
  desktop ou web para cenários compatíveis;
- pacote roda sem checkout, `PYTHONPATH` ou cache do desenvolvedor;
- manifest, SBOM, hashes, política, logs e runtime mínimo acompanham o artefato;
- importação/reedição preserva identidade e histórico;
- secrets são referências externas, nunca payload;
- compatibilidade e migração falham fechadas.

### RC-D9 — Segurança

- capability broker único e deny-by-default;
- modelo, memória importada e artefato gerado são não confiáveis;
- sandbox, quotas, cancelamento e rollback cobrem todos os caminhos reais;
- update é assinado, atômico e recuperável;
- prompt/tool injection, path traversal, archive bomb, secret exfiltration,
  stale result e host escape são exercitados;
- nenhuma assinatura de desenvolvimento é apresentada como comercial.

## Claims autorizados após os gates

- “Casulo owner local, generativo e sem API externa no fluxo principal.”
- “A linguagem T governa intenção, composição, efeitos e materialização.”
- “Universos semânticos são ativados sob demanda em workload declarado.”
- “O motor inclui adaptação/especialistas Casulo sobre pesos bootstrap
  declarados.”
- “A VM candidata está pronta para prova humana de Guilherme.”

## Claims não autorizados

- IA, pesos fundacionais ou LLM criados integralmente do zero;
- amigo real, consciência ou QI psicométrico;
- solver geral das equações de Einstein;
- datacenter literal dentro de 32 GB;
- compressão universal sem perda;
- superioridade geral de T, Casulo ou Semantic Multiverse;
- vantagem energética ou quântica;
- ASR perfeito, Native completo ou hardware universal;
- Cloud/release público/comercial prontos;
- segurança absoluta;
- “qualquer coisa” sem o envelope de capacidades declarado.

