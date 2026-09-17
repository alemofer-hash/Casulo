# LarvaTensor e TensorIR 0.1

## Finalidade

LarvaTensor é o contrato estático que permite ao compilador T conhecer a forma,
o tipo numérico, o dispositivo, o layout, a propriedade e os aliases dos dados
antes de executar um kernel.

Esta versão é CPU-first. Ela não promete acelerar um treinamento por si só. A
função desta camada é tornar verificáveis as condições necessárias para que
backends posteriores possam fundir operações, reutilizar buffers e escolher
kernels sem alterar silenciosamente a semântica.

## Protocolos

| Protocolo | Identidade |
|---|---|
| tipo tensorial | `casulo-tensor-type/0.1` |
| ABI de operadores | `casulo-tensor-operator-abi/0.1` |
| manifesto de extensão | `casulo-tensor-extension/0.1` |
| representação intermediária | `casulo-tensor-ir/0.1` |

## Contrato de tipo

Cada tensor declara:

- `dtype`: `bool`, `int32`, `int64`, `float32` ou `float64`;
- `shape`: dimensões positivas ou símbolos estáveis;
- `device`: `cpu` nesta versão;
- `layout`: `contiguous` ou `strided`;
- `ownership`: `owned`, `borrowed` ou `view`;
- `alias_group`: identidade do armazenamento compartilhado;
- `mutable`: capacidade explícita de mutação.

Entradas `borrowed` são imutáveis. Uma `view` só é válida quando sua origem pode
ser rastreada por `alias_group`. Operadores mutantes, quando introduzidos por
extensão, só podem atingir tensores `owned` e `mutable`.

## Operadores fundamentais

O registro inicial contém:

- aritmética com broadcasting: `add`, `sub`, `mul` e `div`;
- álgebra linear: `matmul`;
- ativações: `relu`, `sigmoid` e `tanh`;
- reduções: `sum` e `mean`;
- views: `reshape` e `transpose`.

O frontend recusa aridade incorreta, dtype incompatível, dispositivos distintos,
shapes não broadcastáveis, dimensões internas inválidas em `matmul` e `reshape`
que altere o número estático de elementos.

## Documento declarativo

Um grafo pode ser baixado para TensorIR sem executar código:

```powershell
t tensor-compile examples/tensor/mlp-forward.tensor.json
t tensor-compile examples/tensor/mlp-forward.tensor.json `
  --output build/mlp-forward.tensor-ir.json
```

O documento usa `format = casulo-tensor-ir/0.1`, entradas tipadas, uma sequência
SSA de chamadas e ao menos uma saída. A saída incorpora a versão de cada
operador e um plano de memória.

## Memória

Quando todas as dimensões são estáticas, a IR publica:

- bytes das entradas;
- bytes realmente alocados por resultados `owned`;
- pico de bytes vivos, considerando o último uso de intermediários;
- views como aliases, sem contabilizá-las como nova alocação.

Se qualquer dimensão for simbólica, os valores de memória permanecem
explicitamente dinâmicos. O compilador não inventa um tamanho.

## Extensões

Extensões são manifestos TOML declarativos. A versão 0.1 registra schemas, mas
não carrega bibliotecas nem executa código externo.

```toml
format = "casulo-tensor-extension/0.1"

[extension]
name = "research-ops"
version = "1.0.0"
abi = "casulo-tensor-operator-abi/0.1"

[[operator]]
name = "square"
arity = 1
shape_rule = "identity"
dtype_rule = "same"
differentiable = true
```

ABI divergente, operador duplicado e regra desconhecida são bloqueados.

## Limite científico

Esta entrega prova validação estática, lowering determinístico e planejamento
de memória. Ela ainda não prova:

- execução numérica da TensorIR;
- autodiferenciação;
- paridade com operadores PyTorch;
- aceleração contra PyTorch eager ou compilado;
- redução de energia.

Essas alegações dependem de backends, corpus de equivalência e experimentos
pré-registrados posteriores.
