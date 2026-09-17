# RequirementGraph soberano em T/2.0

## Autoridade

O aggregate canônico é `HardFulfillmentInput`, definido no source T
`owner.critical.fulfillment`. Ele recebe identidade de projeto, versão de
schema, requisitos HARD, plano de evidência content-addressed e tokens de
evidência observados. Apenas T produz `FULFILLED`.

Verificadores Python permanecem permitidos como primitives independentes. O
método `FulfillmentEngine.collect_evidence` não possui campo `accepted` e não
calcula conclusão. `TRequirementGraphCompiler` apenas serializa fatos e hashes;
ele não retorna verdict. O método legado `evaluate` continua disponível para
compatibilidade RC13, mas não é consumido no caminho T85.

## Evidence plan

Cada obrigação HARD expande seus verificadores em tokens SHA-256 canônicos com:

- project ID;
- requirement ID;
- verifier ID;
- verdict esperado `PASS`;
- classe independente obrigatória.

O runtime T exige cardinalidade idêntica e presença exata de todos os tokens.
Isso não é substring: `contains` opera sobre elementos de uma lista de hashes.
`FAIL`, `UNKNOWN`, ausência, duplicação, self-report do gerador e project bleed
não podem coincidir com o token esperado.

## Holdouts TS6

Doze pedidos em quatro famílias foram congelados antes da geração. Como TS6 não
gerou seus agentes, todos permanecem `BLOCKED` por ausência de evidência; isso é
o resultado correto, não uma derrota ocultada. Cinco domain packs existentes e
um reparo arquitetural possuem caminhos positivos com verificadores reais.

A regressão Einstein separa o texto genérico, que bloqueia, do avaliador local
4D existente, cujo kernel constrói conexão, Ricci, escalar, Einstein e resíduo
de Minkowski. O claim de solver global continua negado.
