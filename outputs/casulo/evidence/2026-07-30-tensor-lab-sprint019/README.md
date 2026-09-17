# Prova pré-registrada do backend tensorial geral

Esta cadeia testou uma hipótese estreita e falsificável:

> No MLP estático registrado, com quatro threads em CPU, o backend tensorial
> geral Casulo/T apresenta menor wall time aquecido que PyTorch eager e
> PyTorch Inductor, preservando correção numérica.

## Ordem de custódia

1. runner, juiz, grafo e critérios foram congelados no commit `ea25297`;
2. o pré-registro recebeu a identidade
   `sha256:2ab07fb6f50212c5715328c421f033c6039267191dbe639b8903b3c356f69622`;
3. a tag `casulo-tensor-lab-preregister-v0.20.0a1` foi criada;
4. somente depois ocorreu a medição oficial;
5. o juiz recalculou as métricas das 21 amostras brutas.

## Resultado

- classificação: `NEGATIVE`;
- Casulo/T versus PyTorch eager:
  - mediana: `0,232910×`;
  - IC95%: `0,213952×–0,255515×`;
- Casulo/T versus PyTorch Inductor:
  - mediana: `0,104399×`;
  - IC95%: `0,083294×–0,119623×`;
- qualidade Casulo/T versus NumPy: `PASS`;
- qualidade NumPy versus PyTorch eager: `PASS`;
- qualidade Inductor versus NumPy: `PASS`;
- gate comercial de `6×`: não aprovado;
- claim: `null`;
- energia elétrica: não medida (`null`).

Em termos inversos, neste desenho o backend atual demorou aproximadamente
`4,29×` o tempo do eager e `9,58×` o tempo do Inductor.

## Escopo

- grafo `256×64 → 128 → 32`;
- ReLU e MSE;
- forward e backward de `weight1` e `weight2`;
- `float32`;
- 4 workers/threads;
- 10 invocações por amostra;
- 21 amostras;
- Core i5-1235U, 16 GB;
- PyTorch `2.12.1+cpu`;
- GCC `16.1.0`.

## Interpretação técnica

O resultado não refuta a especialização do Casulo/T demonstrada nos kernels
fundidos de treinamento anteriores. Ele refuta, para este escopo, a hipótese
de que o backend tensorial geral `0.1` já compete com bibliotecas maduras em
álgebra linear densa.

O candidato usa `matmul` C99 próprio com laços explícitos. PyTorch dispõe de
kernels de álgebra linear altamente otimizados. Essa diferença arquitetural é
uma hipótese forte para o gargalo, mas ainda precisa de perfilamento por kernel
antes de ser tratada como causa quantitativamente provada.

O resultado indica uma correção lógica possível, não permissão para alterar a
evidência: despacho para GEMM otimizado, blocking por cache, packing,
especialização de transposes e nova pré-inscrição em protocolo posterior.

## Memória e energia

A arena Casulo/T exigiu `688.256` bytes. A sonda RSS foi executada numa fase
separada e mede o processo inteiro, portanto não autoriza comparar consumo
exclusivo dos backends. Temperatura não foi exposta pelo sistema operacional.
Energia permanece `null`.
