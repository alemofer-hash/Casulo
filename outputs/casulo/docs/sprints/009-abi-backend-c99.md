# Sprint 009 — ABI e backend C99 mínimo

## Hipótese

A CrisálidaIR do Marco 2 já continha informação suficiente para retirar o
bytecode Python do cálculo numérico sem retirar o envelope, a evidência ou o
oráculo de referência.

## Entrega

- `casulo-native-abi/0.1`;
- backend `c99-reference/0.1`;
- artefato portátil `casulo-artifact/0.6`;
- Casulo `0.9.0a1` e T `0.9.0-alpha.1`;
- fonte C99 e descritor ABI incluídos na identidade do artefato;
- compilação GCC/Clang/MSVC detectada em tempo de execução;
- DLL/SO derivada em cache imutável fora do artefato;
- validação de versão ABI e `artifact_id` na biblioteca;
- execução colunar `float64` por uma chamada nativa por lote;
- manifestação de estado e evidências na fronteira Python;
- fallback conservativo e opção `--native-required`;
- laboratório `casulo-native-benchmark/0.1`.

## Invariantes

1. a fonte C99 precisa ser regenerável da fonte T e da CrisálidaIR;
2. uma DLL de outro artefato nunca pode ser executada;
3. falha nativa não pode alterar silenciosamente a semântica;
4. tipos fora da ABI 0.1 usam o oráculo Python integral;
5. `judge` e `restrict` precisam bloquear antes da manifestação;
6. o artefato portátil não depende do binário da máquina que o construiu;
7. duas compilações equivalentes precisam produzir o mesmo SHA-256;
8. tempo de CPU continua não sendo chamado de joules.

## Resultado no i5-1235U

Configuração:

- Windows 11, CPython 3.13.2;
- GCC MinGW-W64 16.1.0;
- `WaterBalance`, 2.000 registros `float64`;
- 15 amostras alternadas de cinco iterações;
- escopo completo: marshal, kernel, evidência e envelopes.

Resultado observado:

- Python escalar: `38.585,02 ns/registro`;
- C99 nativo: `9.749,56 ns/registro`;
- ganho mediano ponta a ponta: `3,958×`;
- razão de trabalho de CPU: `3,833×`;
- equivalência semântica: preservada;
- primeiro artefato nativo: executado;
- compilação repetida: SHA-256 idêntico.

O ganho não satisfaz ainda o gate final de `5×–20×` do Marco 3. Isso é
deliberadamente registrado como `marco_3_exit_reached: false`: o Sprint 009
abre o Marco 3 e entrega a sua primeira prova; o Sprint 010 otimizará marshal,
alocações de evidência e manifestação.

## Gate

O critério imediato do Sprint 009 era gerar e executar um artefato nativo
reproduzível, manter fallback Python e provar equivalência. Ele foi satisfeito.

Validação final:

- Python 3.11: 83 testes, um skip opcional e 42 subtests;
- Python 3.12: 83 testes, um skip opcional e 42 subtests;
- Python 3.13: 84 testes e 42 subtests;
- cobertura total: 86%;
- wheel e sdist: `twine check` aprovado;
- duas builds limpas: hashes idênticos;
- wheel limpo instalado fora da árvore e `--native-required` executado.

Não foi demonstrado SIMD, paralelismo, ganho universal nem redução de joules.
O resultado vale para o kernel, escopo e máquina declarados.
