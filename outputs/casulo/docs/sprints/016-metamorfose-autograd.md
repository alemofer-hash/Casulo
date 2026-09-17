# Sprint 016 — Metamorfose Autograd

## Entrega

- ABI `casulo-gradient-rule-abi/0.1`;
- registro fechado e versionado de regras VJP;
- backward explícito `casulo-autograd-ir/0.1`;
- loss escalar obrigatória;
- acumulação determinística para fan-out;
- redução de gradientes após broadcasting;
- gradiente zero explícito para entradas desconectadas;
- regras para aritmética, ativações, reduções e views;
- backward de `matmul` rank 2;
- gradient check central por diferenças finitas;
- orçamento máximo de elementos verificados;
- comandos `t autograd-compile` e `t autograd-check`;
- exemplo linear com MSE.

## Invariantes

- operador sem regra de gradiente é bloqueado;
- versão da regra é vinculada à versão do operador;
- loss não escalar não forma backward;
- dtype não flutuante não recebe gradiente;
- fan-out nunca sobrescreve uma contribuição;
- ordem de acumulação é estável;
- broadcasting sempre retorna ao shape da entrada;
- entrada forward nunca é mutada;
- gradient check acima do orçamento é bloqueado;
- falha numérica é publicada como falha, não corrigida pelo juiz.

## Resultado

No exemplo `linear-mse-training.tensor.json`:

- oito elementos foram comparados;
- `x`, `weight` e `target` passaram;
- maior erro absoluto: `1,8191143036361268e-11`;
- SHA-256 da IR Autograd:
  `1287E4181ACE32C3FDA14DDCD600A848F74430C117DE0D46847955C097FAA530`.

Esse resultado é evidência de correção local do corpus, não de desempenho.

## Próximo passo

O Sprint 017 criará o executor tensorial NumPy de referência e o adaptador de
paridade PyTorch:

1. executar forward e backward pela mesma IR pública;
2. importar e exportar parâmetros sem cópia semântica;
3. comparar saídas, loss e gradientes operador a operador;
4. definir tolerâncias por dtype;
5. testar módulos MLP pequenos e médios;
6. registrar indisponibilidade de PyTorch como inconclusiva;
7. continuar sem liberar alegação de velocidade.
