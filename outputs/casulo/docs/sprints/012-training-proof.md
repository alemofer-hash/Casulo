# Sprint 012 — prova de treinamento científico

## Hipótese

A linguagem T pode usar a semântica completa de uma rede compacta para fundir
forward, backward, redução de gradientes e SGD, reduzindo tráfego e despacho
sem alterar dataset, treinamento ou qualidade.

## Entrega

- Casulo `0.12.0a1` e T `0.12.0-alpha.1`;
- especificação `casulo-training-spec/0.1`;
- artefato `casulo-training-artifact/0.1`;
- ABI `casulo-training-abi/0.1`;
- backend `c99-openmp-fused/0.4`;
- benchmark `casulo-training-benchmark/0.1`;
- equivalência `casulo-training-equivalence/0.1`;
- scheduler `casulo-training-scheduler/0.1`;
- comando `t training-experiment`;
- baseline PyTorch/MKL/AVX2;
- partições de treino e validação;
- relatório JSON e HTML autocontido.

## Resultado principal

Execução automática final no Intel Core i5-1235U:

- PyTorch eager CPU mediano: `451,1036 ms`;
- Casulo/T mediano: `48,9430 ms`;
- ganho mediano pareado: `9,743443×`;
- IC95%: `9,216918×–10,528480×`;
- gate de `6×`: aprovado;
- MSE de validação: `0,0431936743`;
- R² de validação: `0,956806`;
- diferença RMSE entre predições: `1,778 × 10⁻¹⁶`;
- equivalência e determinismo: aprovados;
- energia elétrica: não medida.

Os tempos absolutos variaram com a carga do sistema. Três execuções oficiais
independentes de 21 pares, usando o mesmo artefato otimizado, produziram
medianas de `8,212×`, `9,135×` e `9,743×`. O menor limite inferior foi
`7,809×`, ainda acima do gate.

## O que foi aprendido

Quatro workers não são automaticamente melhores. Para este lote:

```text
1 worker → 8,212×
2 workers → 5,276×
4 workers → 5,025×
```

A Crisálida escolhe um worker porque a rede é pequena. Isso confirma a tese de
otimização de tráfego: eliminar sincronização inútil pode valer mais que ocupar
todos os núcleos.

## Estado do Marco 4

O Sprint 012 prova ganho substancial em treinamento e implementa a primeira
decisão limitada de workers. Ele não encerra o Marco 4 geral: eficiência acima
de 70% em quatro núcleos ainda não foi demonstrada para cargas grandes.
