# Sprint 019 — laboratório científico tensorial

## Estado

Concluído com resultado oficial `NEGATIVE`.

## Pergunta

Comparar o backend CPU do Casulo/T com:

- PyTorch eager autograd CPU;
- PyTorch Inductor autograd CPU.

O foco é forward e backward de um MLP estático `float32`. Não é uma alegação
de cobertura ou superioridade geral sobre PyTorch.

## Desenho oficial

- entrada: `256×64`;
- camada oculta: `128`;
- saída: `32`;
- batch integral: `256`;
- parâmetros diferenciados: `weight1` e `weight2`;
- quatro workers/threads;
- 21 amostras;
- três warmups;
- 10 invocações por amostra;
- seis ordens de execução balanceadas;
- 2.000 reamostragens no relatório;
- 10.000 reamostragens independentes no juiz;
- superioridade: IC95% inferior acima de `1×`;
- gate comercial separado: IC95% inferior de `6×` contra todos.

## Controle de contaminação

Durante o desenvolvimento do runner houve um ensaio exploratório em outro
grafo:

- entrada `64×16`;
- camada oculta `32`;
- saída `8`;
- um worker;
- sete amostras;
- duas invocações internas.

Esse ensaio serve somente para depuração. O pré-registro oficial deve
declará-lo e usar o grafo maior, ainda não medido.

## Regra de congelamento

1. finalizar runner, juiz, testes e protocolo;
2. gerar o pré-registro;
3. commitar código e pré-registro;
4. somente então executar a medição oficial;
5. não alterar os arquivos selados após observar o resultado;
6. se houver falha lógica, preservar tudo e iniciar nova versão.

## Resultado oficial

| Comparação | Mediana | IC95% | Classe |
|---|---:|---:|---|
| Casulo/T versus eager | `0,232910×` | `0,213952×–0,255515×` | `NEGATIVE` |
| Casulo/T versus Inductor | `0,104399×` | `0,083294×–0,119623×` | `NEGATIVE` |

As três autoridades numéricas retornaram `PASS`. O resultado é negativo por
desempenho, não por divergência matemática.

O gate comercial de `6×` não foi atingido, nenhum claim foi liberado e energia
elétrica permaneceu `null`.

## Diagnóstico permitido

O backend geral ainda emite `matmul` próprio com laços C99, enquanto PyTorch
usa uma pilha madura de álgebra linear. Isso aponta, mas ainda não quantifica
por perfilamento, para:

- ausência de despacho BLAS/GEMM;
- ausência de packing de matrizes;
- blocking de cache elementar;
- transposes do backward não especializados;
- overhead OpenMP em kernels menores.

Uma correção precisa criar código e pré-registro novos. Esta rodada não pode
ser sobrescrita.
