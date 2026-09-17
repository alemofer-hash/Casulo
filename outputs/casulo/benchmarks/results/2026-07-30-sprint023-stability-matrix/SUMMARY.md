# Sprint 023 — matriz de topologia e estabilidade

Todos os quatro perfis foram pré-registrados e commitados antes da primeira
medição.

| perfil | lote | CV Casulo | CV eager | CV Inductor |
|---|---:|---:|---:|---:|
| `p2-no-smt` | 1024 | 34,04% | 31,16% | 47,10% |
| `p2-smt` | 2048 | 5,88% | 19,16% | 16,74% |
| `e4` | 1024 | 25,28% | 51,03% | 44,58% |
| `p2-e2` | 1024 | 12,54% | 22,38% | 23,32% |

Os quatro vereditos são `INCONCLUSIVE`; o limite selado era 15%.

A tentativa inicial de `p2-smt` falhou antes das amostras porque o Windows não
criou o subprocesso `collect2.exe`. O binário existia e a repetição única foi
preservada como `p2-smt-retry1`.

Pelo critério exclusivamente metrológico, `p2-smt` é a frente de continuação.
O próximo desenho aumenta a duração para 2 segundos e o cooldown para 500 ms.
Speedup não participa da seleção.
