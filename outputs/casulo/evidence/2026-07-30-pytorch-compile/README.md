# Prova pré-registrada contra PyTorch compile

Esta cadeia testa uma hipótese estreita e falsificável:

> Na MLP hidrológica declarada, em CPU, o backend Casulo/T C99/OpenMP
> apresenta mediana pareada superior ao baseline
> `pytorch-compile-inductor-cpu`, preservando equivalência e qualidade.

## Ordem de custódia

1. executor e juiz congelados no commit `45943cb`;
2. pré-registro 1.1 criado e congelado no commit `45c91ab`;
3. somente depois foi executada a medição oficial;
4. o juiz recalculou a mediana e o IC95% das 21 amostras brutas.

## Resultado

- classificação independente: `POSITIVE`;
- mediana pareada: `14,255580×`;
- IC95% independente: `12,496743×–15,383165×`;
- gate comercial pré-registrado de `6×`: aprovado;
- baseline mediano aquecido: `0,489609 s`;
- Casulo/T mediano: `0,035719 s`;
- compilação inicial do Inductor: `10,693516 s`, publicada separadamente;
- equivalência numérica: aprovada;
- falhas de integridade: nenhuma;
- baseline obrigatório ausente: nenhum;
- energia elétrica: não medida (`null`).

## Escopo exato

O resultado vale para esta carga e este ambiente: MLP 8–8–1, ReLU, MSE,
SGD, `float64`, lote completo com 1.024 registros, 400 épocas e um worker no
Core i5-1235U. No baseline, `torch.compile(..., backend="inductor",
fullgraph=True)` compila o modelo e seu backward; o laço de épocas e o passo
`torch.optim.SGD` permanecem no fluxo PyTorch. O Casulo/T funde o ciclo
completo em C99.

Não é uma alegação de superioridade sobre toda carga, GPU, arquitetura de rede
ou configuração PyTorch. É evidência positiva no escopo pré-registrado.

## Arquivos

- `preregistration.json`: hipótese, desenho, limiares e hashes de código;
- `capability-probe.json`: prova de disponibilidade do Inductor;
- `verdict.json`: julgamento independente e selado;
- `SHA256SUMS`: cadeia de integridade dos artefatos publicados.

O relatório bruto e visual está em
`benchmarks/results/2026-07-30-scientific-covenant-compile/`.
