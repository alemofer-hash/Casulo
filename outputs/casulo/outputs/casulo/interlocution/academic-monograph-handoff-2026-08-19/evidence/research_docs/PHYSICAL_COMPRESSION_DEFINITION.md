# Definicao de compressao fisica e logica

Compressao significa reduzir trabalho ou estado observado preservando `R`. Nao
significa comprimir universalmente informacao abstrata.

## Vetor primario `Phi`

- `executed_operations`;
- `active_state_bytes`;
- `bytes_moved`;
- `peak_working_set`;
- `allocations`;
- `model_calls`;
- `processed_tokens`.

Cada campo registra `observed`, `estimated` ou `unavailable`. Operacoes
estimadas nunca sao apresentadas como contadores de hardware. Bytes logicos nao
sao trafego fisico.

## Vetor secundario `Psi`

- `process_cycles`;
- `peak_rss`;
- `wall_time`;
- `package_joules`;
- `total_system_joules`.

RSS nao e energia; tempo nao e energia; RAPL/HWiNFO package nao e energia total;
e somente instrumento de tomada calibrado autoriza `total_system_joules`.
Metrica indisponivel permanece `null` com motivo.

## Fronteiras temporais

Sao contabilizados separadamente interlocucao, compilacao, warm-up, treinamento,
auditoria, julgamento e publicacao. A metrica primaria end-to-end inclui o custo
de T. Steady-state, amortizacao e ponto de equilibrio sao secundarios e devem
mostrar explicitamente quais custos foram excluidos.

## Materialidade

Reducoes por dimensao nao sao agregadas em score. Para uma metrica ruidosa, uma
reducao material inicial exige ao menos 10% e intervalo de confianca congelado
inteiramente favoravel. Para contadores deterministas, exige reproducao e
recomposicao exata. Resultado negativo e preservado.

## Estado atual

TI0-TI2 nao executaram medicao nova. O full worker r2 e apenas baseline de
integridade de trabalho. Energia permanece bloqueada ate autoridade,
equivalencia, adversariais e verificador independente passarem.

