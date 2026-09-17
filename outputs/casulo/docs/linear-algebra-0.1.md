# Álgebra Linear Casulo/T 0.1

## Finalidade

A Álgebra Linear Casulo/T é a camada que transforma um contrato matemático em
um percurso de memória explícito, executável e auditável. Ela não confunde o
planejador com o provedor de capacidade: cada plano identifica tanto a decisão
do Casulo quanto o kernel que realizou a aritmética.

O escopo inicial é `matmul` rank 2 em `float32` e `float64`, no CPU.

## Fases

### Egg — contrato imutável

Registra:

- operação;
- dtype;
- shapes;
- strides;
- shape e strides da saída.

Uma dimensão incompatível é recusada antes de existir código nativo.

### Larva — diagnóstico de trânsito

Calcula:

- multiplicações-acumulações;
- FLOPs escalares;
- bytes lógicos de entrada e saída;
- intensidade aritmética;
- contiguidade do eixo interno;
- contiguidade de colunas.

Essas propriedades são fatos do contrato, não resultados de benchmark.

### Crisálida — plano

Seleciona uma ordem de laços determinística:

- `row-inner-column` quando a matriz direita e a saída são contíguas por
  coluna;
- `row-column-inner` quando o produto interno é o percurso conservador.

O plano declara paralelismo, eixo vetorial, materializações, contração FMA e
eventual reordenação de redução. Sua identidade é o SHA-256 da representação
canônica da decisão.

### Metamorfose — kernel

O primeiro provedor é próprio:

- C99;
- OpenMP limitado a 1, 2 ou 4 workers;
- AVX2 emitido pelo compilador hospedeiro;
- `fast-math` proibido;
- contração FMA permitida e declarada;
- transpostas do backward como views;
- `reduce_to_shape` de shape idêntico como alias;
- arena de memória previamente alocada.

O mesmo binário possui dois modos:

- `audit=1`: manifesta intermediários, loss e gradientes;
- `audit=0`: manifesta somente a fronteira exigida pelo problema.

O modo medido não remove computação matemática. Ele remove apenas sondas de
auditoria que não fazem parte da fronteira comparada com PyTorch.

### Borboleta — manifestação

Expõe o plano, sua identidade, custos lógicos e política numérica. Nenhuma
métrica de velocidade nasce nesta fase.

## Juiz

Há três autoridades separadas:

1. auditor estrutural da Álgebra Casulo;
2. NumPy como referência numérica independente do kernel C;
3. PyTorch como autoridade de paridade externa.

O laboratório científico acrescenta:

- entradas idênticas;
- mesmo grafo e dtype;
- orçamento igual de threads;
- ordens balanceadas;
- amostras pareadas;
- bootstrap;
- resultado negativo preservado;
- claim bloqueado até julgamento.

Uma escolha estruturalmente válida ainda pode falhar numericamente. Uma
execução numericamente correta ainda pode perder em desempenho.

## Provedores

O provedor próprio do Sprint 020 é
`casulo-linear-algebra-c99-openmp/0.2`. A partir do Sprint 021, o backend `0.3`
também aceita:

- microkernel próprio;
- OpenBLAS ILP64 distribuído com o NumPy;
- MKL;
- outros provedores explicitamente registrados.

O uso do provedor externo aparece no plano, na fonte, no manifesto, no
pré-registro, no relatório e no veredito. Nome, versão, símbolos e SHA-256 do
DLL são verificados no carregamento. Uma comparação desse tipo mede a
arquitetura Casulo mais o provedor declarado, nunca um suposto kernel
inteiramente próprio.

## Limites atuais

- apenas matrizes rank 2;
- sem packing persistente;
- sem autotuning por shape;
- sem fusão GEMM + epílogo;
- sem microkernel intrínseco escrito manualmente;
- sem energia elétrica medida;
- nenhuma superioridade sobre PyTorch demonstrada.
