# Backend CPU tensorial 0.1

O backend `c99-openmp-tensor/0.1` é a primeira execução nativa geral da
TensorIR e da MetamorfoseAutogradIR. Ele transforma um grafo já tipado e
derivado em uma biblioteca C99, executa forward e backward e só aprova o
resultado depois de confrontá-lo com as autoridades NumPy e PyTorch.

## Contratos

| Camada | Protocolo |
|---|---|
| plano | `casulo-tensor-cpu-plan/0.1` |
| ABI | `casulo-tensor-cpu-abi/0.1` |
| build | `casulo-tensor-cpu-build/0.1` |
| execução | `casulo-tensor-cpu-run/0.1` |
| paridade nativa | `casulo-tensor-cpu-parity/0.1` |

## Fluxo

```text
Egg tensorial
→ LarvaTensor
→ CrisálidaTensorIR
→ MetamorfoseAutogradIR
→ plano CPU
→ fonte C99/OpenMP
→ biblioteca endereçada por conteúdo
→ execução nativa
→ NumPy + PyTorch
→ Borboleta PASS / FAIL / INCONCLUSIVE / FALLBACK
```

## Planejamento conservador

O plano nativo exige:

- shapes inteiramente estáticos;
- dtype `float32` ou `float64`;
- rank máximo 4;
- operadores e versões conhecidos;
- tensores não mutáveis;
- views cujo layout possa ser provado;
- arena dentro do orçamento declarado.

Qualquer violação produz `FALLBACK` com motivo legível. O backend não converte
ausência de capacidade em sucesso nativo.

Regiões ponto a ponto consecutivas só são fundidas quando dtype e shape são
iguais. SIMD só é autorizado quando todas as entradas da região possuem o
mesmo shape e layout contíguo. `matmul` e reduções mantêm loops determinísticos
separados.

## Memória

Cada valor recebe um intervalo de vida. Buffers mortos podem ceder seu slot a
valores posteriores, sempre com alinhamento de 64 bytes. `reshape` e
`transpose` no forward são views; gradientes de views são materializados no
backward para manter a fronteira ABI simples.

O padrão é uma arena máxima de 64 MiB, configurável por:

```console
t tensor-cpu-plan graph.tensor.json --wrt weight --arena-budget 67108864
```

Se a necessidade exceder o orçamento, o plano publica ambos os números e
seleciona o executor de referência.

## Scheduler

O scheduler aceita somente `1`, `2`, `4` ou `auto`. O modo automático mantém
um worker para tensores compactos e só cresce dentro do limite de quatro
workers. O valor selecionado aparece no plano e é transmitido ao runtime
OpenMP.

O orçamento GEMM também aceita `--gemm-workers adaptive`. Nesse modo, cada
`matmul` recebe uma agenda determinística derivada somente de shape, FLOPs
escalares conhecidos e do teto global de workers. A agenda completa e a versão
da política ficam no plano. Ela não observa wall time, speedup ou backend rival.
No protocolo térmico atual, execuções experimentais ficam limitadas a dois
workers, mesmo que o backend genérico continue capaz de representar quatro.

## Uso

Planejar sem executar:

```console
t tensor-cpu-plan \
  examples/tensor/linear-mse-training.tensor.json \
  --wrt weight \
  --workers auto
```

Executar e julgar:

```console
t tensor-cpu-run \
  examples/tensor/linear-mse-training.tensor.json \
  --input examples/tensor/linear-mse-input.json \
  --wrt weight \
  --workers auto
```

`--no-fallback` transforma incapacidade nativa em erro. Sem essa opção, o
resultado preserva a execução NumPy e retorna `FALLBACK`.

## Proveniência

A chave de build inclui:

- hash da fonte gerada;
- versão do compilador;
- arquitetura e processador;
- versão do backend.

O manifesto preserva comando, compilador, hashes da fonte e biblioteca,
cache-hit e relatório de vetorização. A ABI também verifica em runtime o
protocolo, backend e hash do grafo antes de executar.

## Autoridades e vereditos

O candidato nativo é comparado valor a valor com NumPy:

- cada intermediário;
- loss;
- cada gradiente solicitado;
- shape, dtype, finitude e tolerância numérica.

Depois, o mesmo grafo é comparado com PyTorch. O resultado global é:

- `PASS`: nativo = NumPy e NumPy = PyTorch;
- `FAIL`: o candidato nativo divergiu do NumPy;
- `INCONCLUSIVE`: o nativo passou, mas PyTorch não pôde julgar;
- `FALLBACK`: o caminho nativo não era elegível ou operacional.

## Escopo 0.1

O backend cobre aritmética, `matmul` rank 2, ReLU, sigmoid, tanh, sum, mean,
reshape, transpose e as respectivas regras de backward geradas pela
Metamorfose Autograd.

Ainda não cobre:

- shapes dinâmicos;
- GPU;
- convoluções;
- `matmul` batched;
- mutação/in-place;
- redução por múltiplos eixos;
- cobertura equivalente à API PyTorch.

## Limite científico

Os tempos de compilação, preparação e execução são publicados separadamente,
mas classificados como `EXPLORATORY_DIAGNOSTIC`. `claim_eligible` é falso,
`energy_joules` é nulo e não existe campo de speedup.

O backend prova execução nativa correta no corpus coberto. Ele ainda não prova
ganho sobre PyTorch. Essa pergunta pertence ao laboratório pré-registrado do
Sprint 019.
