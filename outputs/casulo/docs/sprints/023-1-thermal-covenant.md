# Sprint 023.1 — Thermal Covenant

Status: gate físico aprovado no Lenovo 82VY em 31/07/2026.

## Finalidade

Nenhum benchmark de desempenho do Casulo/T pode ser iniciado sem um supervisor
externo capaz de observar temperatura da CPU e throttling. Sensor ausente,
desatualizado, parcial ou não confiável é bloqueio, não evidência de segurança.

O processo supervisor fica fora do processo medido. Ele limita a árvore filha a
dois workers, registra todas as observações e encerra somente essa árvore diante
de perda do sensor, throttling, temperatura ou tempo excessivos.

Cada JSON recebe um sidecar com SHA-256 dos bytes efetivamente gravados, de
modo que `Get-FileHash` e o verificador do Casulo produzam o mesmo valor.

## Política inicial selada

| Evento | Limite | Ação |
|---|---:|---|
| Atenção | 75 °C | sessão inelegível |
| Parada suave | 80 °C | encerra a árvore filha |
| Parada dura | 85 °C | encerra a árvore filha |
| Reinício | abaixo de 55 °C | exige três leituras estáveis |
| Carga contínua | 20 s | encerra a árvore filha |
| Bloco | 60 s | teto estrutural |
| Workers | 2 | sobrescreve variáveis OpenMP/BLAS |
| Carga pesada por hora | 600 s | orçamento inicial |
| Bateria fora da tomada | mínimo 40% | bloqueia início abaixo disso |

Esses números são guardas conservadores do experimento, não especificações de
projeto do fabricante e não autorização para ignorar odor, fumaça ou ruído.

O watchdog pode aguardar até 120 segundos pelo resfriamento, sem iniciar o
processo filho. A contagem reinicia sempre que uma leitura ultrapassa 55 °C.

## Máquina observada em 31/07/2026

- Lenovo 82VY, IdeaPad 1 15IAU7.
- Intel Core i5-1235U, 10 cores e 12 processadores lógicos.
- LibreHardwareMonitor 0.9.6 e PawnIO 2.2.0 instalados.
- HWiNFO 8.50 instalado.
- PawnIO ativo, mas o LibreHardwareMonitor devolveu `null` para temperaturas,
  clocks e potência nesta sessão.
- HWiNFO reconheceu o hardware, mas sua captura JSON ainda não foi habilitada.

O protocolo também aceita o logging CSV nativo do HWiNFO com
`--source hwinfo-csv`. Nomes de sensores em português e inglês são
normalizados; distância para TjMAX nunca é confundida com temperatura da CPU.
Limite de potência é registrado separadamente e não é promovido a throttling
térmico.
- No diagnóstico final, a bateria estava em 15% e fora da tomada; essa condição
  também bloqueia o início de qualquer sessão.

O diagnóstico inicial `doctor.json` permanece corretamente classificado como
`BLOCKED_SENSOR`, preservando a indisponibilidade original. Depois da ativação
do logging contínuo do HWiNFO, três sessões independentes foram aceitas:

| Sessão | Carga | Pico | Throttling | Atestado físico |
|---|---|---:|---|---|
| 01 | processo ocioso, 5 s | 60 °C | não | aceito |
| 02 | um processo CPU, 5 s | 61 °C | não | aceito |
| 03 | dois processos CPU, 5 s | 67 °C | não | aceito |

O juiz produziu `resume-gate.json` com `status=PASSED`, três de três sessões
aceitas e `roadmap_may_resume=true`. Isso aprova a retomada controlada do
roadmap; não constitui evidência de superioridade de desempenho.

## Interface

Diagnóstico sem carga:

```powershell
casulo-thermal doctor --output doctor.json
```

Supervisão de um comando somente depois de o diagnóstico aprovar:

```powershell
casulo-thermal run `
  --source file `
  --telemetry-file thermal-live.json `
  --record session-01.json `
  --session-id session-01 `
  --max-runtime-seconds 20 `
  -- python command.py
```

O produtor de `thermal-live.json` precisa atualizar atomicamente:

```json
{
  "observed_at_utc": "2026-07-31T15:00:00+00:00",
  "temperature_celsius": 48.0,
  "temperature_source": "hardware monitor and sensor name",
  "temperature_trusted": true,
  "thermal_throttling": false,
  "throttling_source": "hardware throttle flag",
  "throttling_trusted": true
}
```

O arquivo expira em dois segundos. Frequência baixa, ausência de evento no log
do Windows e temperatura ambiente não substituem esses dois sinais.

Após cada sessão, o operador registra aquilo que software não consegue sentir:

```powershell
casulo-thermal attest session-01.json `
  --no-odor --no-smoke --no-abnormal-noise
```

O gate exige três sessões independentes, telemetria aprovada e três atestados:

```powershell
casulo-thermal gate `
  session-01.json session-02.json session-03.json `
  --output resume-gate.json
```

## Sequência restante

1. Habilitar uma fonte que exponha temperatura e flag de throttling.
2. Repetir `doctor` até `performance_ready=true`, sem alterar os limites.
3. Executar três sessões curtas e separadas; o operador atesta cada uma.
4. Calibrar janelas de 250 ms e 500 ms usando estabilidade, nunca speedup.
5. Retomar Sprint 025 em blocos térmicos balanceados.
6. Só então reabrir Casulo × PyTorch eager × Inductor.

Qualquer odor, fumaça, ruído anormal, alerta ou throttling coloca a sessão em
quarentena e requer desligamento, desconexão da energia e inspeção física antes
de nova tentativa.
