# Resultado oficial — Sprint 022

**Classificação agregada:** `NEGATIVE`  
**Integridade:** aprovada  
**Execuções:** `9/9` completas  
**Claim:** bloqueado

## Resultado por baseline

| baseline | positivo | nulo | negativo |
|---|---:|---:|---:|
| PyTorch eager | 9 | 0 | 0 |
| PyTorch Inductor | 2 | 6 | 1 |

Todos os casos e reinícios venceram PyTorch eager com IC95% inferior acima de
`1×`. Isso é consistente no escopo medido.

A hipótese forte exigia também vitória em todos os reinícios contra Inductor.
Ela foi refutada por `tall-batch`, reinício 2:

- mediana `0,728×`;
- IC95% `[0,652×, 0,840×]`;
- classificação individual `NEGATIVE`.

## Medianas descritivas por execução

| caso | reinício | eager | Inductor | resultado |
|---|---:|---:|---:|---|
| tall-batch | 0 | 2,007× | 1,018× | NULL |
| tall-batch | 1 | 1,437× | 0,789× | NULL |
| tall-batch | 2 | 1,451× | 0,728× | NEGATIVE |
| wide-input | 0 | 4,230× | 1,892× | NULL |
| wide-input | 1 | 3,099× | 1,866× | NULL |
| wide-input | 2 | 2,809× | 1,999× | POSITIVE |
| deep-bottleneck | 0 | 1,862× | 0,820× | NULL |
| deep-bottleneck | 1 | 2,287× | 1,867× | POSITIVE |
| deep-bottleneck | 2 | 1,961× | 0,895× | NULL |

As medianas não substituem os intervalos nem a regra unânime. Em particular,
uma mediana acima de `1×` pode continuar `NULL` quando o intervalo cruza `1×`.

## Leitura científica

O resultado sustenta uma hipótese mais estreita: o Casulo/T com OpenBLAS
apresentou vantagem consistente sobre eager nos três workloads CPU float32.

O resultado não sustenta superioridade uniforme sobre Inductor. A variação
entre processos é material e precisa ser explicada antes de novo ensaio.

Nenhuma execução será removida ou repetida para alterar esta classificação.

