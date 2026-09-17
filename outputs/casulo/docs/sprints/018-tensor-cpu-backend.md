# Sprint 018 — backend CPU tensorial

## Objetivo

Executar forward e backward da linguagem T em CPU nativa sem retirar NumPy e
PyTorch do papel de autoridades de correção.

## Entregas

- plano determinístico de fusão;
- bloqueios explícitos para formas, efeitos e operadores incompatíveis;
- intervalos de vida, aliases e reutilização de buffers;
- arena alinhada com orçamento máximo;
- geração e compilação C99/OpenMP;
- SIMD apenas em regiões comprovadamente contíguas;
- scheduler limitado a 1, 2 ou 4 workers;
- kernels de forward e backward;
- cache de bibliotecas endereçado por conteúdo;
- fallback NumPy;
- dupla paridade NumPy/PyTorch;
- CLI de planejamento e execução;
- tempos diagnósticos separados, sem claim.

## Corpus executado

### Regressão linear `float64`

- `matmul → sub → mul → mean`;
- forward e backward;
- fusão de `residual → squared`;
- arena de 320 bytes;
- máximo erro absoluto nativo versus NumPy: `0`;
- PyTorch: `PASS`.

### MLP médio `float32`

- shape `64×16 → 32 → 8`;
- dois `matmul`, ReLU e MSE;
- dois gradientes de pesos;
- quatro workers explícitos;
- arena de 43.136 bytes;
- máximo erro absoluto nativo versus NumPy: `9,5367431640625×10⁻⁷`;
- PyTorch: `PASS`.

### Broadcasting, ativações, reduções e views

- soma com bias;
- sigmoid e tanh;
- mean por eixo;
- reshape e transpose;
- sum final;
- gradientes de entrada e bias;
- nativo versus NumPy: `PASS`;
- PyTorch: `PASS`.

Esses números são testes de correção, não benchmark de desempenho.

## Fallbacks verificados

- shape dinâmico;
- arena abaixo do necessário;
- compilador/toolchain indisponível;
- modo estrito que recusa fallback.

## Invariante científico

O relatório nunca contém speedup nem claim. Energia permanece `null`. Os
tempos registrados são exploratórios e não podem ser usados como evidência
comercial antes do Sprint 019.

## Critério de saída

O Sprint foi concluído porque:

1. o mesmo grafo executa forward e backward em C99;
2. a arena respeita orçamento configurável;
3. o scheduler não excede quatro workers;
4. cada candidato nativo é julgado por NumPy;
5. a aprovação completa também exige PyTorch;
6. incapacidade produz fallback, nunca aprovação;
7. o corpus automatizado cobre precisão dupla, simples, broadcasting, redução
   e views.

## Próximo passo

O Sprint 019 criará o laboratório científico tensorial pré-registrado para
responder, sem antecipar o resultado:

> Em quais workloads e condições o backend Casulo/T é mais rápido, equivalente
> ou mais lento que PyTorch eager e PyTorch Inductor CPU?
