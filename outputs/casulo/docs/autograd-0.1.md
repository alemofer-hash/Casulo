# Metamorfose Autograd 0.1

## Finalidade

Metamorfose Autograd transforma uma `CrisálidaTensorIR` forward em um backward
explícito. Cada derivada, redução de broadcasting, transpose e acumulação pode
ser inspecionada antes de qualquer treinamento.

O protocolo não trata diferenciação como um efeito oculto do runtime.

## Protocolos

| Camada | Identidade |
|---|---|
| ABI das regras | `casulo-gradient-rule-abi/0.1` |
| IR forward/backward | `casulo-autograd-ir/0.1` |
| verificação numérica | `casulo-gradient-check/0.1` |

## Regras fundamentais

A versão 0.1 possui VJPs versionados para:

- `add`, `sub`, `mul` e `div`;
- `matmul` de matrizes rank 2;
- `relu`, `sigmoid` e `tanh`;
- `sum` e `mean`;
- `reshape` e `transpose`.

Um operador sem regra correspondente é recusado. `matmul` em lote continua fora
do escopo desta versão e também é recusado no backward.

## Formação do backward

O lowering:

1. exige uma saída loss escalar e flutuante;
2. cria uma semente `ones_like(loss)`;
3. percorre a TensorIR na ordem topológica reversa;
4. aplica a regra VJP vinculada à versão exata do operador;
5. reduz gradientes de broadcasting para o shape da entrada;
6. acumula contribuições em ordem determinística;
7. cria `zeros_like` explícito para uma entrada desconectada;
8. publica um binding final para cada entrada declarada em `wrt`.

Todos os gradientes produzidos são `owned`, imutáveis e recebem um grupo de
alias próprio. O backward não escreve nas entradas forward.

## CLI

Formação e inspeção:

```powershell
t autograd-compile `
  examples/tensor/linear-mse-training.tensor.json `
  --wrt x weight target
```

Verificação central por diferenças finitas:

```powershell
t autograd-check `
  examples/tensor/linear-mse-training.tensor.json `
  --input examples/tensor/linear-mse-input.json `
  --wrt x weight target
```

O gradient check exige NumPy, disponível no extra `ml`. A compilação do
backward permanece independente de NumPy.

## Gate numérico

Para cada elemento treinável, o verificador calcula:

```text
f(x + epsilon) - f(x - epsilon)
─────────────────────────────────
           2 × epsilon
```

O valor é comparado com o gradiente analítico usando tolerância absoluta e
relativa declaradas. Todos os elementos são verificados até `max_elements`; o
limite nunca é ultrapassado silenciosamente.

O exemplo oficial do Sprint 016 verificou oito elementos com:

- `epsilon = 1e-6`;
- tolerância absoluta `1e-6`;
- tolerância relativa `1e-5`;
- maior erro absoluto `1,8191143036361268e-11`;
- veredito `passed = true`.

## Limites científicos

Esta entrega demonstra a coerência do backward no corpus implementado. Ela não
demonstra:

- cobertura equivalente à API PyTorch;
- execução eficiente de treinamento;
- paridade numérica com PyTorch;
- superioridade de tempo, memória ou energia;
- `matmul` batched no backward;
- derivadas de extensões externas.

O executor NumPy usado pelo gradient check é um instrumento interno de
validação, não o runtime tensorial geral do produto.
