# Laboratório científico tensorial 0.1/0.2

O laboratório responde uma pergunta estreita:

> No grafo, máquina, dtype, número de threads e fronteira medidos, qual é a
> relação de tempo aquecido entre Casulo/T, PyTorch eager e PyTorch Inductor?

Ele não responde se uma ferramenta é universalmente superior à outra.

## Protocolos

| Documento | Protocolo |
|---|---|
| pré-registro congelado do Sprint 019 | `casulo-tensor-lab-preregistration/0.1` |
| pré-registro atual | `casulo-tensor-lab-preregistration/0.2` |
| entrada | `casulo-tensor-lab-input/0.1` |
| relatório atual | `casulo-tensor-lab-report/0.2` |
| veredito atual | `casulo-tensor-lab-verdict/0.2` |

A versão `0.2` acrescenta provedor GEMM, SHA-256 do binário externo, threads do
GEMM e fase epistemológica. A evidência `0.1` permanece válida e imutável sob
seu próprio verificador.

## Fronteira medida

Cada invocação recebe tensores já materializados e executa:

```text
forward
→ loss escalar
→ backward dos parâmetros registrados
→ loss + gradientes
```

Ficam fora das amostras aquecidas:

- leitura e validação do grafo;
- geração das entradas;
- planejamento;
- geração C99;
- compilação GCC/Clang;
- preparação de ponteiros e tensores;
- primeira compilação do Inductor;
- paridade;
- relatório e julgamento.

Essas fases continuam registradas separadamente. O relatório também calcula
break-even quando um backend paga mais compilação e economiza tempo por
invocação.

## Pareamento

Todos os backends usam:

- mesmo grafo;
- mesmos valores de entrada;
- mesmo dtype;
- mesmo processo;
- mesmo índice de amostra;
- mesmo orçamento máximo de workers/threads;
- mesmo número de invocações internas.

A ordem percorre ciclicamente as seis permutações possíveis entre os três
backends. Isso distribui igualmente primeira, segunda e terceira posição.

## Qualidade antes da velocidade

Antes da medição:

1. Casulo/T é confrontado com NumPy em todos os intermediários, loss e
   gradientes;
2. PyTorch eager é confrontado com NumPy nos mesmos valores;
3. PyTorch Inductor é confrontado com NumPy em loss e gradientes;
4. shape, dtype, finitude e tolerância por dtype são verificados.

Falha de qualidade torna a evidência inválida. Indisponibilidade de um baseline
obrigatório produz resultado inconclusivo.

## Métrica primária

Para cada índice pareado:

```text
speedup = tempo_baseline / tempo_casulo
```

O juiz independente recalcula:

- mediana dos speedups pareados;
- IC95% bootstrap da mediana;
- classificação individual por baseline;
- classificação global.

O resultado global é positivo somente quando o limite inferior do IC95% fica
acima de `1×` contra todos os baselines obrigatórios. Um baseline com limite
superior abaixo de `1×` torna a hipótese negativa. Intervalos que cruzam `1×`
produzem resultado nulo.

O gate comercial de `6×` é separado da superioridade estatística. Um resultado
pode ser positivo e, corretamente, não atingir o gate comercial.

## Memória, CPU, temperatura e energia

- tempo de CPU é secundário porque a resolução do contador e a soma entre
  threads diferem do wall time;
- RSS é sondado numa fase separada e representa o processo inteiro;
- polling de RSS pode perder picos inferiores ao intervalo de 1 ms;
- frequência e temperatura são registradas quando o sistema operacional as
  expõe;
- energia elétrica fica `null` sem contador cumulativo integrado.

RSS não é usado para corrigir ou selecionar amostras de tempo.

## Pré-registro

```console
t tensor-lab-preregister \
  examples/tensor/mlp-mse-scientific.tensor.json \
  --output evidence/tensor-lab/preregistration.json \
  --wrt weight1 weight2 \
  --samples 21 \
  --warmups 3 \
  --inner-iterations 10 \
  --workers 4 \
  --gemm-workers 1 \
  --provider openblas \
  --prior-same-design-observed \
  --prior-exploratory-disclosure "Configuração observada no Sprint 021." \
  --claim-ineligible
```

O selo inclui o grafo, desenho e hashes do runner, backend tensorial,
adaptadores, autograd e tipos tensoriais.

Toda exploração anterior relevante deve ser declarada. Um desenho já observado
é selado como `CONFIRMATORY_REPLICATION_AFTER_EXPLORATION`; omitir a declaração
é violação do Pacto Científico.

`--claim-ineligible` é obrigatório por política para smoke tests e exploração.
Mesmo que as métricas sejam classificadas como positivas, o Juiz manterá
`claim=null` e `commercial_gate=false`.

## Execução e julgamento

```console
t tensor-lab-run \
  examples/tensor/mlp-mse-scientific.tensor.json \
  --preregistration evidence/tensor-lab/preregistration.json \
  --output benchmarks/results/tensor-lab

t tensor-lab-judge \
  --preregistration evidence/tensor-lab/preregistration.json \
  --report benchmarks/results/tensor-lab/tensor-lab-report.json \
  --output evidence/tensor-lab/verdict.json

t tensor-lab-verify \
  --preregistration evidence/tensor-lab/preregistration.json \
  --report benchmarks/results/tensor-lab/tensor-lab-report.json \
  --verdict evidence/tensor-lab/verdict.json
```

O relatório nasce com `claims_allowed=false`. Somente um veredito `POSITIVE`
pode materializar uma alegação, sempre acompanhada pelo escopo e pela lista do
que não foi provado.
