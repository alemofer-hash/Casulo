# Sprint 011 — SIMD

Corpus oficial:

- artefato:
  `sha256:eb82896a12b2bf904456c376365b244ae98692e35692c0c2209cf092d1d1ab7f`;
- dataset:
  `9dd1386e92761aa022ea1362ad8d0aa5bb9f17e41362295ec4c6676d7505eddf`;
- 2.000 registros únicos;
- protocolo `casulo-simd-benchmark/0.1`;
- perfil escalar estrito versus SIMD estrito.

Resultado:

- C99 escalar: `3,0884 ns/registro`;
- C99 SIMD: `2,7946 ns/registro`;
- ganho pareado: `1,117×`;
- IC95%: `1,084×–1,135×`;
- vetor reportado: 32 bytes, AVX2;
- equivalência: `true`;
- `sprint_011_exit_reached`: `true`.

O ensaio ponta a ponta permaneceu limitado pela fronteira:

- razão das medianas: `6,111×`;
- mediana pareada: `6,096×`;
- IC95%: `5,994×–6,231×`;
- participação isolada do kernel: aproximadamente `0,15%`.

Os arquivos `simd-benchmark-1.json`, `-8`, `-32`, `-256` e `-unique`
preservam a curva por tamanho. `native-benchmark-full.json` preserva a
medição completa.

Validação:

- Python 3.13: 90 testes e 42 subtestes;
- Python 3.11/3.12: 89 testes, um skip esperado e 42 subtestes;
- cobertura: 86%;
- compilação SIMD reproduzível na máquina declarada;
- wheel e sdist reproduzíveis;
- instalação limpa e comando `t simd-benchmark` aprovados.
