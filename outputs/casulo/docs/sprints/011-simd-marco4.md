# Sprint 011 — SIMD e abertura do Marco 4

## Hipótese

O laço do Sprint 010 misturava guardas, retorno antecipado e cálculo. O
processador oferecia AVX2, mas o GCC confirmava `0` laços vetorizados.

## Entrega

- Casulo `0.11.0a1` e T `0.11.0-alpha.1`;
- `casulo-artifact/0.8`;
- backend `c99-simd/0.3`;
- protocolo `casulo-simd/0.1`;
- perfil escalar estrito de controle;
- perfil SIMD endereçado pelo alvo da CPU;
- separação de guardas e cálculo sem mudar o primeiro erro observável;
- relatório do compilador anexado à proveniência;
- benchmark pareado com bootstrap;
- curva de 1, 8, 32, 256 e 2.000 registros.

## Resultado oficial

Ambiente:

- Intel Core i5-1235U;
- Windows 11;
- CPython 3.13.2;
- GCC MinGW-W64 16.1.0;
- AVX2, vetor principal de 256 bits;
- 2.000 registros únicos;
- 21 amostras pareadas;
- 2.000 iterações por amostra.

| Perfil | ns/registro mediano |
|---|---:|
| C99 escalar estrito | 3,0884 |
| C99 SIMD estrito | 2,7946 |

- mediana dos ganhos pareados: `1,117×`;
- IC95% pareado: `1,084×–1,135×`;
- equivalência semântica: preservada;
- laço vetorizado reportado pelo GCC: sim;
- gate do Sprint 011: aprovado.

## Curva por lote

| Registros | Ganho pareado | IC95% | Conclusão |
|---:|---:|---:|---|
| 1 | 0,989× | 0,954×–1,031× | inconclusivo |
| 8 | 1,007× | 0,915×–1,047× | inconclusivo |
| 32 | 0,999× | 0,848×–1,085× | inconclusivo |
| 256 | 1,028× | 0,962×–1,046× | inconclusivo |
| 2.000 | 1,117× | 1,084×–1,135× | ganho comprovado |

O perfil SIMD existe para todos os tamanhos, mas só pode ser descrito como
vantajoso, neste corpus, em 2.000 registros.

## Ponta a ponta

Na medição completa, Python escalar levou `12.329,27 ns/registro` e o backend
nativo `2.017,69 ns/registro`: razão das medianas `6,111×`, mediana pareada
`6,096×` e IC95% `5,994×–6,231×`.

O kernel SIMD representa apenas `0,15%` da soma independente dos estágios.
Logo, o ganho vetorial é real no cálculo, mas fica praticamente oculto pelo
marshal e pela manifestação. Essa é a entrada objetiva do Sprint 012.

## Próximo gate

O Sprint 012 deve introduzir scheduler determinístico de 1, 2 e 4 workers,
partições limitadas e medição de eficiência paralela. Ele também deverá atacar
a fronteira sem retirar entrada, resultado ou evidência do envelope.

## Validação

- Python 3.13: 90 testes e 42 subtestes;
- Python 3.11 e 3.12: 89 testes, um skip esperado e 42 subtestes;
- cobertura total: 86%;
- duas compilações SIMD forçadas: SHA-256 idêntico;
- perfis escalar e SIMD: binários e alvos distintos;
- duas wheels limpas:
  `0e59a7d271a492903b332f4dfe1d1b572348eefb09d89e2784f39864dcad4c76`;
- dois sdists normalizados com SHA-256 idêntico;
- `twine check`, instalação limpa e `t simd-benchmark`: aprovados;
- fallback e `--native-required`: preservados.

O Marco 4 está em andamento; ainda não foi demonstrado ganho combinado de
`15×–50×`, eficiência de quatro núcleos ou redução de joules.
