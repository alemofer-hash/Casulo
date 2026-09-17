# Perfil SIMD 0.1

O perfil `casulo-simd/0.1` é a primeira entrega do Marco 4. Ele acelera somente
operações que a CrisálidaIR já classificou como numéricas, lineares e
independentes entre registros.

## Transformação

O backend `c99-simd/0.3` divide cada operação elegível em duas fases:

```text
registros
→ guardas escalares em ordem
→ laço numérico independente
→ resultados e evidências laterais
```

A fase de guardas mantém:

- ordem dos registros;
- ordem de `judge` e `restrict` dentro do registro;
- identificação do primeiro registro inválido;
- índice da primeira instrução que falhou.

Somente os `let` dos quais uma guarda depende são repetidos nessa fase. O laço
numérico é executado apenas depois de todo o lote ser validado.

## Perfis de compilação

`scalar`

- `-O3`;
- `-fno-tree-vectorize` no GCC;
- ponto flutuante estrito;
- alvo portátil;
- funciona como controle experimental.

`simd`

- `-O3`;
- `-march=native`;
- vetorização habilitada;
- `-fno-fast-math`;
- `-ffp-contract=off`;
- relatório de vetorização preservado.

O artefato assinado contém C99 portátil. A DLL ou SO SIMD é um derivado local,
endereçado também pelo alvo da CPU; ela não é distribuída como se fosse
portátil para outra máquina.

## Gate

O comando:

```console
t simd-benchmark ARTIFATO --input LOTE.json
```

compila os perfis escalar e SIMD a partir da mesma fonte, prova equivalência
exata, alterna a ordem das medições e calcula IC95% pareado por bootstrap.

O gate exige simultaneamente:

1. equivalência semântica;
2. ao menos um laço confirmado como vetorizado pelo compilador;
3. ao menos 512 registros no lote;
4. limite inferior do IC95% do ganho acima de `1,0`.

## Limites

- a fase de guardas ainda é escalar;
- SIMD não é selecionado como ganho comprovado para lotes pequenos;
- alinhamento explícito, scheduler de quatro núcleos e afinidade pertencem aos
  próximos sprints;
- tempo de CPU não é medida de joules;
- o perfil não relaxa a semântica numérica para perseguir benchmark.
