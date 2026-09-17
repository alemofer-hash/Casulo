# Sprint 021 — Provedor GEMM auditável

**Versão:** `0.22.0a1`  
**Estado:** implementação concluída; hipótese de desempenho ainda exploratória

## Objetivo

Separar duas responsabilidades sem perder a identidade do invento:

1. o Casulo/T decide quais operações existem, elimina trânsito inútil, forma o
   plano e controla a execução;
2. um provedor GEMM intercambiável pode executar apenas a multiplicação
   matricial, sob contrato e proveniência verificáveis.

Isso permite testar a arquitetura Casulo contra PyTorch sem fingir que uma
biblioteca externa foi criada pelo projeto.

## Arquitetura

### Egg — contrato

Cada `matmul` conserva dtype, shapes, strides, transposições lógicas e destino.
Nada é copiado implicitamente para tornar o caso conveniente.

### Larva — trânsito

O diagnóstico mede trabalho aritmético, bytes lógicos, intensidade, eixos
contíguos e oportunidades de evitar materialização.

### Crisálida — escolha

O plano sela:

- provedor `casulo-owned-c99` ou `numpy-scipy-openblas-ilp64`;
- versão e ABI;
- nome e SHA-256 do DLL externo;
- símbolos `sgemm`, `dgemm` e controle de threads;
- orçamento total de workers;
- threads internas do GEMM;
- identidade SHA-256 de cada kernel.

### Metamorfose — execução

Para o OpenBLAS, o código C99 gerado recebe ponteiros de função CBLAS ILP64 em
tempo de carga. Antes do primeiro cálculo, o runtime redescobre o DLL, compara
todo o descritor e recalcula o hash. Divergência impede a execução.

### Borboleta — Juiz

Paridade numérica precede tempo. O relatório identifica separadamente o código
Casulo, o provedor aritmético, as threads e o binário. Um pré-registro também
declara se o mesmo desenho já havia sido observado. Smoke tests e explorações
são selados como inelegíveis para claim: podem receber classificação positiva,
mas não liberam alegação nem gate comercial.

## Reduções de trabalho neste sprint

O compilador de autograd passou a:

- podar derivadas que não contribuem para os gradientes solicitados;
- reconhecer `x * x` e formar sua derivada com uma multiplicação e uma soma;
- reduzir de seis para cinco os GEMMs do grafo MLP médio observado;
- reduzir o backward desse grafo de 19 para 13 instruções.

Essas transformações preservaram a paridade nos testes NumPy/PyTorch.

## Observações exploratórias

As medições abaixo guiaram engenharia. Elas **não são claim**:

| configuração observada | Casulo | eager | Inductor | leitura |
|---|---:|---:|---:|---|
| OpenBLAS, orçamento 4, GEMM 4 | `0,918 ms` | `1,592 ms` | `0,760 ms` | vence eager; perde para Inductor |
| OpenBLAS, orçamento 4, GEMM 1, rodada pareada instável | `1,454 ms` | `6,068 ms` | `1,621 ms` | vitória isolada de `1,115×` sobre Inductor |

A segunda rodada é interessante porque sugere que evitar competição entre o
scheduler externo e o paralelismo do grafo pode ser útil. Ela não prova
superioridade: o eager degradou de forma anormal, os tempos absolutos variaram
entre rodadas e o mesmo desenho já tinha sido observado.

Durante a integração, um smoke test declarado textualmente após exploração
mediu `9,686×` contra eager e `3,043×` contra Inductor no grafo MLP médio, com
sete amostras e paridade aprovada. A primeira versão do Juiz liberou claim
porque ainda não existia um campo binário de elegibilidade. Isso foi tratado
como defeito do protocolo, não como vitória: o teste permaneceu temporário,
nenhuma evidência foi promovida e o Juiz ganhou o gate selado
`claim_eligible`. Sob o protocolo corrigido, esse tipo de execução conserva a
classificação, mas produz `claim=null` e `commercial_gate=false`.

## O que o resultado permite afirmar

- a arquitetura consegue trocar o executor GEMM sem perder auditoria;
- a redução de trânsito do Casulo pode ser combinada com uma implementação
  BLAS madura;
- há uma hipótese concreta de escalonamento hierárquico a testar;
- nenhum resultado atual sustenta “Casulo é mais rápido que PyTorch” de forma
  geral.

## Próximo portão científico

O próximo experimento confirmatório deve:

1. usar shapes e, idealmente, grafos ainda não cronometrados;
2. pré-registrar provedor, hashes, orçamento e threads;
3. executar múltiplos reinícios frios e alternar a ordem dos processos;
4. registrar frequência, temperatura e throttling;
5. comparar Casulo próprio, Casulo+OpenBLAS, NumPy/OpenBLAS, PyTorch eager e
   Inductor;
6. repetir em outra máquina;
7. publicar todos os resultados, inclusive negativos e falhas.
