# Resultado final da campanha energética do worker completo

**Estado científico:** `BLOCKED_PHYSICAL_COOLING_REQUIRED`

## Resultado

Não há uma comparação energética TCAP × PyTorch Eager válida nesta campanha.
O sistema parou antes de controles, probes, calibração de `K`, warm-ups e pares.
Portanto, joules por treinamento, razão, intervalo de confiança e teste de
sinais são indisponíveis — não zero.

## Causa física comprovada

O evento anterior a 68 °C foi classificado como
`GENUINE_INSTANTANEOUS_THERMAL_THROTTLE` por três indicadores HWiNFO
instantâneos. Em seguida, um novo segmento de 20 minutos com nenhum workload
registrou 4.790 amostras, 46–77 °C (mediana 54 °C) e quatro amostras de
throttling instantâneo do núcleo/P-core 1:

- 16:10:34.111 UTC, 70 °C;
- 16:10:34.360 UTC, 60 °C;
- 16:10:34.612 UTC, 73 °C;
- 16:14:36.577 UTC, 57 °C.

O maior trecho dentro da banda térmica simétrica pré-registrada de ±1 °C foi
7,293 s, contra 30 s exigidos. O guard expirou sem iniciar o Controle A.

## Trabalho preservado

O gate anterior continua válido para a unidade completa: 1.024 registros por
época, 400 épocas, 409.600 visitas, 400 forwards, 400 backwards, 400 updates e
32.400 escritas de parâmetros. A equivalência TCAP/Eager anterior permanece
em `4,44e-16` para parâmetros e `1,78e-15` para predições. Ela não substitui
a equivalência por par que seria obrigatória na campanha energética.

## Próxima ação física única

Fornecer resfriamento ativo e um host quiescente que sustente 30 segundos de
idle estável sem qualquer throttling; depois executar o protocolo sob uma nova
identidade. Não é permitido reaproveitar controles ou pares desta tentativa.

## Limites

- `TOTAL_SYSTEM_WALL=BLOCKED_PHYSICAL_INSTRUMENT`
- `CASULO_NATIVE_ENERGY=BLOCKED_PHYSICAL_INSTRUMENT`
- Sem alegação de vantagem energética, contra Inductor, GPU/TPU, datacenter,
  outros hosts ou energia total.
