# Protocolo de treinamento científico 0.1

O protocolo `casulo-training-benchmark/0.1` mede uma rede neural completa,
pequena e reproduzível. Ele existe para responder a uma pergunta comercial
específica:

> Uma carga de treinamento que leva X pode, no mesmo hardware e com a mesma
> qualidade, terminar em menos de X/6?

## Baseline

O baseline não é Python escalar:

- PyTorch `2.12.1+cpu`;
- modo eager;
- Intel MKL/oneDNN;
- AVX2;
- `torch.optim.SGD`;
- `float64`;
- número de threads igual ao número de workers selecionado.

O resultado não declara superioridade sobre `torch.compile`, GPU, CUDA, JAX,
XLA ou qualquer outra forma que não tenha sido medida.

Desde o Pacto Científico 1.0, esse protocolo possui dois modos:

- sem pré-registro: execução exploratória, incapaz de liberar alegação pública;
- com pré-registro: parcela elegível para julgamento independente.

Se o pré-registro exigir `torch.compile`, um resultado positivo contra eager
continua válido nesse escopo, mas o veredito geral permanece `INCONCLUSIVE`
até o baseline compilado ser efetivamente medido.

## Carga declarada

- surrogate hidrológico `FloodSurrogate`;
- oito variáveis de entrada;
- uma camada oculta com oito unidades ReLU;
- uma saída;
- 1.024 registros de treino;
- 256 registros separados para validação;
- full-batch SGD;
- 400 épocas;
- learning rate `0,018`;
- loss MSE;
- seed dos parâmetros `260730`;
- seed do dataset `20260730`;
- meta pré-fixada de MSE de validação `≤ 0,08`.

## Equivalência

PyTorch e Casulo/T recebem:

1. os mesmos bytes de entrada;
2. os mesmos parâmetros iniciais;
3. a mesma arquitetura;
4. a mesma ativação;
5. a mesma taxa;
6. o mesmo otimizador;
7. o mesmo número de épocas.

O gate exige determinismo interno de cada backend, diferença máxima de
parâmetros e predições dentro da tolerância declarada e meta de validação
atingida pelos dois lados.

## Medição

- 3 aquecimentos;
- 21 amostras pareadas;
- ordem alternada;
- mediana dos ganhos pareados;
- IC95% por bootstrap de 2.000 reamostragens;
- tempos brutos preservados.

O gate de `6×` somente abre quando:

```text
treinamento equivalente
∧ meta de validação atingida
∧ limite inferior do IC95% ≥ 6
```

Esse gate pertence ao baseline contido no relatório. Uma alegação que reúna
vários baselines depende adicionalmente do veredito do Pacto Científico.

## Scheduler Crisálida

O protocolo aceita apenas 1, 2 ou 4 workers. Em `auto`, a Crisálida estima o
trabalho por época e recusa paralelismo quando sincronização e redução custariam
mais que o lote.

Para a forma `1.024 × 8 × 8`, o seletor escolhe um worker. A matriz experimental
confirmou a decisão:

| Workers | PyTorch mediano | Casulo/T mediano | Ganho pareado |
|---:|---:|---:|---:|
| 1 | 139,4072 ms | 16,9491 ms | 8,2116× |
| 2 | 175,1129 ms | 35,3767 ms | 5,2764× |
| 4 | 187,7337 ms | 36,6565 ms | 5,0245× |

Mais núcleos pioraram os dois backends nesta carga compacta. O resultado
correto foi retirar atrito, não forçar paralelismo.

## Limites

- a carga efetivamente medida dura milissegundos;
- “seis horas → aproximadamente 37 minutos” é projeção linear para explicar a
  escala, não uma execução literal de seis horas;
- energia elétrica não foi medida;
- o dataset é sintético e versionado;
- a rede é um surrogate compacto, não um treinamento generativo ou GPU;
- validação independente ainda é necessária.
