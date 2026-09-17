# Teorema da Interlocucao — formulacao V1

## Estatuto epistemico

O nome historico e mantido como nome da tese. Neste documento, a parte formal e
uma proposicao condicional; a implementacao sera uma instancia empirica
falsificavel. Uma instancia aprovada nao demonstra universalidade.

Etiquetas usadas:

- `FORMAL_THEOREM`: consequencia das definicoes e premissas declaradas;
- `EMPIRICAL_ASSUMPTION`: condicao que precisa ser observada ou testada;
- `OBSERVED_INSTANCE`: medicao reproduzivel de um workload delimitado;
- `UNPROVEN_GENERALIZATION`: extrapolacao proibida pela evidencia atual.

## Objetos

- `I`: expressao humana inicialmente incompleta;
- `O`: observacoes explicitamente ditas ou inferidas, sempre com proveniencia;
- `G`: lacunas materiais cuja resolucao pode mudar o artefato ou o criterio de
  sucesso;
- `R`: contrato semantico confirmado por humano, composto de requirements,
  tolerancias e efeitos observaveis;
- `P`: processo de treinamento de referencia;
- `T_R(P)`: processo governado por uma politica T compilada para `R`;
- `V_R`: verificador independente e read-only de `R`;
- `C(P)`: vetor de custos, nunca um escalar sintetizado depois dos resultados.

`Interlocucao(I)` e o processo que transforma `I` em `(O,G,R)` sem permitir que
o modelo neural confirme a propria inferencia. `R` e suficiente somente quando
nenhuma lacuna material conhecida permanece sem estado `RESOLVED`, `UNKNOWN` ou
`BLOCKED`, e o humano confirma a representacao.

## Integridade e equivalencia

`T_R(P) equiv_R P` quando ambos satisfazem todos os requirements HARD e todos os
efeitos observaveis de `R` dentro das tolerancias congeladas. Equivalencia
operacional nao exige identidade de bits, de numero de passos ou de estado
interno, salvo quando tais propriedades pertencem a `R`.

Integridade semantica significa: nenhum requisito HARD confirmado e perdido,
nenhum efeito fora de `R` e apresentado como cumprimento, nenhum `UNKNOWN` vira
`PASS`, e toda eliminacao de trabalho tem justificativa verificavel de
irrelevancia relativa a `R`.

## Proposicao condicional (`FORMAL_THEOREM`)

Se:

1. `R` e suficiente para a finalidade declarada;
2. as nove decisoes criticas sao causalmente governadas por T;
3. todo estado ou trabalho eliminado e irrelevante sob `R`;
4. `V_R` e solido para os requisitos que afirma verificar;
5. receipts correspondem ao trabalho realmente executado;
6. o publicador consome o julgamento T e falha fechado;

entao uma execucao aceita de `T_R(P)` preserva os observaveis declarados em `R`.
Esta conclusao segue das premissas; a validade das premissas e empirica.

Existe compressao liquida numa dimensao `k` quando, para protocolo congelado,

`C_k(T_R(P)) = C_k(P) - C_k(E_redundante) + C_k(T)`

e a reducao observada, incluindo todo overhead atribuivel a T, e positiva. A
equacao organiza a contabilidade; nao prova que `E_redundante` exista nem que a
reducao seja material.

## Premissas empiricas

- receipts internos nao podem ser fabricados pelo runner;
- as mutacoes T sao a unica mudanca entre pares causais;
- o oraculo e o verificador nao compartilham a decisao que auditam;
- datasets e inicializacoes sao carregados em runtime e content-addressed;
- custo ausente e `UNAVAILABLE`, jamais zero;
- tolerancias, protocolo e holdouts sao congelados antes dos resultados.

## Criterio da instancia viva

Uma instancia pode ser chamada `INTERLOCUTION_LIVE_INSTANCE_VALIDATED` somente
quando `A_T=1.00`, as nove mutacoes forem causais, o worker for integral, o juiz
T for consumido, `V_R` aprovar FloodSurrogate e dois holdouts, nao houver falso
PASS e existir reducao liquida observada em pelo menos uma dimensao declarada.
Energia nao e requisito se o estado terminal delimitar explicitamente a ausencia
de instrumento, mas nenhuma alegacao energetica sera autorizada.

## O que permanece generalizacao nao provada

- aplicacao a toda arquitetura neural, dataset ou dominio;
- compressao universal de informacao;
- eliminacao geral de treinamento matricial;
- vantagem em GPU, datacenter ou outro host;
- solidez completa de `V_R` para propriedades nao codificadas.

