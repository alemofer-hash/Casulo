# Protocolo experimental da instancia viva

## Congelamento em camadas

1. TI3 congela intencao e requirements;
2. TI4 congela plano, sources T e TCAP;
3. TI5 congela ABI da primitive e schema de work receipt;
4. TI6 congela as nove mutacoes antes de executa-las;
5. TI8 congela tolerancias e oraculo;
6. TI10 congela ordem dos bracos e ablations;
7. TI13 congela holdouts antes de observar seus resultados.

Alterar uma camada depois do respectivo gate exige novo campaign ID.

## Unidade FloodSurrogate

1.024 registros reais, 8-8-1, ReLU, MSE, SGD, float64, full batch e 400 epocas.
Esperado por treinamento: 400 forwards, 400 backwards, 400 optimizer steps,
409.600 visitas e 32.400 escritas de parametros. O canario de oito registros e
rejeitado por contrato.

## Bracos

- A: baseline transparente sem T;
- B: T somente auditora;
- C: T arquiteta sem julgamento final;
- D: T arquiteta, auditora e juiza.

As primitives matematicas sao as mesmas quando a comparacao exigir causalidade
da politica. Comparacoes com PyTorch Eager ou worker nativo sao secundarias e
identificam a fronteira estrangeira.

## Ordem dos gates

Autoridade -> adversariais -> equivalencia -> contabilidade -> baselines ->
compressao -> verificador independente -> holdouts -> demonstracao. Nenhuma
medicao energetica e iniciada antes dos gates logicos.

## Decisao

Nenhum score agrega dimensoes. Resultado negativo e preservado. `UNKNOWN` e
`BLOCKED` sao estados de primeira classe. O estado maximo continua sendo uma
instancia, nao um teorema universal.

