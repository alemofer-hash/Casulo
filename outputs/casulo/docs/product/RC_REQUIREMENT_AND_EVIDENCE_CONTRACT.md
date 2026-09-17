# Contrato de requisitos e evidência

## RequirementGraph

Cada pedido é decomposto em requisitos únicos, `HARD` ou `SOFT`, ponderados,
provenientes e ligados a verificadores nomeados. Dependências formam DAG.
Requisito HARD desconhecido vale bloqueio, nunca sucesso implícito.

## Evidência

Classes aceitas: type check, compile, propriedade, simulação, execução limpa,
invariante de domínio e revisão humana. `GENERATOR_SELF_REPORT` é armazenado
como diagnóstico, mas não satisfaz requisito.

Um requisito só recebe PASS quando todos os seus verificadores obrigatórios
independentes produzem PASS. Qualquer FAIL independente prevalece. Ausência,
timeout ou incompatibilidade resulta UNKNOWN.

## Aceite

```text
Accept = todos HARD PASS
      AND Safety PASS
      AND UnsupportedClaims == 0
```

Coverage e SpecGap são auxiliares. Eles nunca compensam requisito duro. O
payload testado, hashes de entrada, artifact hash, produtor e timestamp ficam
no receipt.

## Reparação

Diagnostics reais voltam ao gerador dentro de budget finito. A candidata não
altera a criação viva até que o grafo inteiro passe e o humano confirme deltas
materiais. Esgotado o budget, o gap é mostrado honestamente.

