# Sprint 008 — matriz do buffer tipado

## Protocolo

- artefato: `sha256:e47e11c2343a8fb2903f74bbe29b250b7396c3f03147d4b62cf16fe972d67e44`;
- buffer: `casulo-typed-buffer/0.1`;
- chave: `casulo-structural-key/0.1`;
- modelo: `casulo-cost-model/0.3`;
- Borboleta: `casulo-borboleta/0.4`;
- 2.000 registros por lote;
- semente: `8020`;
- ensaios gerais: 9 amostras × 5 iterações, 2 aquecimentos;
- fronteira de 50%: 21 amostras × 10 iterações, 3 aquecimentos;
- bootstrap: 2.000; fronteira: 5.000;
- ambiente: Intel Core i5-1235U, 16 GB RAM, Windows 11, Python 3.13.2.

O fator é `tempo_escalar / tempo_casulo`. Perfil, decisão e execução estão
incluídos no fator adaptativo.

| Repetição | Estimada | Estratégia | Kernel | IC95% | Adaptativo | IC95% |
|---:|---:|---|---:|---:|---:|---:|
| 0% | 0,00% | `FUSE_TYPED_BATCH` | 3,074× | 2,259–3,589 | 2,652× | 2,197–2,842 |
| 25% | 30,00% | `FUSE_TYPED_BATCH` | 3,546× | 3,327–3,895 | 3,033× | 2,776–3,487 |
| 50% | 52,45% | `DEDUPLICATE_BATCH` | 3,790× | 3,446–4,250 | 3,557× | 3,388–3,752 |
| 75% | 73,40% | `DEDUPLICATE_BATCH` | 3,739× | 3,565–4,245 | 3,872× | 2,616–4,161 |
| 99% | 99,00% | `DEDUPLICATE_BATCH` | 4,989× | 4,160–6,150 | 4,528× | 3,931–5,233 |

Todas as comparações foram semanticamente equivalentes e estatisticamente
favoráveis ao Casulo.

## Representação em 50%

Uma chamada fria comparou o lote de objetos do próprio artefato com o caminho
tipado usando `tracemalloc`:

- pico do caminho de objetos: 5.127.552 bytes;
- pico do caminho tipado: 3.538.171 bytes;
- redução do pico rastreado: 31,00%;
- redução de blocos retidos: 0,55%;
- mapas intermediários evitados: 6.000;
- listas intermediárias evitadas: 5.000;
- escritas de campos evitadas: 8.000.
- referências intermediárias não escritas: no mínimo 64.000 bytes no ambiente
  de 64 bits, sem contar tabelas hash e cabeçalhos.

## Conclusão limitada

O critério de `2×` em tráfego intermediário foi superado tanto no kernel quanto
na execução adaptativa. O ganho em 0% mostra que a retirada de objetos produz
benefício mesmo sem reutilização.

Os números pertencem ao kernel, dataset e computador declarados. O ensaio não
mede contadores físicos de tráfego de memória nem joules, não contém SIMD e não
equivale a multiplicação universal de processadores.
