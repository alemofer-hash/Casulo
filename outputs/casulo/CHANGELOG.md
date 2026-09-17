# Changelog

## 0.25.0-alpha.1 — 2026-07-30

### Profiler causal

- contabilidade por instrução de FLOPs conhecidos e bytes lógicos;
- distinção entre GEMM, ponto a ponto, redução e view;
- mapeamento de materializações, buffers, live ranges e arena;
- quantificação de reuso de memória e lançamentos evitados por fusão;
- identidade e tráfego de cada kernel GEMM;
- hipóteses de gargalo acompanhadas de falsificadores;
- matriz de ablação estrutural para workers, threads GEMM e provedor;
- HTML auditável sem cronômetro, speedup ou claim.

## 0.24.0-alpha.2 — 2026-07-30

### Correção do CLI metrológico

- opções de calibração, cooldown, afinidade e CV ligadas ao comando correto;
- teste de integração prova os valores efetivamente selados no JSON;
- rodada produzida pela ligação anterior preservada como `INCONCLUSIVE`;
- novo pré-registro obrigatório para qualquer repetição.

## 0.24.0-alpha.1 — 2026-07-30

### Estabilidade metrológica

- calibração prévia e causal da duração de lote, sem observar speedup;
- mesmo número calibrado de invocações aplicado a todos os backends;
- janela mínima de tempo, limite de calibração e cooldown selados;
- afinidade de CPU opcional, verificável e restaurada após o ensaio;
- detecção da topologia híbrida do Windows pela API do sistema;
- telemetria antes e depois de cada amostra, fora da fronteira medida;
- registro de plano de energia, bateria, frequência, memória e sensores;
- coeficiente de variação recalculado pelo Juiz;
- medição acima do CV pré-registrado passa a ser `INCONCLUSIVE`;
- nenhuma amostra é removida ou escolhida após o resultado.

## 0.23.0-alpha.1 — 2026-07-30

### Suíte confirmatória multi-caso

- três workloads reservados com shapes distintos e um grafo MLP profundo;
- pré-registros filhos selados antes de qualquer medição;
- três reinícios por caso em processos Python independentes;
- agenda latina fixa que distribui a posição dos casos;
- caches nativo e Inductor isolados por execução;
- falhas e execuções ausentes permanecem evidência;
- claim individual dos casos bloqueado;
- Juiz agregado exige unanimidade entre todos os casos, reinícios e baselines;
- seleção posterior do melhor caso ou reinício é proibida;
- verificador independente recalcula a classificação agregada.
- primeira suíte oficial concluída como `NEGATIVE`;
- `9/9` resultados positivos contra eager;
- contra Inductor: `2` positivos, `6` nulos e `1` negativo;
- nenhuma alegação de superioridade sobre Inductor foi liberada.

## 0.22.0-alpha.1 — 2026-07-30

### Provedor GEMM auditável

- descoberta do OpenBLAS ILP64 distribuído com o NumPy;
- validação da ABI CBLAS por símbolos, versão e SHA-256 do binário;
- ligação dinâmica sem incorporar nem ocultar o provedor externo;
- orçamento independente, mas limitado, de threads do GEMM;
- provedor e número de threads selados no plano, fonte, manifesto e
  pré-registro científico;
- eliminação de derivadas mortas e coalescência da derivada de quadrado;
- distinção obrigatória entre desenho ainda não observado e replicação
  confirmatória após exploração;
- flag selada de elegibilidade impede smoke tests e explorações de liberarem
  claim ou gate comercial, mesmo quando o resultado é positivo;
- protocolos do backend tensorial promovidos para `0.3` e laboratório para
  `0.2`.

### Estado científico

- resultados deste sprint permanecem exploratórios e inelegíveis para claim;
- uma execução isolada superou Inductor com configuração desacoplada, mas a
  instabilidade entre rodadas impede conclusão;
- o achado é uma hipótese de escalonamento a ser replicada em desenho novo,
  múltiplos shapes, reinícios frios e máquinas independentes.

## 0.21.0-alpha.1 — 2026-07-30

### Adicionado

- arquitetura auditável da Álgebra Linear Casulo/T;
- contratos Egg, diagnóstico Larva, plano Crisálida e auditor Borboleta;
- seleção de microkernel por shape e strides;
- modo de auditoria separado da fronteira cronometrada;
- testes e documentação do Sprint 020.

### Alterado

- backend tensorial promovido para `casulo-linear-algebra-c99-openmp/0.2`;
- transpostas e reduções de identidade do backward passam a ser zero-copy;
- regiões pequenas evitam coordenação OpenMP desnecessária;
- FMA é permitida e declarada, mantendo `fast-math` proibido.

## 0.20.0-alpha.1 — 2026-07-30

### Laboratório científico tensorial

- pré-registro específico para TensorIR/AutogradIR;
- comparação pareada com PyTorch eager e PyTorch Inductor CPU;
- seis ordens balanceadas entre os três backends;
- separação entre planejamento, geração, compilação, preparação e execução;
- runner preparado do backend C99/OpenMP sem alocação no laço medido;
- paridade obrigatória de intermediários, loss e gradientes;
- memória RSS sondada fora das amostras de tempo;
- frequência e temperatura preservadas quando disponíveis;
- juiz que recalcula mediana e bootstrap das amostras brutas;
- classificação individual por baseline e global;
- claim limitado ao escopo e somente após veredito positivo;
- energia elétrica permanece `null` sem instrumento cumulativo.
- primeira execução oficial classificada como `NEGATIVE`;
- `0,232910×` contra PyTorch eager e `0,104399×` contra Inductor;
- todos os gates de correção numérica aprovados;
- nenhum claim de desempenho liberado.

## 0.19.0-alpha.1 — 2026-07-30

### Backend CPU tensorial

- planejamento determinístico de fusão para forward e backward;
- bloqueio conservador de shapes dinâmicos, mutação e operadores incompatíveis;
- análise de vida e reutilização de buffers numa arena alinhada;
- orçamento máximo de arena com fallback explícito para NumPy;
- geração C99/OpenMP endereçada por conteúdo;
- scheduler limitado a 1, 2 ou 4 workers;
- SIMD restrito a regiões ponto a ponto comprovadamente contíguas;
- kernels de aritmética, ativações, reduções, views e `matmul` rank 2;
- forward, intermediários, loss e gradientes julgados contra NumPy e PyTorch;
- comandos `t tensor-cpu-plan` e `t tensor-cpu-run`;
- tempos de compilação, preparação e execução classificados como exploratórios;
- energia, speedup e claim permanecem explicitamente ausentes.

## 0.18.0-alpha.2 — 2026-07-30

### Runtime PyTorch operacional

- diagnóstico executável de NumPy, PyTorch CPU e autograd;
- comando `t pytorch-doctor` com prova opcional do Inductor;
- descoberta automática do MSVC Build Tools no Windows;
- ativação de `vcvars64.bat` quando `cl.exe` não está no `PATH`;
- política UTF-8/inglês para impedir falha de decodificação do compilador;
- baseline `torch.compile` e sondagem científica usam a mesma preparação;
- sondagem científica 1.1 registra o toolchain sem invalidar evidências 1.0;
- extra explícito `casulo[parity]`;
- `t doctor` deixou de declarar PyTorch disponível sem verificá-lo.

## 0.18.0-alpha.1 — 2026-07-30

### Executor NumPy e paridade PyTorch

- executor público da TensorIR e MetamorfoseAutogradIR;
- saídas e gradientes manifestados com hashes;
- adaptador PyTorch CPU sobre o mesmo grafo;
- comparação de cada intermediário, loss e gradiente;
- tolerâncias por `float32` e `float64`;
- vereditos `PASS`, `FAIL` e `INCONCLUSIVE`;
- falha explícita para shape, dtype e valores não finitos;
- corpus pequeno `float64` e médio `float32`;
- comandos `t numpy-execute` e `t pytorch-parity`;
- timing e energia invariavelmente ausentes nesta prova.

## 0.17.0-alpha.1 — 2026-07-30

### Metamorfose Autograd

- ABI versionada de regras VJP;
- backward explícito sobre a TensorIR;
- loss escalar e flutuante obrigatória;
- redução de broadcasting ao shape original;
- acumulação determinística em fan-out;
- zero explícito para entrada desconectada;
- regras de aritmética, ativação, redução e views;
- `matmul` rank 2 com transposes visíveis;
- verificador central por diferenças finitas;
- comandos `t autograd-compile` e `t autograd-check`;
- maior erro absoluto de `1,82×10⁻¹¹` no exemplo oficial.

## 0.16.0-alpha.1 — 2026-07-30

### LarvaTensor

- contrato tensorial com dtype, shape, device, layout, ownership e aliasing;
- dimensões estáticas ou simbólicas, sem estimativa fictícia;
- operadores fundamentais com inferência conservativa;
- registro versionado e ABI declarativa de extensões;
- bloqueio de mutação sobre entradas borrowed;
- TensorIR SSA com versões de operadores;
- plano de memória por tempo de vida e aliases;
- comando `t tensor-compile`;
- exemplo de forward de MLP e corpus automatizado.

## 0.15.0-alpha.1 — 2026-07-30

### Egg Workspace

- terminologia inicial migrada para `Egg` em toda a superfície ativa;
- manifesto de projeto `casulo.toml`;
- lockfile de fontes e compilador endereçado por conteúdo;
- descoberta recursiva de módulos core e training;
- dependências locais e módulos externos declarados;
- resolução de `use` e ordem topológica determinística;
- bloqueio de módulos ausentes, duplicados e cíclicos;
- build multifile com cache por identidade do workspace;
- comandos `t init`, `t check .`, `t build .`, `t run .` e `t test .`;
- `t training-experiment` aceita projetos com entrypoint training.

## 0.14.0-alpha.1 — 2026-07-30

### Baseline PyTorch compilado

- baseline selecionável `pytorch-compile-inductor-cpu`;
- forward e backward compilados por `torch.compile`/Inductor;
- custo inicial de compilação medido e publicado separadamente;
- amostras de treinamento compilado explicitamente marcadas como aquecidas;
- equivalência numérica e determinismo continuam precedendo velocidade;
- pré-registro 1.1 vincula os hashes do executor e do juiz científico;
- pré-registros 1.0 permanecem verificáveis e não são sobrescritos.

## 0.13.0-alpha.1 — 2026-07-30

### Pacto científico

- fidelidade científica transformada em doze invariantes executáveis;
- pré-registro imutável de hipótese, desenho, baselines e gates;
- execuções não registradas impedidas de liberar claims;
- vereditos `POSITIVE`, `NULL`, `NEGATIVE`, `INCONCLUSIVE` e `INVALID`;
- juiz sem permissão para otimizar ou alterar o experimento;
- métricas e bootstrap recalculados das amostras brutas;
- indisponibilidade de `torch.compile` preservada como evidência;
- primeira parcela pré-registrada: `8,958×` contra PyTorch eager;
- primeiro veredito amplo: `INCONCLUSIVE`, por ausência do baseline compilado;
- energia elétrica continua `null` porque não foi medida.

## 0.12.0-alpha.1 — 2026-07-30

### Prova de treinamento científico

- extensão declarativa `learn` da linguagem T;
- MLP `float64` full-batch com ReLU, MSE e SGD;
- backend `c99-openmp-fused/0.4`;
- scheduler Crisálida limitado a 1, 2 ou 4 workers;
- seleção automática que recusa paralelismo prejudicial;
- baseline PyTorch eager CPU com MKL/oneDNN e AVX2;
- partições determinísticas de treino e validação;
- equivalência de parâmetros, predições, loss e qualidade;
- comando `t training-experiment`;
- ganho final `9,743×`, IC95% `9,217×–10,528×`;
- menor limite inferior entre três replicações: `7,809×`;
- gate de treinamento `6×`: aprovado;
- energia elétrica continua explicitamente não medida.

## Evidência congelada — 2026-07-30

- demonstração comercial autocontida do ganho ponta a ponta;
- alegação delimitada em `6,095936×`, com IC95% `5,994133×–6,230838×`;
- manifesto canônico e `SHA256SUMS`;
- verificador independente da instalação do pacote;
- documentação de transferência comercial e proteção intelectual;
- resultado preservado sem declarar encerramento do Marco 4.

## 0.11.0-alpha.1 — 2026-07-29

### Marco 4 — SIMD estrito

- formato `casulo-artifact/0.8`;
- backend `c99-simd/0.3`;
- protocolos `casulo-simd/0.1` e `casulo-simd-benchmark/0.1`;
- fase escalar de guardas separada do laço numérico independente;
- ordem do primeiro erro e evidências preservadas;
- ponteiros C99 qualificados com `restrict`;
- perfil escalar com vetorização desativada para controle;
- perfil SIMD específico da CPU, sem `fast-math` ou contração FMA;
- relatório do compilador e alvo incorporados à proveniência da build;
- comando `t simd-benchmark`;
- AVX2 de 256 bits demonstrado no i5-1235U;
- ganho SIMD pareado `1,117×`, IC95% `1,084×–1,135×`, em 2.000 registros;
- ausência de ganho conclusivo documentada entre 1 e 256 registros;
- equivalência exata contra o perfil escalar estrito.

## 0.10.0-alpha.1 — 2026-07-29

### Marco 3 — AOT e arena nativa

- formato `casulo-artifact/0.7`;
- backend `c99-aot/0.2`;
- protocolos `casulo-aot/0.1`, `casulo-native-arena/0.1` e
  `casulo-boundary-aot/0.1`;
- remoção AOT de `let` morto;
- propagação de constantes e aliases seguros;
- arena colunar com crescimento em potência de dois;
- fusão de validação e marshal em uma única passagem;
- marshal e manifestação especializados por esquema;
- medição separada de marshal, kernel C99 e manifestação;
- intervalo pareado bootstrap para o ganho ponta a ponta;
- `5,864×` por razão de medianas e mediana pareada `5,966×`;
- IC95% pareado `5,866×–6,169×`;
- Marco 3 encerrado no kernel e máquina declarados.

## 0.9.0-alpha.1 — 2026-07-29

### Marco 3 — primeiro artefato nativo

- formato `casulo-artifact/0.6`;
- ABI `casulo-native-abi/0.1`;
- backend `c99-reference/0.1`;
- fonte C99 e descritor ABI verificáveis dentro do artefato;
- compilação AOT com GCC, Clang ou MSVC;
- DLL/SO derivada em cache imutável por conteúdo;
- layout colunar `float64` com estado e evidência laterais;
- validação de versão ABI e identidade do artefato na biblioteca;
- fallback Python explícito para forma, tipo ou compilador incompatível;
- comando `t native-benchmark`;
- equivalência semântica contra Python escalar;
- `3,958×` ponta a ponta no i5-1235U;
- binário MinGW reproduzível byte a byte.

## 0.8.0-alpha.1 — 2026-07-29

### Marco 2 — caminho quente sem objetos

- formato `casulo-artifact/0.5`;
- backend `python-reference/0.4.1`;
- protocolo `casulo-typed-buffer/0.1`;
- colunas contíguas `float64` e `int64` para operações numéricas elegíveis;
- índices de registros e flags de evidência em buffers laterais;
- manifestação dos envelopes somente na fronteira;
- fallback conservativo para entradas mistas, irregulares ou incompatíveis;
- estratégia adaptativa `FUSE_TYPED_BATCH`;
- protocolos `casulo-adaptive/0.3`, `casulo-cost-model/0.3` e
  `casulo-borboleta/0.4`;
- prova comparativa de alocações por `tracemalloc`;
- meta de `2×` em tráfego intermediário superada.

## 0.7.0-alpha.1 — 2026-07-29

### Chave estrutural e cache local

- formato `casulo-artifact/0.4`;
- backend `python-reference/0.3.1`;
- chave `casulo-structural-key/0.1`, tipada e independente da ordem de objetos;
- especialização AOT para esquemas numéricos;
- igualdade estrutural completa para resolver colisões de fingerprint;
- cache de lote com vida útil restrita a uma chamada;
- clonador conservativo para valores JSON;
- perfil por concentração de pares coincidentes;
- modelo `casulo-cost-model/0.2` calibrado para a nova fronteira;
- protocolos `casulo-adaptive/0.2` e `casulo-borboleta/0.3`;
- melhoria adaptativa conclusiva em 40% de repetição.

## 0.6.0-alpha.1 — 2026-07-29

### Crisálida adaptativa

- custo, determinismo e cacheabilidade incorporados ao manifesto;
- perfil estrutural exato até 128 itens e amostragem determinística acima disso;
- modelo de custo conservador;
- escolha entre recomputação e deduplicação;
- orçamento de memória;
- comando `t run --adaptive`;
- decisão, confiança e justificativa na saída;
- previsão confrontada com a medição Borboleta.
- medição adaptativa ponta a ponta, incluindo perfil, decisão e execução;
- formato Borboleta `casulo-borboleta/0.2`.

## 0.5.0-beta.1 — 2026-07-29

### Borboleta

- API pública `BorboletaLaboratorio`, `BorboletaConfig` e
  `generate_hydrological_dataset`;
- comando `t experiment`;
- dataset determinístico com semente, versão e SHA-256;
- comparação alternada entre referência escalar e estratégia Casulo;
- equivalência por projeção semântica com exclusão explícita de telemetria;
- mediana, amostras brutas, bootstrap pareado e veredito estatístico;
- tempo, CPU, RSS observada e energia detectável;
- relatórios JSON e HTML autocontido;
- testes gerados por propriedades;
- extras `science` e `dev`;
- CI ampliada e release reproduzível por tag.

### Compatibilidade

A API Borboleta é candidata a estável durante a série 0.5. O formato do
relatório é identificado por `casulo-borboleta/0.1`.
