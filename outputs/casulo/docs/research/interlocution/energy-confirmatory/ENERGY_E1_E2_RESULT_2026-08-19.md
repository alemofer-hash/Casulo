# E1/E2 — resultado energético honesto da Interlocução

Data de selagem: `2026-08-20T01:24:48.782135+00:00`  
Commit preservado: `df12e916c90d9bd2b966326275dc191573f38abd`  
Branch: `product/semantic-multiverse`

## Veredito curto

**E1 não foi aprovado:** não existe neste host um wattímetro físico calibrado nem uma fonte RAPL cumulativa válida. O HWiNFO permitiu apenas uma medição exploratória do pacote CPU.

**E2 não foi aprovado:** a topologia confirmatória observada é 0/6 hosts qualificados, 0/3 famílias de CPU, 0/2 laboratórios e 0/5 workloads com energia total válida.

O resultado exploratório local aponta na direção **negativa** para a hipótese de que a governança T, isolada sobre o mesmo kernel, economiza energia: D/E = `1.049367` — D usou aproximadamente `4.94%` mais energia reportada do pacote que E. Isso não é uma derrota do sistema integrado contra PyTorch; é a medição do overhead causal de T contra o mesmo kernel nativo.

O caminho continua **positivo em validade científica**: o kernel foi realmente isolado, os resultados foram bit a bit iguais nos testes feitos, uma tentativa termicamente assimétrica foi rejeitada e nenhum joule inexistente foi fabricado.

## Números centrais

| Medida | Resultado | Leitura permitida |
|---|---:|---|
| K por braço/janela | 480 | 480 treinamentos completos e distintos |
| Tentativas pareadas | 3 | todas preservadas |
| Pares exploratórios válidos | 2 | 1 rejeitado por assimetria térmica de 5 °C |
| D — mediana J/treino | 0.350100739 | HWiNFO package, exploratório |
| E — mediana J/treino | 0.334061825 | HWiNFO package, exploratório |
| Razão D/E | 1.049366993 | acima de 1 favorece E |
| Variação D vs E | +4.937% | sinal negativo para economia causal de T |
| Máxima térmica em janelas válidas | 65.0 °C | 0 throttling |
| Diferença máxima de resultado D/E | 0 | perdas, parâmetros e predições |
| Treinamentos medidos válidos | 1.920 | 960 por braço |
| Treinamentos executados totais | 2.880 | inclui o par térmico rejeitado |
| Receipts de trabalho preservados | 2.880 | supervisor-derived; não chamados de assinatura interna do kernel |

### Pares válidos

| Par | D J/treino | E J/treino | D/E | D W médio | E W médio | ΔT inicial |
|---|---:|---:|---:|---:|---:|---:|
| pair-02 | 0.354385522 | 0.323926079 | 1.094032082 | 9.791 | 8.984 | 0.0 °C |
| pair-03 | 0.345815955 | 0.344197571 | 1.004701905 | 9.418 | 9.657 | 1.0 °C |

Com apenas dois pares válidos não foi calculado um IC confirmatório. Produzir um IC aqui daria aparência de precisão sem desenho amostral suficiente.

## Identificação causal D × E

- D e E chamaram o mesmo `tcap_full_worker.exe`, SHA-256 `687d61ce424b84c066211f41b45bd8ea5d64270654a8eb1ad564245962a0777b`.
- Dataset e bundle de inicialização foram iguais e content-addressed.
- Piloto K=2: D end-to-end `0.855144 s`; E `0.106738 s`; razão `8.012`.
- Tempo interno do filho no piloto: D `0.072995 s`; E `0.066968 s`.
- O binário de resultado foi idêntico; diferenças máximas de loss, parâmetros e predições foram zero.
- A diferença D/E mede a governança T e sua verificação/publicação; não mede T contra PyTorch nem a escolha de um kernel melhor.

## Metrologia e recomposição

- Sensor literal selecionado: `Potência total da CPU [W]`; unidade `w`.
- Intervalo mediano `0.252 s`; p95 `0.271 s`.
- Energia integrada por timestamps reais, regra trapezoidal e interpolação nos limites exatos.
- Segmentos brutos recompostos: `6/6`; diferença máxima `0 J` dentro de 1e-9.
- O HWiNFO não tem certificado de calibração/uncertainty suficiente para elevar esses números a E1.
- A bateria estava carregando; portanto a energia na tomada, mesmo se estivesse disponível, não poderia ser atribuída integralmente ao workload sem controle adicional.

## Runtime energético V2

Validação focal: **54 passed, 0 failed** em `7.00 s`.

Foram corrigidos/testados: normalização exclusiva por `K_completed`, cinco contadores K, potência por amostra, potência amostrada e energia cumulativa, interpolação de borda, gaps, reset/wrap desconhecido, mudança de range, mock, calibração, firmware, clock, desktop sem bateria, laptop instável, bootstrap hierárquico e braço E de kernel idêntico.

## Estados terminais

- `E1 = E1_BLOCKED_PHYSICAL_INSTRUMENT`
- `E2 = E2_BLOCKED_INSUFFICIENT_EXTERNAL_SCALE_AND_INSTRUMENTATION`
- `TOTAL_SYSTEM_ENERGY_CLAIM = NOT_AUTHORIZED`
- `CPU_PACKAGE_ENERGY_CLAIM = NOT_AUTHORIZED`
- `EXPLORATORY_HWINFO_DIRECTION = D_CONSUMED_MORE_THAN_E_IN_VALID_LOCAL_PAIRS`

## O que falta fisicamente — não é uma pendência de software

E1 exige um analisador físico de tomada com serial, firmware, range congelado, incerteza <1%, calibração rastreável recente e export por timestamps; no notebook, a bateria precisa estar estável. E2 exige 6 hosts em 3 famílias de CPU, 2 laboratórios independentes, 5 famílias de workload e 24 pares por host/workload em pelo menos 3 sessões. Nenhuma manipulação local transforma 1 laptop e HWiNFO nessa topologia.

## Síntese de direção

**Negativo quanto à hipótese específica testada:** a governança T adicionou energia ao mesmo kernel nos dois pares válidos. O efeito exploratório mediano foi +4,94%, abaixo do limiar material de 10%, mas na direção desfavorável.

**Positivo quanto à arquitetura experimental:** o contraste anteriormente confuso foi decomposto; sabemos agora que a grande vantagem D/A não pode ser atribuída somente à governança T. Ela vem principalmente da escolha do executor/kernel, enquanto T cobra um overhead mensurável para arquitetar, auditar e julgar.

**Conclusão científica atual:** não existe evidência válida de compressão energética confirmatória. Existe evidência exploratória de equivalência perfeita, isolamento causal e pequeno overhead energético de T no host local. O próximo resultado legítimo depende de instrumento físico e replicação externa, não de ajustar o software até aparecer uma vitória.
