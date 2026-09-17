# Executor NumPy e paridade PyTorch 0.1

## Finalidade

O executor NumPy é a implementação pública de referência da TensorIR e da
MetamorfoseAutogradIR. O adaptador PyTorch reconstrói o mesmo grafo, com os
mesmos dados, dtype, shapes e dispositivo CPU, e usa `torch.autograd` como
autoridade externa de comparação.

Esta camada responde:

> O forward, a loss e os gradientes do Casulo possuem a mesma semântica
> numérica que o grafo equivalente em PyTorch?

Ela não mede velocidade.

## Protocolos

| Camada | Identidade |
|---|---|
| executor de referência | `casulo-numpy-executor/0.1` |
| adaptador PyTorch | `casulo-pytorch-adapter/0.1` |
| relatório de paridade | `casulo-pytorch-parity/0.1` |

## Identidade da execução

Cada execução publica:

- SHA-256 canônico do forward, backward, regras e bindings;
- SHA-256 das entradas com nome, dtype, shape e bytes;
- versão do backend;
- descritor e SHA-256 de cada intermediário;
- descritor e SHA-256 de cada saída;
- descritor e SHA-256 de cada gradiente.

Execuções com identidades diferentes não podem ser comparadas.

## Tolerâncias

| dtype | absoluta | relativa |
|---|---:|---:|
| `float32` | `1e-5` | `1e-4` |
| `float64` | `1e-10` | `1e-9` |

Shape e dtype precisam ser idênticos antes da comparação numérica. Valores não
finitos produzem falha, mesmo quando aparecem nos dois caminhos.

## Vereditos

- `PASS`: todos os intermediários, loss e gradientes estão dentro do contrato;
- `FAIL`: ao menos uma grandeza divergiu;
- `INCONCLUSIVE`: PyTorch não está disponível ou o adaptador não suporta o
  grafo solicitado.

Indisponibilidade nunca é convertida em aprovação.

## Uso

Instalação explícita do runtime de paridade:

```powershell
python -m pip install -e ".[parity]"
t pytorch-doctor
t pytorch-doctor --compile
```

O primeiro diagnóstico executa uma multiplicação tensorial e seu backward.
Com `--compile`, o Casulo também localiza e ativa o MSVC no Windows, compila
um grafo real com `torch.compile(..., backend="inductor")` e compara a saída
compilada com a eager. Falha de importação, autograd, toolchain ou equivalência
retorna código de saída `3` e nunca é convertida em aprovação.

Execução NumPy com valores manifestados:

```powershell
t numpy-execute `
  examples/tensor/linear-mse-training.tensor.json `
  --input examples/tensor/linear-mse-input.json `
  --wrt x weight target
```

Paridade PyTorch:

```powershell
t pytorch-parity `
  examples/tensor/linear-mse-training.tensor.json `
  --input examples/tensor/linear-mse-input.json `
  --wrt x weight target `
  --output build/parity.json
```

## Resultado oficial do Sprint 017

Ambiente:

- NumPy `2.3.5`;
- PyTorch `2.12.1+cpu`;
- dispositivo `cpu`;
- MKL e oneDNN disponíveis.

Identidades:

- grafo:
  `4e774833fb42d67463b5491aba7c8f507e0cbbe3011c4316c7246f4f5626c61b`;
- entradas:
  `77a53f66d2c0734224b9e6452ac97960d0e421f93009bd14bfb90365e5265270`.

Foram comparados:

- `prediction`;
- `residual`;
- `squared`;
- `loss`;
- gradiente de `x`;
- gradiente de `weight`;
- gradiente de `target`.

Os sete checks passaram com erro absoluto máximo zero no exemplo `float64`.
O corpus automatizado também valida um MLP `float32` 64×16→32→8.

Duas execuções completas produziram o mesmo SHA-256 de relatório:

`EB64C67E12278CE4C14C9195A7A6396A2F9ED60EDA8B6FFC29857A516D2EE5F0`

## Anti-alegações

O relatório contém obrigatoriamente:

```json
{
  "timing": null,
  "energy_joules": null
}
```

Portanto, o Sprint 017 não prova:

- ganho sobre PyTorch;
- menor uso de memória;
- menor energia;
- cobertura da API PyTorch;
- treinamento de redes arbitrárias;
- desempenho sustentado.

Ele prova paridade apenas para os operadores, shapes e dtypes presentes no
corpus declarado.
