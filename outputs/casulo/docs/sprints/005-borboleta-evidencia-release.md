# Sprint 005 — Borboleta

## Resultado

A linguagem T passou a liberar evidência reproduzível da otimização, além do
artefato executável. A Borboleta candidata a beta entrega:

- dataset hidrológico sintético versionado e determinístico;
- comparação referência escalar × lote fundido;
- prova SHA-256 de equivalência da saída integral;
- aquecimento, ordem alternada e amostras brutas;
- intervalo de confiança de 95% por bootstrap;
- tempo de parede, CPU e memória residente observada;
- joules somente quando há contador elétrico real;
- relatório JSON para máquinas e HTML autocontido para demonstração;
- API Python pública e comando `t experiment`;
- testes por exemplo e por propriedades;
- build de wheel/sdist e release automatizada por tag.

## Critério de saída

Esta sprint termina quando:

1. os testes passam em Python 3.11, 3.12 e 3.13;
2. o corpus de propriedades não encontra divergência escalar/lote;
3. um experimento canônico gera os quatro arquivos esperados;
4. wheel e sdist passam por `twine check`;
5. a instalação limpa do wheel executa `t doctor`;
6. o relatório declara explicitamente quando energia não foi medida.

## Próxima metamorfose

A Borboleta mede o runtime de referência. O passo seguinte, sem prometer
milagres físicos, é compilar kernels numéricos para um backend nativo e comparar:

1. Python escalar;
2. lote Python atual;
3. backend nativo de um núcleo;
4. backend nativo limitado a quatro núcleos;
5. implementação científica de referência.

A meta útil é reduzir movimentação de objetos, alocações e interpretações por
registro. Nenhuma otimização de instrução substitui 256 processadores em carga
perfeitamente paralela; a oportunidade real aparece quando o baseline desperdiça
trabalho ou quando o grafo permite fusão, deduplicação e especialização.
