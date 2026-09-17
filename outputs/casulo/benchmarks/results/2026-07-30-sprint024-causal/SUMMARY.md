# Sprint 024 — diagnóstico causal dos três grafos

Os perfis são estruturais: não medem runtime e não liberam claim.

| caso | instruções | GEMMs | FLOPs conhecidos | fração GEMM | tráfego lógico | reuso arena |
|---|---:|---:|---:|---:|---:|---:|
| tall | 19 | 5 | 9.870.336 | 98,60% | 2.557.456 B | 26,89% |
| wide | 19 | 5 | 5.635.584 | 99,43% | 804.880 B | 26,78% |
| deep | 26 | 8 | 14.115.840 | 99,24% | 2.141.200 B | 30,70% |

## Diagnóstico

O trabalho aritmético conhecido é inequivocamente dominado por GEMM. Os três
grafos já evitam materializar views e reutilizam parte relevante da arena.
Somente duas regiões fundidas aparecem em cada grafo.

A ordem causal de ataque passa a ser:

1. threads e provedor por GEMM/shape;
2. evitar oversubscription em CPU híbrida;
3. destination passing e fusões adicionais;
4. provedores alternativos;
5. autotuning selado.

Isso não prova que GEMM domina o wall time. O falsificador explícito é uma
ablação em que mudar provedor/threads não altera materialmente o tempo. A matriz
de seis variantes está embutida em cada JSON.

Nenhum speedup foi calculado e `claim=null`.
