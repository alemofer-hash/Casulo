# Casulo/T — prova de treinamento científico

## Resultado final

| Item | Resultado |
|---|---:|
| PyTorch eager CPU | 451,1036 ms |
| Casulo/T C99 fundido | 48,9430 ms |
| Ganho mediano pareado | **9,743443×** |
| IC95% | **9,216918×–10,528480×** |
| MSE de validação | 0,0431936743 |
| R² de validação | 0,956806 |
| Gate de 6× | **aprovado** |

Baseline: PyTorch 2.12.1 CPU, MKL/oneDNN e AVX2. A mesma rede, dataset,
inicialização, SGD, taxa e 400 épocas foram usados nos dois backends.

## Replicações oficiais

| Rodada | Mediana pareada | IC95% |
|---|---:|---:|
| otimizada, worker 1 | 8,211641× | 7,808888×–8,450584× |
| scheduler auto, repetição 1 | 9,134510× | 8,616880×–9,749974× |
| scheduler auto, repetição 2 | 9,743443× | 9,216918×–10,528480× |

As três rodadas possuem 21 pares e 2.000 reamostragens bootstrap. O menor limite
inferior observado foi `7,808888×`.

## Verificação independente

Na raiz do repositório:

```console
python tools/verify_training_evidence.py
```

O verificador usa somente a biblioteca padrão do Python. Ele confere os
checksums dos sete arquivos, a identidade content-addressed do artefato, o hash
do dataset, as razões pareadas, a equivalência numérica e o conteúdo exato
incorporado às provas visuais. Ele também recalcula um bootstrap independente
nas três rodadas oficiais e exige limite inferior acima de 6× em todas elas.

## Tradução visual

Aplicado linearmente, o ganho final transforma seis horas em aproximadamente
36 minutos e 57 segundos. Essa é uma projeção de escala. A carga efetivamente
cronometrada dura milissegundos; uma alegação literal de horas exige um ensaio
longo equivalente.

## Escopo

- surrogate hidrológico sintético e versionado;
- MLP `8 → 8 ReLU → 1`;
- 1.024 registros de treino e 256 de validação;
- full-batch SGD `float64`;
- 400 épocas;
- scheduler automático selecionou um worker;
- energia elétrica não medida;
- não representa qualquer rede, GPU ou biblioteca não testada.

Casulo é um invento original da Teloscorp para Otimização de Tráfego de
Informação.
