# Semântica dos sensores HWiNFO usados na campanha

## Energia

O campo energético permitido é literalmente:

`Potência total da CPU [W]`

Ele é tratado como potência reportada do pacote CPU no Windows bare-metal. A
energia é calculada por integração trapezoidal com os timestamps reais e
interpolação nos limites da janela. Não é energia da tomada e não autoriza
inferência sobre a energia total do notebook.

## Térmica

O guard considera apenas colunas instantâneas de thermal throttling. Colunas
com `Maximum`/`Máximo`, latches históricos, limites PL1/PL2, temperatura,
frequência e utilização não são convertidos em throttling.

O evento decisivo foi sustentado pelos campos instantâneos:

- `Estrangulamento térmico do núcleo (avg) [Yes/No]`;
- `P-core 1 Estrangulamento térmico [Yes/No]`;
- `Regulagem térmica do pacote / anel [Yes/No]`.

Os campos críticos e PROCHOT são preservados separadamente. Um valor `Sim` em
`IA: Max Turbo Limit` não é thermal throttling.

## Limites de alegação

- `TOTAL_SYSTEM_WALL=BLOCKED_PHYSICAL_INSTRUMENT`
- `CASULO_NATIVE_ENERGY=BLOCKED_PHYSICAL_INSTRUMENT`
- Sem extrapolação para Inductor, GPU/TPU, datacenter ou outros hosts.
