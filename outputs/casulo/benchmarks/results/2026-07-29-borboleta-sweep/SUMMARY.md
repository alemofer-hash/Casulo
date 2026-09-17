# Borboleta — sensibilidade à repetição

Máquina: Intel Core i5-1235U, Windows 11, Python 3.13.2.

Protocolo comum: 2.000 registros, 7 amostras, 3 iterações por amostra,
1 aquecimento, 1.000 reamostragens bootstrap, semente `24052024`. A energia
elétrica não foi medida porque o sistema não expôs um contador cumulativo.

| Repetição | Fator escalar/Casulo | IC 95% | Veredito |
|---:|---:|---:|---|
| 0% | 0,510× | 0,481–0,577 | regressão |
| 25% | 0,580× | 0,568–0,600 | regressão |
| 50% | 0,679× | 0,650–0,697 | regressão |
| 75% | 0,873× | 0,861–0,893 | regressão |
| 90% | 0,991× | 0,947–1,026 | inconclusivo |
| 95% | 1,047× | 1,024–1,069 | melhoria |
| 99% | 1,095× | 1,091–1,194 | melhoria |

## Conclusão

Para este kernel aritmético barato, a implementação Python atual só amortiza o
custo de serialização, hash e cache quando aproximadamente 95% ou mais das
entradas se repetem. Isso não é uma propriedade universal do Casulo: é a
fronteira observada para este artefato, dataset, runtime e máquina.

O próximo objetivo técnico é deslocar a fronteira para a esquerda:

1. chave estrutural especializada em vez de serialização JSON genérica;
2. hash incremental por campos efetivamente usados;
3. cache local do lote sem envelopes intermediários;
4. geração de kernel nativo e vetorizado;
5. política de custo que só habilita deduplicação quando a economia prevista
   supera o overhead.

Cada subdiretório contém dataset, manifesto, amostras brutas e relatório HTML;
portanto, a tabela pode ser auditada sem confiar neste resumo.
