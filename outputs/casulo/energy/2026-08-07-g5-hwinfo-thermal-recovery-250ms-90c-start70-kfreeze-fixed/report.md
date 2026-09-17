# Campanha energética HWiNFO: TCAP × PyTorch Eager

**Estado científico:** `INCONCLUSIVE_CPU_PACKAGE_ENERGY_HWINFO_WINDOWS`

Escopo: HWiNFO-reported CPU package energy on bare-metal Windows.

- Sensor: `Potência total da CPU [W]` (w)
- Intervalo mediano: 0.255 s
- Pares válidos: 21/21
- TCAP: 0.0038897192190195237 J/treinamento
- PyTorch Eager: 2.5318306505471764 J/treinamento
- Razão TCAP/Eager: 0.0015239981590574325
- IC bootstrap pareado 95%: [0.0014016660419851176, 0.0016165606798826668]
- Equivalência: PASS_PER_PAIR_PRE_AND_POST
- Assimetria térmica mediana: 7.0 °C
- Outliers removidos: não

`TOTAL_SYSTEM_WALL=BLOCKED_PHYSICAL_INSTRUMENT`

`CASULO_NATIVE_ENERGY=BLOCKED_PHYSICAL_INSTRUMENT`

Nenhuma extrapolação para Inductor, GPU/TPU, datacenter, outros hosts ou energia total.
