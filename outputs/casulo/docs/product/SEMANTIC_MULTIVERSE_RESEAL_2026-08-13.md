# Relatorio do reseal Semantic Multiverse - 2026-08-13

Estado: `READY_FOR_GUILHERME_SEMANTIC_MULTIVERSE_REINSPECTION`

## Preservacao

O archive da terceira inspecao permanece imutavel com SHA-256
`93650a516d1340c84c15efe9aba5b18064b6f4d7115256f1b6f8bace31c7d9d1`.
O evidence, pacote e manifesto recebidos tambem conservaram seus hashes. O selo
anterior foi marcado superseded sem alteracao. Duas tentativas de reseal que
nao satisfizeram o gate foram preservadas separadamente.

## Tres correcoes auditadas

1. `rg` e uma otimizacao opcional. A ausencia, executavel invalido ou falha de
   execucao seleciona um scanner Python literal limitado por extensao, tamanho,
   encoding e exclusoes. Nenhuma rota usa `shell=True`.
2. Restore consulta o catalogo antes de chamar `qemu-img -a`. Zero snapshots,
   nome invalido ou `qemu-img` ausente produzem falha recuperavel e preservam
   base, overlay, catalogo, memoria e criacao. Snapshot baseline, live e nomeado
   sao distintos; repeticao e idempotente.
3. `identity.name` continua opcional e `creation_id` e a identidade canonica.
   O renderer recebe uma projecao tipada. Ausencia valida gera diagnostico e
   fallback; tipo errado, parcial ou schema futuro incompatível falha antes de
   criar output. Falha visual nao invalida materializacao e nao bloqueia
   `:export`, `:nota`, `:universos` ou `:sair`.

## Componente Einstein, alegacao delimitada

A implementacao validada e um avaliador tensorial local 4D parametrizavel. Ela
aceita metrica 4x4 simetrica, quatro coordenadas, ponto, G, c, Lambda,
`T_mu_nu`, condicoes declaradas, passo e tolerancias. Com assinatura `-+++`,
convencao de Riemann `wald` e unidades SI, calcula explicitamente:

```text
g^-1
Gamma^rho_mu_nu
R_mu_nu
R
G_mu_nu = R_mu_nu - 1/2 g_mu_nu R
E_mu_nu = G_mu_nu + Lambda g_mu_nu - (8 pi G / c^4) T_mu_nu
```

Minkowski no vacuo com Lambda zero produziu residuo maximo `0.0`. Para
Minkowski com Lambda `2.5`, o residuo foi
`diag(-2.5, 2.5, 2.5, 2.5)`, como esperado para a assinatura declarada.
Metrica nao simetrica ou singular, dimensoes erradas, coordenadas insuficientes,
passo nao positivo, NaN/Infinity, tolerancia invalida e `T_mu_nu` incompativel
foram recusados.

As condicoes iniciais e de contorno sao registradas para proveniencia; este
avaliador nao as evolui. Nao e solver geral das PDEs de Einstein, nao fornece
solucao global, estabilidade numerica geral, validacao cientifica completa ou
superioridade sobre ferramentas existentes.

TCAP atual:
`8236cdb64fdcc56a0b1627e52abe716474852c92ee653a207a0c3789dbf3095e`.
Pacote delimitado:
`9ceefac252271d66f305e34d0c595606104237cfe534004e935b652660abe37f`.

## Gate integrado

- regressao: `410 passed, 2 skipped, 42 subtests passed`;
- Native/Cargo: PASS;
- SM0-SM7: PASS;
- rota owner: seis universos, 28 lifecycle receipts e cinco transition
  receipts;
- somente `materializacao` HOT ao termino normal; HOT vazio apos reboot;
- memoria confirmada, constraints e proveniencia retomadas;
- cancelamento nao publicou resultado tardio;
- corrupcao em quarentena e prompt injection negado;
- G10: 24/24 checks e quatro hashes congelados;
- owner: allowlist exata e auditoria apos extracao;
- public: 12 arquivos na fonte e wheel sem privados;
- Cloud `RELEASE_LOCKED`; USB/block device proibidos; QPU indisponivel/negada;
- nenhum benchmark cientifico iniciado.

## Selo

- manifesto: `31764546c2dff61f68d2b00bbe4f78060cef4d1523234e7ad59ab1c24d9ad724`;
- SBOM: `69bd1b752fc1476808cc219135a26186b79dc67ecc179ba8027228bd808ed09e`;
- `SHA256SUMS`: `3b9e4e248701baddba49016b5914dc5c10db57f212b0f580ec5f4c677ac99844`;
- assinatura: Ed25519, verificada, rotulada
  `DEVELOPMENT_SIGNATURE_NOT_COMMERCIAL_RELEASE`;
- pacote owner: `b6c65a5b3af0ffb032e7a3b5b62cd013c59aa198d2dfecc4fce59772063f6841`;
- launcher: `d8d64e44255b4fe8a4627ba2d849fc3456ec1c8d2bd6ab853eb733c5ef129a7a`.

O proximo ato e exclusivamente humano: iniciar o launcher, executar o roteiro
do handoff e informar se algum fluxo essencial produz falha P0.
