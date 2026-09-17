# Contrato epistemológico e de alegações

## Hierarquia de evidência

1. dados brutos, binários hashados e receipts;
2. código executado e contratos compilados;
3. verificação independente e testes;
4. análise derivada reproduzível;
5. relatório da campanha;
6. documentação de arquitetura;
7. narrativa histórica.

Uma camada inferior não pode corrigir silenciosamente a superior.

## Classes de enunciado

| Classe | Significado | Prova exigida |
|---|---|---|
| `FORMAL_PROPOSITION` | conclusão que decorre das premissas declaradas | derivação e premissas explícitas |
| `EMPIRICAL_ASSUMPTION` | condição necessária, ainda observável | protocolo de teste ou limitação |
| `OBSERVED_INSTANCE` | medição delimitada | artefato, hash, protocolo e reprodução |
| `UNPROVEN_GENERALIZATION` | extrapolação além da evidência | deve permanecer hipótese |

## Claim máximo corrente

No host e protocolo preservados, T governou causalmente nove decisões críticas
em três workloads; o verificador independente aprovou equivalência operacional
e a campanha observou redução material não energética em tempo, CPU/ciclos e
pico RSS, incluindo overhead end-to-end medido. Não houve medição de joules.

## Fronteiras residuais obrigatórias

- o envelope criptográfico do Flood é produzido pelo supervisor após o kernel
  síncrono; contadores são internos, mas o hash não nasce assinado no kernel;
- a redução principal combina AOT lean e remoção de overhead de framework; não
  prova eliminação da matemática da rede;
- o verificador é independente do trainer, mas não formalmente provado sólido;
- o estudo atual é single-host e usa três workloads pequenos;
- o tempo humano de interlocução é indisponível na campanha;
- energia é `UNAVAILABLE`, jamais zero.

## Regra de linguagem

Evite `prova` sem qualificador. Prefira `evidência`, `instância validada`,
`proposição condicional`, `resultado observado` e `fronteira de aplicabilidade`.
