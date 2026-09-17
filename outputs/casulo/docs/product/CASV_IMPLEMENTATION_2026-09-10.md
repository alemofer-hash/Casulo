# CASV/0.1 — primeiro arquivo visual causal executado

Data: 2026-09-10  
Estado: `CV0_CASV_NATIVE_FORMAT_BOUNDED_PROBE_PASS`

## Resultado

Foi implementado um formato binário próprio `.casv`. Ele não é ZIP, MP4 ou
HEVC reempacotado. O primeiro probe executou a seguinte rota:

```text
RGB8 canônico sintético
-> detecção de fundo e retângulos
-> base + aparência + dinâmica
-> renderer determinístico
-> residual XOR exato
-> seleção causal T
-> CASV
-> decoder independente
-> SHA-256 RGB8 idêntico
```

## Números observados

Corpus estruturado: `96 x 54`, 24 frames, RGB8, 24 fps.

| Medida | Resultado |
|---|---:|
| fonte canônica RGB | 373.248 bytes |
| payload generativo | 124 bytes |
| base | 100 bytes |
| dinâmica | 24 bytes |
| residual persistido | 0 bytes |
| arquivo CASV completo | 2.591 bytes |
| redução contra RGB cru | 99,305823474% |
| arquivo + artifacts da autoridade por encode | 34.392 bytes |
| redução nesta contabilidade parcial | 90,785751029% |
| tracks inferidos | 2 |
| veredito T | `ACCEPT` |

O SHA-256 canônico reconstruído foi:

```text
88186bc00c409dda8391d0c2b2f3df2db3e588b75029373b1a73949c9e6621dd
```

O `.casv` estruturado possui SHA-256:

```text
521334a68a926e17e2ef6258ea9875b24121891cd9fb32ba575abb321c267443
```

O controle T force-raw mudou o TCAP e produziu `CANONICAL_RAW`, com 375.394
bytes. O conteúdo reconstruído permaneceu idêntico. Isso demonstra causalidade
da política T nessa superfície, não autoridade sobre toda a inferência visual.

O controle de ruído determinístico tinha 373.248 bytes. Os candidatos foram:

| Candidato | Payload |
|---|---:|
| generativo + residual | 373.421 bytes |
| zlib direto | 373.369 bytes |
| raw | 373.248 bytes |

T escolheu raw; o envelope completo ficou em 375.393 bytes e o juiz retornou
`REJECT`. A entrada incompressível não foi transformada em um sucesso falso.

## Interpretação obrigatória

A redução de 99,3% é uma validação de engenharia sobre um vídeo sintético que
pertence exatamente à família representável por dois retângulos. Ela não prova:

- ganho em vídeo natural;
- ganho contra HEVC;
- streaming 8K;
- inferência neural;
- compressão próxima de 100% de uma fonte externa;
- custo total do sistema, pois runtime e decoder compartilhados não foram
  integralmente alocados nessa conta.

O próprio zlib reduziu o payload estruturado para 829 bytes. Portanto, esse
probe valida o formato e a causalidade, não superioridade comercial.

## Evidência

```text
C:\CasuloLab\campaigns\2026-09-10-casv-native-format-probe-attempt1
```

Hashes:

```text
PROBE_MANIFEST.json
7222426398c76120dbfd350098175bee64a286aec2ee72e564299b75dfac8b9d

report.json
5c848c203b2482ff4acae9ad42237bd86377b33c5e9d2e00cc122ba2da289bc6
```

Validação executada:

```text
ruff: PASS
tests/product/test_casv_format.py: 7 passed
casv-probe: 6/6 gates PASS
casv-verify structured: PASS
casv-verify noise: PASS
```

## Próximo gate

`CV1_STREAMING_IMPORT_AND_PLAYER`:

1. importer MP4 -> frames canônicos sem armazenar o MP4 no CASV;
2. pipeline streaming com working set congelado;
3. index/checkpoints para seek;
4. player que renderiza `.casv` diretamente;
5. áudio canônico com contrato separado;
6. antialiasing, alpha, gradientes, texturas e luz espacial determinísticos;
7. probes naturais curtos antes de qualquer execução 8K integral.

