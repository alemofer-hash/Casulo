# GOAL AUTÔNOMO — PROVA ENERGÉTICA CONFIRMATÓRIA DA COMPRESSÃO OPERACIONAL GOVERNADA POR T

Status: `DRAFT_FOR_PROTOCOL_FREEZE`

Este Goal estrutura a próxima trilha científica do Princípio da Interlocução.
Ele não inicia medição, não compra instrumento, não modifica o produto e não
autoriza alegação energética. A execução confirmatória somente começa depois
de protocolo, instrumentos, workloads, contratos, análise e equipes terem sido
congelados por identidade verificável.

## Mandato

Construir e executar uma replicação independente, multi-host e fisicamente
instrumentada que responda, separadamente, às seguintes perguntas:

1. qual é o custo energético da governança T quando o kernel numérico é
   exatamente o mesmo;
2. qual é a energia do sistema integrado governado por T contra baselines
   transparentes e stacks nativos otimizados;
3. quando T reduz trabalho permitido pelo contrato semântico `R`, essa redução
   permanece líquida depois de incluir compilação, receipts, auditoria,
   julgamento e publicação;
4. a direção e a magnitude do efeito sobrevivem a workloads, hosts,
   operadores e instrumentos independentes;
5. até qual escala os resultados autorizam falar em redução energética, sem
   extrapolar de uma rede pequena em CPU para GPU, cluster ou datacenter.

O objetivo não é recuperar o fator histórico de `656×`, formalmente
invalidado. O objetivo é medir o que realmente acontece. Resultado neutro,
heterogêneo ou desfavorável deve ser preservado.

## Baseline científico imutável

Preservar como evidência histórica:

- campanha `2026-08-18-interlocution-live-instance-attempt1`;
- `A_T=9/9=1.00` sob a métrica congelada;
- nove mutações causais com efeito fail-closed;
- equivalência operacional de FloodSurrogate e dois holdouts;
- zero falso `PASS` nos ataques implementados;
- razão D/A de wall time observada no host original;
- custo D/C positivo da governança;
- energia de pacote e energia total como `null/UNAVAILABLE` na campanha TI10;
- campanha full-worker interrompida em `0/21` pares;
- calibração TCAP isolada sem braço comparável;
- errata que invalida o fator energético `656×` e proíbe sua correção por
  multiplicação;
- separação do canário de oito registros e da unidade científica de 1.024
  registros.

Nenhum resultado anterior pode ser renomeado como energia confirmatória.

## Formulação operacional

Para um contrato confirmado `R`, sejam:

```text
P_ref       processo de referência
P_T         processo governado por T
V_R         verificador independente
J_wall(P)   joules totais medidos na entrada elétrica do sistema
J_pkg(P)    joules do domínio CPU package, quando válidos
W(P)        vetor de trabalho executado
O_T(P)      overhead de interlocução automatizada, compilação, autoridade,
            receipts, auditoria, julgamento e publicação dentro do escopo
```

Uma amostra energética somente é admissível quando:

```text
P_T ≡_R P_ref
AND V_R(P_T)=PASS
AND V_R(P_ref)=PASS
AND work_receipts_complete=true
AND instrument_valid=true
AND thermal_and_power_guards=PASS
```

Definir, sem agregação posterior oportunista:

```text
rho_wall = J_wall(P_T) / J_wall(P_ref)
rho_pkg  = J_pkg(P_T)  / J_pkg(P_ref)
compression_wall = 1 - rho_wall
compression_pkg  = 1 - rho_pkg
```

`compression_wall` é a coordenada energética primária. `compression_pkg` é
secundária e não pode ser chamada de energia total. Tempo, TDP, temperatura,
utilização, RSS, ciclos e taxa de carga da bateria nunca substituem joules.

## Escopos temporais obrigatórios

Medir e publicar separadamente:

1. `S0_KERNEL_STEADY`: apenas execução numérica síncrona;
2. `S1_GOVERNED_POSTCOMPILE`: autoridade T, execução, receipts, verificação,
   julgamento e publicação;
3. `S2_COLD_CONTRACT_REALIZATION`: inicialização, imports, compilação e `S1`;
4. `S3_INTENT_TO_ACCEPTED_ARTIFACT`: interlocução automatizada, compilação,
   execução e aceitação, somente quando o protocolo de interação tiver começo,
   fim e equivalência próprios.

Cada pergunta científica tem uma única métrica primária pré-registrada:

- custo causal da governança: `S1`, contraste D/E, mesmo kernel;
- eficiência do sistema integrado: `S2`, contraste D/F e D/A;
- compressão semântica de trabalho: joules até qualidade aceita, incluindo todo
  overhead automatizado congelado;
- experiência humana `S3`: exploratória até existir interação reproduzível.

Não misturar escopos no mesmo intervalo ou no mesmo claim.

## Modos de trabalho

### Modo I — trabalho fixo

Os braços executam exatamente os mesmos dados, batches, epochs, forwards,
backwards, optimizer steps, dtype e inicializações. Esse modo mede diferença de
stack e overhead. T não recebe crédito por eliminar trabalho porque nenhum
trabalho contratual pode ser eliminado.

### Modo II — treino até contrato de qualidade

O contrato congela dataset, split, métrica, limiar de qualidade, orçamento
máximo, stopping, tolerância, seeds e conjunto de avaliação. Os braços podem
executar quantidades diferentes de trabalho. O estimando é:

```text
joules totais por execução que alcança qualidade aceita
```

Receipts registram o trabalho efetivamente executado. Par que não atinge a
qualidade não é uma amostra energética favorável; é falha ou não convergência
segundo a regra pré-registrada.

## Estados terminais permitidos

```text
PASS_TOTAL_SYSTEM_ENERGY_REDUCTION_DELIMITED
PASS_CPU_PACKAGE_ENERGY_ONLY_DELIMITED
PASS_CAUSAL_AUTHORITY_ENERGY_INCONCLUSIVE
NO_NET_TOTAL_SYSTEM_ENERGY_REDUCTION
HETEROGENEOUS_ENERGY_EFFECT_SCOPE_DELIMITED
FAIL_SEMANTIC_EQUIVALENCE
FAIL_T_CAUSAL_AUTHORITY
FAIL_INDEPENDENT_VERIFICATION
BLOCKED_PHYSICAL_INSTRUMENT
BLOCKED_THERMAL_OR_POWER_QUALITY
BLOCKED_INSUFFICIENT_EXTERNAL_SCALE
BLOCKED_EXPLICIT_CONSENT
IN_PROGRESS_CHECKPOINTED
```

Nenhum estado autoriza automaticamente claim sobre GPU, datacenter ou modelos
maiores que os efetivamente medidos.

## EC0 — Preservação, isolamento e cadeia de custódia

Antes de mutar:

- ler todos os `AGENTS.md` aplicáveis;
- registrar branch, commit, worktree e arquivos não rastreados;
- verificar manifests, SHA-256 e erratas da campanha atual;
- criar trilha append-only `research/interlocution/energy-confirmatory/`;
- criar campaign ID novo por tentativa;
- impedir qualquer escrita em release owner, public, Cloud ou Native Product
  Gate;
- manter Cloud `RELEASE_LOCKED`, APIs externas proibidas e USB/block devices
  fora do protocolo;
- publicar o digest do protocolo por canal institucional independente antes
  da primeira amostra definitiva;
- usar assinatura digital real ou assinatura institucional destacada para o
  preregistro; `DEVELOPMENT_NOT_COMMERCIAL` continua sendo rótulo, não
  assinatura.

## EC1 — Fechar lacunas causais antes de energia

Energia não começa enquanto estes gates não passarem:

1. o comparador deve consumir a tolerância emitida por T; remover o literal
   `1e-9` duplicado em Python como fonte decisória;
2. o juiz deve receber e verificar a raiz do contrato, o digest da evidência e
   o identity seal da primitive, não apenas strings `PASS`;
3. o publisher deve verificar a mesma raiz que o juiz julgou;
4. o worker deve validar runtime ID, source hash, IR hash, input/output hash,
   foreign calls, fields exatos e ausência de fallback afirmativo;
5. o verificador independente deve receber fontes T, TCAP, executable,
   toolchains e primitive manifest;
6. counters e `final_loss` do receipt devem ser comparados aos bytes do
   resultado, não apenas a constantes esperadas;
7. o hash da primitive executada deve ser validado contra o handle/binário que
   realmente foi lançado, reduzindo TOCTOU;
8. o evento humano confirmado deve ser ligado ao input do juiz por hash;
9. receipts de trabalho devem ser produzidos no ponto mais próximo possível do
   executor e vinculados a um monitor independente; hashes posteriores do
   supervisor não podem ser descritos como assinatura do kernel;
10. o braço sem T deve usar exatamente a mesma primitive do braço governado,
    permitindo identificar o custo causal da governança.

Gate: `CAUSAL_BINDINGS_FOR_ENERGY=PASS`.

## EC2 — Corrigir a infraestrutura energética existente

Antes de conectar instrumento físico, adicionar regressões para estas lacunas
do runtime atual:

- normalizar energia por `K_completed` comprovado por receipts, nunca por
  `sample["K"]` solicitado;
- persistir `K_requested`, `K_frozen`, `K_dispatched`, `K_started` e
  `K_completed`;
- calcular potência média com o `K` e a duração da própria amostra, não com o
  primeiro `K` encontrado para uma implementação;
- distinguir desenho incompleto, falha física, falha de equivalência e ausência
  de vantagem em estados terminais diferentes;
- aceitar medidor físico de energia cumulativa e medidor físico de potência
  amostrada, integrando potência por timestamps reais e interpolando os limites
  da janela;
- exigir amostras que bracketem início e fim e rejeitar gaps, regressões,
  autorange, clipping ou mudança de range não permitida;
- permitir desktop sem bateria; exigir controle validado de bateria somente em
  hosts que a possuam;
- importar export assinado do controlador externo sem exigir que o SUT leia o
  instrumento durante a janela;
- implementar schemas para identidade do medidor, número de série, firmware,
  range, uncertainty, calibration date, calibration traceability e clock
  uncertainty;
- separar HWiNFO como guarda/telemetria exploratória; ele não satisfaz a
  métrica total-system confirmatória;
- substituir o default histórico de 21 pares pelo desenho pré-registrado novo;
- suportar análise hierárquica multi-host sem reduzir todos os pares a uma
  única mediana plana.

Testes obrigatórios: contador cumulativo, integração trapezoidal, interpolação
de borda, gaps, wrap/reset, range change, relógios desalinhados, amostra
parcial, mock rejeitado, instrumento sem calibração, K incompleto, receipt
duplicado, desktop sem bateria e notebook com bateria instável.

Gate: `ENERGY_RUNTIME_V2=PASS`.

## EC3 — Qualificação metrológica do instrumento

A métrica primária exige analisador físico entre a fonte elétrica e o sistema
sob teste. Preferir equipamento aceito pela metodologia SPEC ou qualificado por
processo equivalente.

Requisitos mínimos:

- True RMS e leitura de potência/energia adequadas ao range do SUT;
- incerteza total AC menor que 1% no range efetivamente usado, ou justificativa
  metrológica pré-registrada mais estrita que o menor efeito material buscado;
- calibração rastreável e realizada nos 12 meses anteriores;
- pelo menos uma leitura por segundo; usar a maior frequência confiável do
  instrumento sem degradar exatidão;
- ao menos 60 amostras válidas por janela, com duração ampliada por unidades
  completas independentes;
- controle externo de start/stop ou alinhamento validado;
- autorange desabilitado durante a medição;
- range, crest factor e carga máxima dentro das especificações;
- instrumento instalado entre a fonte AC e o SUT, sem componente ativo
  intermediário não declarado;
- computador controlador separado sempre que possível;
- certificado, serial, firmware, configuração e incerteza incluídos no pacote;
- controle conhecido de carga para provar resposta, resolução e sincronismo.

Segurança elétrica segue o fabricante e um profissional qualificado. O agente
não instala, abre ou conecta equipamento de rede elétrica autonomamente.

Gate: `TOTAL_SYSTEM_METER_QUALIFIED=PASS`.

## EC4 — Fronteira física do sistema

Congelar o que pertence ao SUT:

- host, CPU, memória, armazenamento e aceleradores participantes;
- fontes de alimentação e conversão AC/DC;
- displays, storage remoto, rede/interconnect e cooling, marcando cada item como
  incluído, medido separadamente, estimado apenas em análise exploratória ou
  excluído;
- energia do controlador do medidor excluída do SUT;
- em multi-node, medir todos os nós participantes e interconnect segundo regra
  pré-registrada;
- em notebook, remover/estabilizar/contabilizar bateria; se o fluxo não puder
  ser controlado, bloquear `TOTAL_SYSTEM_WALL` para esse host;
- RAPL apenas em bare metal e somente leitura, com `energy_uj`,
  `max_energy_range_uj`, avanço controlado, wraparound e topologia de zonas;
- nunca somar package e subzonas sobrepostas.

Gate: `SYSTEM_BOUNDARY_FROZEN=PASS`.

## EC5 — Braços e contrastes causais

Implementar e congelar:

- `A`: baseline transparente, inicialmente PyTorch Eager, sem T;
- `B`: mesmo executor de A, auditoria T pós-fato ignorada;
- `C`: T arquiteta e seleciona primitive AOT, aceitação estrangeira;
- `D`: T arquiteta, audita e julga; publisher exige `PUBLISH`;
- `E`: exatamente a mesma primitive, executable, wrapper, flags, processo,
  dtype e matemática de D, porém escolha/aceitação estrangeira sem T;
- `F`: melhor stack nativo disponível e congelado para o ecossistema de
  referência, incluindo `torch.compile`/Inductor quando aplicável e estável.

Contrastes:

```text
B/A = custo de T pós-fato sem autoridade
D/C = custo incremental de auditoria, julgamento e publicação
D/E = custo causal da governança T com kernel idêntico
D/A = comparação do sistema integrado com baseline transparente
D/F = comparação do sistema integrado com stack nativo otimizado
```

`E` e `F` são obrigatórios para qualquer claim que atribua mecanismo a T ou
compare com o ecossistema PyTorch. Compilação incluída e excluída são campanhas
ou escopos distintos. Não chamar D/A de velocidade intrínseca da linguagem T.

Gate: `SAME_KERNEL_IDENTIFICATION=PASS`.

## EC6 — Workloads e escada de validade externa

Congelar antes dos resultados:

### Nível L0 — conexão histórica

1. FloodSurrogate integral: 1.024 registros, 400 épocas, 1.228.800 visitas nos
   três casos, float64;
2. regressão linear/MAE;
3. classificação logística/BCE com working set parcial.

### Nível L1 — novas estruturas

4. CNN pequena com dataset, convolução, padding, layout, qualidade e optimizer
   congelados;
5. atenção/Transformer pequeno com sequência, máscara, posição, qualidade e
   optimizer com estado congelados.

### Nível L2 — escala intermediária

- ao menos três tamanhos predefinidos por família, incluindo um que pressione
  memória e movimentação de dados sem exceder a capacidade segura dos hosts;
- minibatches, optimizer com estado e, em protocolo separado, mixed precision;
- nenhuma redução de shape, dataset ou qualidade depois de observar consumo.

### Nível L3 — acelerador externo

- GPU física em laboratório, com total-system wall energy primária;
- board telemetry apenas secundária;
- kernels/frameworks nativos comparáveis;
- CNN e atenção/Transformer em escala suficiente para que o acelerador seja o
  caminho natural, não um overhead artificial de lançamento.

### Nível L4 — sistema distribuído

- múltiplos nós, todos medidos;
- comunicação, interconnect, storage e data pipeline dentro de fronteira
  declarada;
- contrato de qualidade inspirado em benchmark público, sem usar a marca ou
  alegar resultado MLPerf se as regras oficiais não forem integralmente
  satisfeitas.

Cada nível fecha apenas seu próprio claim. Resultado L0 não autoriza falar em
GPU; L3 não autoriza datacenter; L4 não autoriza universalidade.

Gate por workload: `WORKLOAD_CONTRACT=PASS`.

## EC7 — Equivalência e informação preservada

Cada workload deve declarar `R` antes da medição:

- identidade do dataset e splits;
- inicialização e seeds;
- precisão e determinismo esperado;
- arquitetura e operações obrigatórias;
- loss, optimizer, estado e update;
- working set e data order;
- stopping;
- qualidade, tolerâncias e invariantes;
- outputs observáveis;
- efeitos permitidos e proibidos;
- política de aceitação.

O verificador independente compara, conforme o modo: perdas, parâmetros,
predições, qualidade, finitude, counters, work receipts, optimizer state,
stopping reason e ausência de cache/replay. Tolerâncias possuem rationale
numérico específico por workload e não podem ser relaxadas após resultado.

Gate: `OPERATIONAL_EQUIVALENCE=PASS` por par antes de energia.

## EC8 — Autoridade causal e compressão de trabalho

Reexecutar 9/9 mutações e acrescentar decisões específicas de CNN/atenção sem
alterar retrospectivamente o denominador original. Para provar compressão de
trabalho, não basta uma mutação que pare na incompatibilidade da ABI. Exigir
variantes suportadas em que uma mudança exclusiva da política T altere
causalmente:

- working set executado;
- stopping efetivo;
- primitive selecionada;
- plano de memória/layout quando pertencente a `R`;
- quantidade de trabalho até qualidade aceita.

Python/C/C++ podem executar a primitive, mas não podem recomputar o `PASS` nem
substituir silenciosamente a decisão T. O receipt deve ligar decisão,
configuração, trabalho e resultado.

Gate: `T_CAUSAL_WORK_REDUCTION=PASS` para qualquer claim de que T eliminou
trabalho, em vez de apenas selecionar um executor mais leve.

## EC9 — Piloto, resolução e potência estatística

Executar piloto separado e excluído do confirmatório para:

- estimar variância por host/workload/braço;
- escolher range do instrumento;
- calibrar K de unidades completas e independentes;
- assegurar `max(60 s, 60 amostras)` por janela, ou janela mais longa exigida
  pela resolução/incerteza;
- medir overhead do observador;
- definir cooldown e banda de temperatura inicial;
- calcular tamanho amostral para o efeito material pré-registrado.

K pode diferir entre braços somente em análise matched-duration e deve ser
normalizado por unidades completas provadas. A campanha de trabalho equivalente
usa K comum quando tecnicamente possível. Casos têm nonces, inicializações e
receipts únicos; não há replay ou repetição de output.

O piloto pode elevar o tamanho da campanha, nunca reduzi-lo oportunisticamente.

Gate: `PILOT_EXCLUDED_AND_PROTOCOL_REFROZEN=PASS`.

## EC10 — Hosts, sessões e independência

Mínimo confirmatório:

- seis hosts físicos;
- três famílias de CPU, com ao menos dois hosts por família;
- dois laboratórios ou operadores independentes;
- ao menos um ambiente Linux bare metal com RAPL válido para análise
  secundária;
- desktop preferido para energia total; notebook apenas com bateria controlada;
- inventário de CPU, stepping, microcode, firmware, memória, NUMA, storage,
  SO/kernel, mitigations, governor/perfil, turbo, afinidade, threads, ambiente e
  temperatura;
- reconstrução a partir de manifestos, não de imagem preparada pelo inventor;
- equipe de análise não confia no `analysis.json` do produtor;
- patches locais criam nova identidade e não são misturados.

Gate: `MULTI_HOST_INDEPENDENCE=PASS`.

## EC11 — Campanha pareada definitiva

Por combinação host × workload × modalidade:

- mínimo inicial de 24 pares válidos, distribuídos em três sessões
  independentes com pelo menos oito pares por sessão; análise de potência pode
  elevar esse número;
- agenda balanceada e seed selada antes dos dados;
- ordem Latin-square ou equivalente para A–F;
- três warm-ups fora das amostras;
- temperatura inicial pareada e estabilidade pré-definida;
- mesma afinidade, threads, perfil, firmware e estado de instrumentos;
- zero throttling dentro da janela e guarda posterior;
- nenhuma exclusão pós-hoc;
- rejeições preservadas com motivo e dados brutos;
- reposição somente por agenda predefinida;
- nenhum optional stopping por resultado favorável;
- término apenas ao completar o tamanho fixo/potenciado ou atingir bloqueio
  físico/de integridade.

Toda janela termina depois de processo, threads, filas, escrita do resultado,
flush de receipts e confirmação do medidor.

Gate: `CONFIRMATORY_SCHEDULE_COMPLETE=PASS`.

## EC12 — Estatística, incerteza e recomposição

Para cada pergunta, pré-registrar um estimando primário. Reportar:

- joules brutos por janela;
- joules por unidade aceita;
- tempo, potência média derivada, trabalho e throughput;
- energia incremental sobre idle apenas como secundária;
- razão pareada e redução absoluta;
- IC95, teste de sinais e todas as razões individuais;
- incerteza metrológica Tipo A/Tipo B, combinada e expandida;
- efeitos por host, família, laboratório, sessão e workload;
- heterogeneidade e interações;
- custo de compilação, ponto de amortização e curvas cold/warm;
- resultado com e sem compilação, sem misturar os escopos.

Modelo principal em log-razão, com níveis de laboratório, família, host,
workload, sessão e bloco. Bootstrap pareado de 20.000 reamostragens e teste de
sinais são suplementares. A regra de multiplicidade é congelada antes da
coleta.

Uma redução material exige:

```text
median(rho_wall) < 0.90
AND CI95_upper(rho_wall) < 1.00
AND semantic_equivalence=PASS
AND metrology=PASS
AND no_invalid_pair_used=true
AND direction_rule_across_sessions_and_hosts=PASS
```

Efeito menor que 10% pode ser estatisticamente significativo, mas é rotulado
`SMALL_EFFECT`. Heterogeneidade não é apagada pela média.

Gate: `INDEPENDENT_RECOMPOSITION=PASS`.

## EC13 — Red team e falsificação

Equipe independente deve tentar, no mínimo:

- trocar dataset ou inicialização após grant;
- omitir epochs, batches, records, updates ou K;
- alterar dtype, loss, optimizer, working set, stopping ou tolerância;
- duplicar, reordenar, inventar ou reusar receipt;
- reutilizar output/cache;
- encerrar medição antes de join/flush;
- substituir executable após hash;
- aceitar erro/ausência do juiz;
- atribuir autoridade à primitive;
- fabricar PASS rehashando bundle coordenado;
- remover host/par desfavorável;
- alterar range, relógio, calibração ou série do medidor;
- misturar package energy e total-system energy;
- usar TDP/tempo como energia;
- produzir resultado numericamente plausível com trabalho incompleto.

Ataques HARD são congelados antes dos resultados. Qualquer falso HARD `PASS` é
P0 e invalida o claim dependente.

Gate: `FALSE_HARD_PASS=0`.

## EC14 — Escada de claims sobre o “colosso energético”

Autorizar somente o nível efetivamente aprovado:

### Claim E0 — ausência de energia

Autoridade causal e redução não energética permanecem; joules indisponíveis.

### Claim E1 — um host, workload pequeno

“No host e workload especificados, o sistema T apresentou a razão medida de
energia total/package.” Nenhuma extrapolação.

### Claim E2 — multi-host CPU e cinco famílias de workload

“Nos hosts e workloads CPU estudados, observou-se efeito agregado e
heterogeneidade descritos.” Não falar em GPU/datacenter.

### Claim E3 — CNN/atenção em acelerador

Permite claim delimitado ao acelerador, modelo, escala, qualidade e fronteira
energética medidos. Não autoriza treinamento de foundation model.

### Claim E4 — treinamento distribuído

Somente após medir todos os nós e a comunicação, sob qualidade congelada, é
permitido discutir relevância para infraestrutura de grande porte. Ainda não é
lei universal nem substituição de datacenter.

### Claim E5 — replicação institucional externa

Exige laboratórios independentes, preregistro, instrumento calibrado, análise
cega/recomposta e publicação de negativos. É o primeiro nível adequado para
uma alegação científica geral dentro do domínio definido, nunca fora dele.

O slogan “comprimir o colosso energético” permanece hipótese motivadora até
E3/E4. Antes disso, a formulação científica é “redução energética operacional
delimitada sob preservação do contrato”.

## EC15 — Artefatos, selagem e relatório

Produzir por tentativa:

```text
docs/research/interlocution/energy-confirmatory/
  ENERGY_CONFIRMATORY_PROTOCOL.md
  ENERGY_CLAIM_BOUNDARY.md
  METROLOGY_PLAN.md
  SAME_KERNEL_CAUSAL_DESIGN.md
  WORKLOAD_LADDER.md
  STATISTICAL_ANALYSIS_PLAN.md
  INDEPENDENT_REPLICATION_RUNBOOK.md
  ENERGY_CONFIRMATORY_EXECUTION_STATE.md

outputs/casulo/interlocution-energy/<campaign-id>/
  preregistration.json
  frozen_protocol.json
  system_boundary.json
  instrument_manifest.json
  calibration/
  environments/
  workload_contracts/
  sources_t/
  tcap/
  primitive_manifests/
  schedules/
  markers/
  receipts/
  raw_meter/
  raw_runtime/
  rejected/
  equivalence/
  adversarial/
  independent_verification/
  statistical_analysis/
  uncertainty_budget.json
  claim_matrix.json
  report.md
  MANIFEST.json
  SHA256SUMS
  SIGNATURES/
```

Dados brutos são imutáveis. Correção gera `attempt-N` e errata. O relatório
separa observado, estimado e indisponível. O pacote é verificável sem confiar
na narrativa.

## Definição de pronto

O estudo encerra somente quando puder responder com artefatos:

1. o que exatamente `R` preservou por workload;
2. qual trabalho foi realmente executado em cada braço;
3. qual decisão T reduziu trabalho e por qual mecanismo causal;
4. quanto custou a governança T com o mesmo kernel;
5. quanto custou cada stack completo;
6. quantos joules totais na tomada foram medidos por unidade aceita;
7. quais joules de pacote foram medidos separadamente;
8. qual foi a incerteza metrológica;
9. quais hosts/workloads ganharam, empataram ou perderam;
10. se a compilação e o overhead completo foram incluídos;
11. se o verificador independente recompôs trabalho, equivalência e energia;
12. se algum ataque HARD obteve falso `PASS`;
13. até qual nível E0–E5 o claim chegou;
14. qual parte da hipótese do “colosso energético” permaneceu não testada.

## Regra final

Não usar tempo como joules. Não usar package como sistema total. Não usar
FloodSurrogate como datacenter. Não usar kernel AOT como prova de que T é
intrinsecamente mais rápida. Não ocultar o overhead de governança. Não retirar
host desfavorável. Não mover tolerância depois dos dados. Não ressuscitar
`656×`.

Se T reduzir trabalho permitido por `R`, preservar equivalência e continuar
favorável na tomada após todo overhead, a compressão energética está observada
naquele domínio. Se não, a autoridade causal pode continuar válida, mas a tese
energética precisa ser delimitada ou rejeitada.
