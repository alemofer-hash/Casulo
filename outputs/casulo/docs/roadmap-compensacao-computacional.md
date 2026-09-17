# Roadmap — compensação computacional com a linguagem T

## Tese

A linguagem T não cria capacidade física. Ela pode substituir parcialmente
hardware quando usa conhecimento semântico para evitar interpretação,
movimentação, alocação, recomputação e simulações redundantes.

O objetivo experimental é maximizar:

```text
trabalho útil manifestado
──────────────────────────
CPU × memória × energia × tempo
```

O desafio de `256×` somente será considerado atingido contra um baseline
declarado, no mesmo hardware, com saída semanticamente ou numericamente
equivalente e intervalo de confiança publicado.

## Invariante universal — Pacto Científico

Desde o Sprint 013, todo marco está subordinado ao
`casulo-scientific-covenant/1.0`.

- hipótese, desenho, baselines e gates são pré-registrados;
- execução exploratória não libera alegação pública;
- qualidade precede velocidade;
- baseline ausente produz `INCONCLUSIVE`;
- divergência de integridade produz `INVALID`;
- resultado negativo ou nulo é preservado;
- correção lógica exige nova versão e nova execução;
- grandeza não medida permanece `null`;
- o juiz não pode modificar ou otimizar o experimento.

Esse pacto é cumulativo e não expira nos sprints posteriores.

## Estado inicial — concluído

- frontend, tipos e representação intermediária;
- grafo de dependências;
- artefato reproduzível;
- execução escalar e em lote;
- cache e deduplicação;
- prova de equivalência;
- laboratório Borboleta;
- curva de sensibilidade;
- wheel e sdist reproduzíveis.

Baseline histórico no i5-1235U:

- kernel barato, 35% de repetição: regressão;
- 90%: inconclusivo;
- 95%: pequena melhoria;
- 99%: aproximadamente `1,095×`.

Após os Sprints 007 e 008, o mesmo kernel atingiu `3,790×` em 50% de repetição
e `3,074×` mesmo em 0%, com equivalência semântica.

---

## Marco 1 — Casulo adaptativo

### Hipótese

O compilador pode estimar quando cache, lote e deduplicação custarão mais que
recalcular e escolher automaticamente o caminho adequado.

### Implementação

1. incorporar custo estático por instrução à CrisálidaIR;
2. medir custo dinâmico por operação e forma de entrada;
3. estimar repetição, cardinalidade e tamanho do estado;
4. criar políticas:
   - `RECALCULATE`;
   - `FUSE`;
   - `MEMOIZE`;
   - `DEDUPLICATE_BATCH`;
   - `PARALLELIZE`;
5. registrar a decisão e sua justificativa no artefato;
6. permitir orçamento máximo de memória e latência.

### Experimentos

Variar independentemente:

- repetição: 0%–99,9%;
- custo do kernel: 4–1.000.000 operações;
- tamanho do registro: 32 B–10 MB;
- lote: 1–1.000.000 registros;
- memória disponível: 256 MB–12 GB.

### Critério de saída

- regressão máxima menor que 5% contra o melhor caminho conhecido;
- decisão correta em pelo menos 95% da matriz;
- cache jamais ativado quando a economia prevista for negativa;
- relatório explica por que cada estratégia foi escolhida.

---

## Marco 2 — caminho quente sem objetos

**Estado: concluído no Sprint 008.**

### Hipótese

Grande parte do overhead atual vem de JSON, dicionários Python, envelopes e
hash genérico, não da lógica T.

### Implementação

1. gerar chave tipada somente com campos efetivamente usados;
2. substituir JSON canônico por tuplas/estruturas binárias;
3. usar hash incremental especializado;
4. separar conteúdo conservado da representação do caminho quente;
5. manter evidências em buffers laterais;
6. materializar envelopes apenas na fronteira de saída;
7. usar layout columnar e buffers contíguos;
8. criar cache local do lote com vida útil explícita.

### Critério de saída

- pelo menos `2×` no cenário de 50% de repetição;
- break-even de deduplicação abaixo de 50%;
- conteúdo e evidências idênticos à implementação de referência;
- redução comprovada de alocações e bytes movimentados.

Resultado em 50%: kernel `3,790×`, adaptativo `3,557×` e redução de 31,00% no
pico rastreado. Em 0%, a fusão tipada permaneceu acima de `3×` no kernel.

---

## Marco 3 — backend nativo de um núcleo

**Estado: concluído no Sprint 010.**

O backend `c99-aot/0.2` atingiu `5,864×` ponta a ponta, mediana pareada de
`5,966×` e IC95% `5,866×–6,169×` em 2.000 registros únicos. A equivalência, o
fallback e a reprodutibilidade binária foram preservados.

### Hipótese

A IR já possui informação suficiente para remover a interpretação Python e
gerar um kernel AOT especializado.

### Implementação

1. especificar ABI estável para operações T;
2. criar backend C99 de referência;
3. compilar artefatos nativos com otimização;
4. eliminar boxing de números e despacho dinâmico;
5. executar propagação de constantes;
6. remover código morto;
7. fundir operações consecutivas;
8. vetorizar loops seguros;
9. conservar fallback Python para comparação e portabilidade.

C99 é o primeiro alvo por simplicidade e auditabilidade. LLVM/MLIR somente
entra depois que a ABI e as regras da IR estiverem estáveis.

### Critério de saída

- `5×–20×` sobre Python escalar em kernels numéricos;
- equivalência no corpus golden e nos testes de propriedades;
- artefato reproduzível em Windows e Linux;
- falha do compilador nativo nunca altera silenciosamente a semântica.

---

## Marco 4 — SIMD e quatro núcleos

**Estado: em andamento; SIMD concluído no Sprint 011 e primeiro scheduler
adaptativo entregue no Sprint 012.**

### Hipótese

Depois de reduzir overhead, o i5 pode combinar vetorização e paralelismo sem
perder determinismo ou exceder memória.

### Implementação

1. scheduler determinístico limitado a 1, 2 ou 4 núcleos;
2. partição por blocos, bacias, células ou membros de ensemble;
3. filas limitadas e backpressure;
4. redução determinística;
5. afinidade e blocos adaptados ao cache da CPU;
6. SIMD para operações independentes;
7. cancelamento e checkpoint;
8. controle térmico por janelas de execução.

### Experimentos

- escalabilidade em 1, 2 e 4 núcleos;
- speedup, eficiência paralela e tempo ocioso;
- conjuntos menores e maiores que os caches L2/L3;
- desempenho sustentado por 1, 10 e 60 minutos;
- execução conectado e desconectado da tomada;
- throttling térmico e frequência efetiva.

### Critério de saída

- eficiência paralela superior a 70% em quatro núcleos;
- ganho combinado nativo + SIMD + quatro núcleos de `15×–50×`;
- pico de memória dentro de orçamento configurado;
- reprodução numérica dentro da tolerância declarada.

---

## Marco 5 — otimização estrutural do FLOOD-RS

### Hipótese

O maior ganho não virá de calcular cada célula mais rapidamente, mas de
identificar estados, sub-bacias e membros de ensemble que compartilham trabalho.

### Implementação

1. decompor o gêmeo digital em subgrafos:
   - chuva;
   - solo;
   - chuva–vazão;
   - propagação;
   - drenagem;
   - infraestrutura;
   - consequências;
2. identificar estados antecedentes compartilhados;
3. reutilizar prefixos iguais entre ensembles;
4. recalcular somente regiões afetadas por nova observação;
5. usar esparsidade espacial e temporal;
6. criar resolução adaptativa;
7. gerar surrogate models com domínio de validade explícito;
8. manter o modelo físico como autoridade e corretor;
9. colocar extrapolações fora do domínio em quarentena.

### Critério de saída

- atualização incremental mais rápida que simulação integral;
- erro dentro da tolerância física estabelecida;
- toda reutilização rastreável até estado e versão de entrada;
- fallback automático quando o estado deixa de ser equivalente.

---

## Marco 6 — memória e processamento fora de núcleo

### Hipótese

Com 16 GB de RAM, o gargalo do FLOOD-RS será frequentemente movimentação de
dados, e não aritmética.

### Implementação

- arquivos mapeados em memória;
- particionamento espacial;
- armazenamento columnar;
- compressão por blocos;
- carregamento sob demanda;
- descarte explícito de intermediários reproduzíveis;
- checkpoints endereçados por conteúdo;
- cache em disco com política de retenção;
- streaming com backpressure;
- modo degradado quando o orçamento for excedido.

### Critério de saída

- executar dataset maior que a RAM sem paginação descontrolada;
- memória residente previsível;
- recuperação após interrupção;
- nenhuma perda de proveniência.

---

## Marco 7 — laboratório de energia real

### Hardware mínimo

Uma das alternativas:

- Linux com RAPL exposto;
- medidor USB/tomada com API e amostragem;
- fonte de bancada;
- contador cumulativo externo integrado ao protocolo.

Sensores de software sem contador cumulativo não serão tratados como medição de
joules.

### Experimentos

- joules por milhão de registros;
- energia por membro de ensemble;
- energia por atualização assimilada;
- energia até determinada antecedência hidrológica;
- temperatura e frequência ao longo do tempo;
- comparação 1, 2 e 4 núcleos;
- melhor tempo versus melhor energia.

### Critério de saída

- intervalo de energia sincronizado com cada amostra;
- erro conhecido do instrumento;
- execução de idle descontada ou publicada separadamente;
- resultado replicado em pelo menos duas máquinas.

---

## Marco 8 — desafio de compensação

O desafio final terá quatro baselines:

1. Python escalar ingênuo;
2. bibliotecas científicas convencionais;
3. Casulo nativo em um núcleo;
4. Casulo nativo em quatro núcleos.

O número `256×` somente poderá ser usado com:

- dataset público ou gerador versionado;
- baseline tecnicamente razoável;
- mesma máquina e mesmos dados;
- mesma tolerância numérica;
- amostras brutas;
- intervalo de confiança;
- energia quando disponível;
- prova de conteúdo/proveniência;
- revisão independente.

É possível obter `256×` contra um baseline ingênuo por uma combinação de:

```text
eliminação de interpretação
× SIMD
× quatro núcleos
× fusão
× esparsidade
× atualização incremental
× reutilização entre ensembles
× surrogate válido
```

Isso não equivale a substituir 256 processadores em uma carga irreduzível e
perfeitamente paralela. A afirmação correta será sempre vinculada à carga e ao
baseline medidos.

---

## Sequência de sprints

| Sprint | Entrega | Meta mínima |
|---:|---|---|
| 006 | modelo de custo e seletor adaptativo | **concluído: nenhuma regressão adaptativa conclusiva** |
| 007 | chave estrutural e cache local | **concluído: ganho adaptativo em 40%** |
| 008 | buffers tipados e envelopes laterais | **concluído: `3,790×` em tráfego intermediário** |
| 009 | ABI e backend C99 mínimo | **concluído: primeiro artefato nativo reproduzível** |
| 010 | otimizações AOT | **concluído: `5,864×`, IC95% inferior acima de `5×`** |
| 011 | SIMD | **concluído: `1,117×`, IC95% `1,084×–1,135×`** |
| 012 | treinamento científico e scheduler limitado | **concluído: `9,743×`, IC95% inferior `9,217×`; gate geral de quatro núcleos permanece aberto** |
| 013 | Pacto Científico e juiz independente | **concluído: baseline eager positivo e veredito amplo inicialmente inconclusivo** |
| 014 | Egg Workspace e baseline PyTorch compilado | **concluído: projetos multifile e prova compilada congelada** |
| 015 | LarvaTensor e ABI de extensões | **concluído: tipos, inferência, aliasing, TensorIR e memória estática** |
| 016 | Metamorfose Autograd | **concluído: backward explícito e oito derivadas verificadas** |
| 017 | executor NumPy e adaptador PyTorch | **concluído: paridade de intermediários, loss e gradientes** |
| 018 | backend CPU tensorial | **concluído: forward/backward C99, arena limitada e dupla paridade** |
| 019 | laboratório científico tensorial | **concluído: veredito `NEGATIVE`; `0,233×` vs eager e `0,104×` vs Inductor** |
| 020 | grafo incremental FLOOD-RS | recalcular somente regiões afetadas |
| 021 | reutilização de ensembles | compartilhamento de prefixos |
| 022 | surrogate com guardas | aceleração dentro do domínio |
| 023 | desafio público | relatório revisável de compensação |

## Próximo sprint

O Sprint 019 separou correção de competitividade:

```text
correção numérica
→ PASS em Casulo/T, NumPy, eager e Inductor

desempenho no MLP denso de quatro threads
→ 0,233× contra eager
→ 0,104× contra Inductor
→ veredito NEGATIVE
```

O Sprint 020 continua destinado ao grafo incremental FLOOD-RS, mas o ramo de
runtime tensorial agora possui uma exigência objetiva antes de nova alegação:

1. perfilar o tempo por kernel sem modificar esta evidência;
2. introduzir despacho GEMM/BLAS ou microkernel bloqueado;
3. especializar os transposes do backward;
4. medir separadamente kernels densos e ponto a ponto;
5. criar um protocolo `0.2` e novo pré-registro;
6. aceitar novamente qualquer classificação.

O resultado positivo dos kernels de treinamento especializados e o resultado
negativo do backend tensorial geral não são contraditórios: representam
fronteiras e implementações diferentes.
