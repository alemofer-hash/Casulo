# Roadmap do Casulo como ambiente local de invenção

Data: 2026-08-20  
Estado: `ROADMAP_PROPOSTO; NENHUMA_DEPENDENCIA_INSTALADA`  
Trilha científica: `CONGELADA_NO_CAMINHO_PADRAO`  
Cloud: `RELEASE_LOCKED`

## 1. Objetivo do produto

O Casulo estará pronto como produto quando uma pessoa puder ligar o ambiente,
dar um nome ao Guia e começar a imaginar em voz alta sem conhecer programação,
matemática ou engenharia. O sistema deverá reconstruir a intenção, pedir apenas
escolhas humanas materiais, fabricar em segundo plano e entregar software
executável, corrigível e retomável.

O fluxo-alvo é:

```text
abrir o Casulo
-> presença visual imediata
-> nomear o Guia
-> falar ou escrever uma ideia em linguagem comum
-> conversar sobre experiência e finalidade, nunca implementação
-> reconhecer ou corrigir um espelho curto da intenção
-> confirmar
-> acompanhar a criação ganhar forma enquanto o Guia continua presente
-> simular
-> abrir o software criado
-> pedir uma correção em linguagem comum
-> recompilar somente o subgrafo afetado
-> reiniciar o Casulo e retomar a criação
```

“Entender exatamente” continua sendo um critério operacional, não uma alegação
de leitura de pensamentos. A intenção está suficientemente compreendida quando:

- toda fala possui proveniência;
- fatos, inferências e lacunas estão separados;
- nenhuma ambiguidade material permanece escondida;
- o usuário reconhece o espelho da intenção;
- requisitos técnicos são derivados internamente;
- a criação pode ser corrigida sem perder a versão anterior.

## 2. O que já existe e o que ainda falta

| Superfície | Estado atual comprovável | Lacuna para o produto |
| --- | --- | --- |
| Inferência owner local | Qwen local por `llama.cpp`, sem API externa no caminho owner | carregamento, continuidade, corte por limite e concorrência precisam virar serviço de produto, não processo acoplado à sessão |
| Streaming | protocolo `ASSISTANT_START/TOKEN/END` e streaming real já existem | a melhor interface ainda não consome o fluxo; encerramento por limite precisa continuar semanticamente, sem cortar a frase |
| Interlocução criativa | uma descrição leiga, espelho curto e no máximo uma escolha material | corrigir o espelho por conversa e consolidar alterações incrementais sem reiniciar o fluxo |
| Identidade do Guia | `:nome` persiste identidade validada e hash | onboarding visual e vocal; o usuário não deve conhecer comandos |
| Presence | aceita entrada enquanto jobs rodam e relata receipts reais | quando o runtime neural está ocupado, ainda não existe diálogo neural livre realmente concorrente |
| Voz | rota opt-in, ASR/TTS e cancelamento possuem implementação/testes | captura contínua, endpointing natural, barge-in físico, AEC, qualidade de voz e Device Profile ainda dependem de prova humana |
| Memória | memória persistente, proveniência e retomada existem | controle visual de projetos, isolamento explícito e correção causal da criação atual |
| Creation Field | renderer HTML/SVG puro, dirigido por estados e receipts reais | hoje é uma prova visual separada; precisa ser a superfície central, fluida e integrada |
| Correção | núcleo de reparo, diagnostics e versionamento existem em partes | a fala “muda só isso” ainda não está ligada de ponta a ponta ao artefato vivo e ao subgrafo afetado |
| Materialização | targets e round-trip já possuem provas internas | experiência unificada, dependências, abertura em ambiente limpo e fronteira honesta de “qualquer software” |
| Interface | Tkinter melhorado, conversa, forma, input e menu avançado | ainda parece utilitário técnico; limita motion, composição, tipografia e acabamento |
| Distribuição | launchers e pacotes owner selados existem | executar sem checkout/PYTHONPATH, instalar, diagnosticar, restaurar e atualizar como produto comum |

Conclusão: o núcleo não precisa de outra reescrita. O caminho crítico é uma nova
casca de produto, um runtime conversacional persistente e a ligação causal entre
conversa, criação atual, correção, visualização e materialização.

## 3. Decisão de ferramentas recomendada

Não existe uma única ferramenta que faça pesquisa visual, motion e aplicação
local com a mesma qualidade. A combinação recomendada é:

```text
Figma                 Rive                  Tauri 2
design/fluxo     ->   forma viva      ->   produto Windows local
tokens/protótipo      state machine        Rust + TypeScript + WebView2
```

### 3.1 Ferramenta principal de engenharia: Tauri 2

**Recomendação:** migrar a superfície Hosted de Tkinter para Tauri 2, com
backend Rust, frontend TypeScript e uma camada visual reativa. O frontend
preferido para o primeiro spike é Svelte estável pinado; Web Components puros
permanecem o fallback se a dependência não justificar seu custo.

Razões:

- reaproveita diretamente o renderer HTML/SVG e os eventos JSONL tipados já
  existentes;
- usa a WebView do sistema em vez de empacotar outro Chromium inteiro;
- Rust já pertence à trajetória Native do Casulo;
- IPC e capabilities permitem uma fronteira estreita e deny-by-default;
- sidecars suportam a migração gradual: Python, `llama.cpp`, T Forge e a VM
  continuam atrás de contratos explícitos enquanto partes críticas migram;
- produz janela e instalador de produto sem exigir uma reescrita do motor.

Tauri não transforma o Hosted Profile em Casulo Native. Ele é a casca de
produto correta para validar a experiência agora. A autoridade continua no
motor, em T, nos receipts e no capability broker.

### 3.2 Ferramenta de concepção: Figma

**Recomendação:** usar Figma para o sistema visual, protótipos de alta fidelidade
e testes de fluxo. Variáveis, componentes, condições e transições permitem
avaliar a experiência antes de cristalizar o código.

Restrição: Figma é uma superfície externa. Nenhum código owner, prompt real,
CreationSpec, segredo, modelo, peso ou evidência privada será enviado. O arquivo
de design conterá somente tokens, formas e conteúdo sintético.

Se essa fronteira de privacidade não for aceitável, a alternativa é design
code-first no próprio Tauri. Penpot self-hosted fica como opção futura em uma
máquina com orçamento de disco e operação próprios; não é a melhor instalação
agora neste notebook.

### 3.3 Ferramenta de motion: Rive

**Recomendação:** usar Rive somente para a forma central viva e microinterações.
Sua state machine recebe estados validados do Casulo:

```text
SILENCE
LISTENING
THINKING
FIRST_INTENT
FIRST_FORM
CLARIFICATION
CONFIRMATION
SIMULATION
CORRECTION
AGREEMENT
MATERIALIZATION
RECOVERABLE_FAILURE
```

Rive nunca calcula progresso, escolhe estado nem declara conclusão. Ele projeta
eventos reais produzidos pelo motor. Antes da adoção, licença, plano, formato,
runtime, hash e redistribuição devem entrar no Dependency Ledger.

### 3.4 Alternativas rejeitadas como rota principal

| Opção | Decisão | Motivo |
| --- | --- | --- |
| Tkinter | manter apenas como harness/fallback | insuficiente para motion, composição, tipografia e acabamento de produto |
| Electron | não adotar | Chromium adicional disputa RAM e disco com o modelo local no hardware-alvo |
| Qt/QML | reserva técnica | excelente UI nativa, mas acrescenta toolchain/licenciamento e perde o reaproveitamento imediato de HTML/SVG/eventos |
| Penpot self-hosted agora | adiar | custo operacional e de armazenamento desproporcional ao laptop atual |
| UI nativa própria imediata | não iniciar | seria reescrita prematura; Native receberá um adapter do mesmo protocolo visual depois |

### 3.5 Preflight antes de instalar

O ambiente já expõe Rust, Cargo, Node, npm e pnpm. Antes de qualquer instalação:

1. verificar Microsoft C++ Build Tools;
2. verificar WebView2 Runtime;
3. verificar espaço projetado, licença e hashes;
4. pinar versões e lockfiles;
5. executar um spike descartável fora do caminho owner selado;
6. instalar somente após registrar o plano e o consentimento aplicável.

Não instalar Figma, Rive, Tauri, plugins, fontes ou assets como efeito deste
roadmap.

## 4. A linguagem visual Stark + Jobs

“Stark + Jobs” é uma abreviação interna de duas qualidades, não uma licença
para copiar interfaces, personagens, assets ou marcas existentes:

- **Stark:** tecnologia que parece viva, causal, espacial e instrumental;
- **Jobs:** simplicidade implacável, hierarquia, acabamento e ausência de
  decisões desnecessárias para o usuário.

O resultado precisa ser original e reconhecível como Casulo.

### 4.1 Princípios

1. **Uma presença, não um dashboard.** O centro é o Guia e a forma da criação.
2. **O estado é percebido antes de ser lido.** Motion, luz e som comunicam
   escuta, compreensão, formação, simulação e conclusão.
3. **Texto é conversa, não log.** Diagnostics ficam no modo avançado.
4. **Uma decisão humana por vez.** Nunca formulário técnico ou árvore de opções.
5. **Progresso é causal.** Sem porcentagem, ETA ou animação que não venha de
   receipt real.
6. **Silêncio também é design.** Quando nada ocorre, a forma estabiliza e para
   de consumir recursos desnecessariamente.
7. **Falha preserva confiança.** O ambiente continua vivo, explica em linguagem
   comum e oferece retomar, tentar de novo ou inspecionar.

### 4.2 Gramática visual

Preservar e refinar os tokens existentes:

- fundo `ink` quase preto, sem preto absoluto;
- `ivory` para verdade consolidada e texto principal;
- `amber` para intenção ainda em formação;
- `cobalt/deep_blue` para estrutura, simulação e matéria já organizada;
- `mist` para contexto secundário;
- brilho usado como evidência de atividade, nunca decoração constante.

A forma central não será “um círculo pulsando”. Ela deve evoluir com a criação:

```text
presença difusa
-> linhas de intenção
-> núcleos de requisitos
-> conexões entre capacidades
-> forma simulada
-> forma estável materializada
```

Cada camada visual deve possuir o `event_id` ou `receipt_hash` que a autorizou.

### 4.3 Superfícies do produto

| Superfície | Conteúdo principal | O que fica escondido |
| --- | --- | --- |
| Primeiro encontro | nome do Guia, voz e ritmo | modelos, threads, paths e configuração neural |
| Presença | forma viva, conversa e uma ação primária | logs, universos, manifests |
| Espelho da intenção | imagem curta do que será vivido | RequirementGraph e hipóteses completas |
| Fabricação | forma evoluindo e milestones humanos | stdout, compiladores e diagnostics crus |
| Simulação | comportamento observável e limites | detalhes de sandbox por padrão |
| Resultado | abrir, usar, corrigir, exportar | hashes e SBOM sob inspeção avançada |
| Memória | criações e conversas por significado | banco, índices e projeções |
| Avançado | evidência integral e controles | nada é apagado; apenas não domina o fluxo |

### 4.4 Motion e som

- meta de 60 fps na forma central, com degradação honesta para 30 fps;
- animação reduzida respeitada;
- nenhum loop caro quando a forma está estável;
- transições de 120–450 ms para resposta direta e até 1,2 s para metamorfose;
- tokens aparecem conforme chegam, sem simulação posterior de digitação;
- uma linguagem sonora mínima: presença, acordo, atenção e materialização;
- sem sons de notificação corporativa, vozes robóticas caricatas ou excesso de
  brilho.

## 5. Arquitetura-alvo da experiência

```text
                       CASULO HOSTED PRODUCT

  microfone/teclado
          |
          v
  +--------------------+       eventos tipados       +-------------------+
  | Tauri Presentation | <--------------------------> | Experience Bridge |
  | Svelte + Rive      |                              | Rust, deny-default |
  +--------------------+                              +---------+---------+
       | visual projection                                      |
       |                                                        v
       |       +----------------+     +-------------------+  +---------+
       +------ | Guide Presence | <-> | Local Model       |  | Memory  |
               | turn/barge-in  |     | Service, streaming|  | projects|
               +-------+--------+     +-------------------+  +---------+
                       |
                       v
       IntentTwin -> RequirementGraph -> T Forge -> TCAP/graph
                                                   |
                                                   v
                                 verifier -> simulation -> materializer
                                                   |
                                                   v
                                    artifact/version/receipt/hash
```

Invariantes:

- apresentação nunca concede capability;
- output neural é dado não confiável;
- todo comando do frontend possui schema, escopo e limite;
- o modelo fica quente em um serviço local e não é recarregado por turno;
- resposta, job e cancelamento são streams independentes;
- conclusão tardia de job cancelado não publica artefato;
- o protocolo visual é independente de Tauri para permitir um futuro adapter
  Casulo Native;
- Cloud e public não entram nesta trilha owner.

## 6. Roadmap de execução

As durações são faixas de planejamento para um ciclo concentrado de engenharia
assistida, não promessa de calendário. Um sprint equivale a um vertical slice
que termina em código, testes, demonstração e checkpoint.

### CP0 — Freeze de produto e contrato de prazer (2–3 dias)

**Entrega:** baseline do slice criativo atual, critérios de experiência,
telemetria sem conteúdo e mapa definitivo de estados.

**Gate:** nenhum benchmark científico; owner/public/cloud preservados; replay do
event log atual; orçamento de latência e erro congelado antes da migração.

### CP1 — Spike Tauri e fronteira de processo (3–5 dias)

**Entrega:** janela Tauri separada recebendo o mesmo protocolo tipado da
interface atual, com um sidecar permitido por allowlist e cancelamento real.

**Gate:** sem shell arbitrário, sem rede, sem componentes owner em public,
nenhum dado perdido e renderer antigo continua como fallback.

Decisão no fim do sprint: confirmar Tauri/Svelte ou permanecer em
TypeScript/Web Components. Não migrar o motor ainda.

### CP2 — Sistema visual Stark + Jobs (5–8 dias + revisão humana)

**Entrega:** tokens v2, tipografia licenciável, grid, 12 estados, motion spec,
acessibilidade, reduced motion e protótipo navegável.

**Gate:** três rotas completas no protótipo: conversa, criação e falha
recuperável. Guilherme julga beleza, química e prazer; testes não podem aprovar
isso em seu nome.

### CP3 — Casca de produto e onboarding (4–6 dias)

**Entrega:** tela de primeiro encontro, nome do Guia, personalidade/voz,
presença em menos de uma interação e fallback de texto.

**Gate:** zero comando `:nome` no caminho principal; identidade persiste,
reboot retoma; advanced mode continua disponível sem dominar a tela.

### CP4 — Runtime conversacional fluido (6–10 dias)

**Entrega:** serviço local persistente do modelo, carregamento em background,
fila de turnos, streaming imediato, detecção de parada e continuação semântica
quando o limite corta a resposta.

**Gate:** nenhuma resposta aparece como bloco depois de pronta; nenhum corte
silencioso; cancelamento drena o stream; modelo não é recarregado a cada turno;
falha retorna estado recuperável, nunca traceback.

### CP5 — Interlocução e correção do espelho (5–8 dias)

**Entrega:** conversa livre, espelho editável por linguagem comum, no máximo uma
pergunta experiencial por vez e confirmação material versionada.

**Gate:** zero pergunta sobre API, banco, framework, algoritmo, modelo, hardware
ou arquitetura; uma correção altera o IntentTwin/RequirementGraph sem apagar a
fala ou a versão anterior.

### CP6 — Presence enquanto o Casulo fabrica (7–12 dias)

**Entrega:** scheduler de inferência local com canais separados para presença e
worker. Primeiro tentar time-slicing/prioridade no mesmo modelo; adotar um
modelo auxiliar pequeno somente se a medição mostrar necessidade e após novo
consentimento de download/licença.

**Gate:** o usuário consegue interromper, perguntar, cancelar e continuar uma
conversa durante geração/compilação; toda resposta de progresso deriva de
receipt real.

### CP7 — Voz duplex de produto (7–12 dias + prova física humana)

**Entrega:** captura contínua opt-in, VAD, partial/final, endpointing, TTS
streaming, barge-in, Device Profile e fallback imediato para texto.

**Gate técnico:** nenhum PCM bruto persistido por padrão; interrupção invalida
fala tardia; dispositivos falhos não derrubam a sessão.

**Gate humano:** Guilherme aprova ou rejeita voz, ritmo e turn-taking. Qualidade
de voz não é aprovada por teste sintético.

### CP8 — Creation Field vivo (6–10 dias)

**Entrega:** forma central Rive ou fallback Canvas/SVG integrada ao Tauri,
alimentada por eventos reais e capaz de mostrar intenção, estrutura, simulação,
correção, materialização e falha recuperável.

**Gate:** cada transição visual é recomposta do log; Rive não inventa estado;
idle estabiliza; reduced motion passa; frame budget não compete materialmente
com a inferência.

### CP9 — Artefato vivo, correção causal e versões (8–14 dias)

**Entrega:** a frase “muda só isso” seleciona o requisito e o subgrafo afetados,
gera `IntentDelta`, recompila, simula e materializa nova versão.

**Gate:** parte não afetada preserva hashes; versão anterior permanece
restaurável; conversa sem mudança material não recompila; falha de reparo não
substitui a criação válida.

### CP10 — Projetos, memória e retomada (5–8 dias)

**Entrega:** criação/seleção de projetos em linguagem comum, isolamento de
memória, busca por significado, visão de versões e retomada após reboot.

**Gate:** `project_bleed=0`; “lembra daquilo?” apresenta origem e incerteza;
exclusão/exportação funcionam; HOT reinicia vazio e estado confirmado retorna.

### CP11 — Materialização realmente utilizável (8–15 dias)

**Entrega:** matriz reduzida de targets de alto valor, doctor de dependências,
execução limpa, abertura com uma ação, reimportação e correção.

**Gate:** três criações inéditas e de classes diferentes funcionam fora do
checkout. “Qualquer software” permanece visão; targets e limites reais são
mostrados honestamente.

### CP12 — Empacotamento independente e beta owner (7–12 dias)

**Entrega:** instalador owner, modelo/runtime/sidecars manifestados, doctor
read-only, restore, update reversível, SBOM, hashes e assinatura de
desenvolvimento.

**Gate:** zero dependência do checkout/PYTHONPATH; primeira execução segura;
uninstall preserva exportação escolhida; public continua sem privados; Cloud
continua `RELEASE_LOCKED`.

### CP13 — Prova humana e selo de produto (3 ciclos de 2–4 horas)

**Entrega:** sessões reais de Guilherme sobre conversa, criação simples,
criação complexa/correção e reboot. Falhas P0/P1 são corrigidas e reexecutadas.

**Gate final:** somente Guilherme pode aprovar prazer, química, voz e beleza. O
selo técnico comprova integridade; não substitui o julgamento humano.

## 7. Orçamento total e caminho crítico

Estimativa inicial:

- **10–16 semanas de engenharia concentrada** para um beta owner coerente;
- **2–3 semanas distribuídas** de design/motion e três ciclos de revisão humana;
- o trabalho pode encurtar porque motor, protocolo, streaming, memória,
  compilador e materialização já existem;
- o maior risco de prazo é runtime neural concorrente em 16 GB, seguido da
  correção causal de artefatos arbitrários;
- o acabamento visual não é o maior risco técnico, mas é o maior risco de
  percepção de valor.

Caminho crítico:

```text
CP1 Tauri
-> CP4 runtime persistente
-> CP5 correção da intenção
-> CP6 Presence concorrente
-> CP9 correção causal do artefato
-> CP11 execução fora do checkout
-> CP12 beta instalável
```

CP2/CP3/CP8 formam a trilha visual paralela. CP7 voz começa depois que CP4
estiver estável; caso contrário, voz apenas amplifica a fricção.

## 8. Métricas congeladas antes do beta

As metas iniciais devem ser congeladas em CP0 e ajustadas somente por nova
versão de protocolo, nunca depois de observar um resultado ruim.

| Métrica | Meta inicial |
| --- | ---: |
| presença visual após abrir | <= 1 s |
| input reconhecido pela UI | <= 100 ms |
| primeiro conteúdo warm, mediana | <= 3 s |
| primeiro conteúdo warm, p95 | <= 7 s |
| resposta cortada silenciosamente | 0 |
| perguntas técnicas ao usuário leigo | 0 |
| escolhas humanas simultâneas | <= 1 |
| traceback/stderr cru na interface | 0 |
| conclusão visual sem receipt | 0 |
| publicação após cancelamento | 0 |
| project bleed | 0 |
| versão anterior perdida na correção | 0 |
| dependência do checkout no pacote beta | 0 |
| API externa no owner | 0 |

TTFT depende do host e será reportado com Machine Profile, não como promessa
universal. Beleza, prazer, voz e química não recebem score automático final.

## 9. O que define um beta vendável

O beta owner está pronto para ser demonstrado quando:

1. abre por uma ação e mostra presença imediatamente;
2. a pessoa nomeia o Guia sem comando;
3. conversa por voz ou texto enquanto o modelo carrega e enquanto jobs rodam;
4. cria três softwares inéditos de classes diferentes sem pergunta técnica;
5. toda resposta aparece progressivamente conforme é gerada;
6. nenhuma resposta termina no meio sem recuperação explícita;
7. o usuário corrige uma criação falando e vê somente a parte afetada mudar;
8. o artefato abre fora do repositório, reimporta e reedita;
9. reboot retoma memória e criação sem project bleed;
10. owner funciona localmente sem API externa;
11. falhas são recuperáveis e nunca expõem traceback;
12. Guilherme declara que a sessão é agradável o suficiente para querer
    continuar usando.

## 10. Ordem imediata recomendada

O próximo trabalho não deve começar por desenhar vinte telas. Deve ser:

1. **CP0:** congelar contrato e budgets;
2. **CP1:** construir o spike Tauri lendo o event stream real;
3. **CP2:** prototipar no Figma os quatro momentos decisivos — primeiro
   encontro, conversa, espelho e fabricação;
4. **CP4:** matar recarga, bloco pronto e corte de resposta;
5. **CP5:** permitir corrigir o espelho sem reiniciar;
6. só então integrar a forma Rive e avançar para voz contínua.

O primeiro sinal inequívoco de progresso será o mesmo diálogo que hoje roda no
Tkinter aparecer numa janela Tauri fluida, token a token, com presença imediata,
sem comandos e sem alterar o motor. Isso isola a melhoria de experiência antes
de qualquer migração mais arriscada.

## 11. Claims e fronteiras preservadas

- este roadmap não aprova design final;
- não prova compreensão perfeita nem criação universal;
- não altera ou libera Casulo Native, public ou Cloud;
- não instala dependências;
- não inicia benchmark científico ou energético;
- não atribui progresso visual sem receipt;
- não chama o Hosted Profile de sistema operacional Native completo;
- não autoriza copiar propriedade visual de terceiros;
- a decisão estética final pertence a Guilherme Moura Fernandes.
