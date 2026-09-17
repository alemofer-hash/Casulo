# Sprint 010 — AOT, arena e encerramento do Marco 3

## Hipótese

O Sprint 009 mostrou que o cálculo já não era o gargalo. O custo restante vinha
de validar e copiar cada número duas vezes, alocar buffers por chamada e
materializar evidências por um caminho genérico.

## Entrega

- Casulo `0.10.0a1` e T `0.10.0-alpha.1`;
- `casulo-artifact/0.7`;
- backend `c99-aot/0.2`;
- remoção de código morto;
- propagação de constantes e aliases;
- arena colunar reutilizável;
- crescimento de capacidade em potência de dois;
- validação e marshal fundidos;
- manifestação especializada por operação;
- protocolo de benchmark nativo 0.2;
- decomposição de estágios;
- IC95% pareado por bootstrap;
- dataset integral e manifesto publicados.

## Resultado oficial

Ambiente:

- Intel Core i5-1235U;
- Windows 11;
- CPython 3.13.2;
- GCC MinGW-W64 16.1.0;
- 2.000 registros hidrológicos;
- 2.000 registros únicos, 0% de duplicação;
- 21 amostras alternadas, cinco iterações;
- cache desativado em ambos os caminhos.

Resultado:

| Caminho | ns/registro mediano | registros/s |
|---|---:|---:|
| Python escalar completo | 11.899,13 | 84.039,76 |
| C99 completo | 2.029,06 | 492.839,05 |
| marshal isolado | 652,92 | 1.531.581,20 |
| kernel C99 pré-materializado | 4,0409 | 247.471.154 |
| manifestação isolada | 1.336,92 | 747.987,91 |

- razão das medianas: `5,864×`;
- mediana dos ganhos pareados: `5,966×`;
- IC95% pareado: `5,866×–6,169×`;
- razão de trabalho de CPU: `3,500×`;
- equivalência semântica: preservada;
- limite inferior do IC95% acima de `5×`: sim.

Os tempos absolutos sofreram carga concorrente durante a rodada; o desenho
pareado conserva essa variação nos dois caminhos. O veredito usa o intervalo
do ganho, não um único melhor tempo.

## Gate

O Marco 3 exigia:

- `5×–20×` sobre Python escalar em kernel numérico;
- equivalência;
- artefato reproduzível;
- fallback sem mudança silenciosa de semântica.

O resultado ponta a ponta superou `5×`, inclusive no limite inferior do IC95%.
A compilação reproduzível continua coberta em Windows e integra a matriz
Windows/Linux do CI. O fallback e `--native-required` permanecem ativos.

Marco 3 encerrado para o escopo declarado.

## Validação final

- Python 3.13: 87 testes e 42 subtestes;
- Python 3.11 e 3.12: 86 testes, um skip esperado e 42 subtestes;
- cobertura total: 86%;
- wheel e sdist: `twine check` aprovado;
- duas builds limpas de wheel:
  `c421fd33923cccce538c89cea287b2c778d72a00fb85dbc1b03ceb430cd265f0`;
- duas builds normalizadas de sdist:
  `37a325eb2e97224469d706a5637ce1310b51d13fb7628dd826af063bd49e728c`;
- wheel instalado em ambiente virtual limpo;
- `t doctor`, build nativo e execução com `--native-required` aprovados.

Isso não prova SIMD, quatro núcleos, ganho universal nem redução de joules.
