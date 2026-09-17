# Preflight de voz hosted

Observado em 2026-08-11 no host Windows físico, sem capturar áudio e sem tocar
voz durante o diagnóstico.

| Componente | Estado observado | Decisão |
|---|---|---|
| dispositivo | Realtek High Definition Audio(SST), `OK` | apto para probe futuro consentido |
| permissão microfone | `Allow` | apta; não prova qualidade |
| `sounddevice` | 0.5.5, MIT | adapter opcional já disponível; não pinado para release |
| `numpy` | 2.3.5 | instalado no host; duplex novo não depende dele |
| TTS pt-BR | Microsoft Maria Desktop | fallback hosted opcional, não redistribuído |
| ASR Windows | somente en-US | não elegível para vertical pt-BR |
| Whisper | v1.9.2 + small-q5_1 verificados | ASR local READY; modelo por SHA-256 |
| ffmpeg/sox | ausentes | não necessários ao slice de contratos |

## Estado

```text
CAPTURE_ADAPTER=READY_UNCALIBRATED
VAD_ENDPOINTING=PASS_SYNTHETIC
PARTIAL_FINAL_CONTRACT=PASS_SYNTHETIC
BARGE_IN_CONTRACT=PASS_SYNTHETIC
TTS_SYSTEM_FALLBACK=PASS_BUFFERED_PCM_REAL_NO_PLAYBACK
TTS_DIRECT_STREAMING_PLAYBACK=PASS_IMPLEMENTATION_AWAITING_PHYSICAL_SMOKE
TTS_STREAMING_REDISTRIBUTABLE=ROADMAP_NOT_ADOPTED
ASR_PROCESS_BOUNDARY=PASS_SYNTHETIC
ASR_NATIVE_ABI=PASS_REAL_LOAD
ASR_ADOPTION_FLOW=PASS_EXECUTED_WITH_RECEIPTS
ASR_PT_BR=PASS_SYNTHETIC_LOOPBACK_NO_DEVICE
ASR_FAST_PROFILE=PASS_BASE_Q5_1_4_THREADS_LOCAL_UX
SPRINT_5_GATE=NOT_PASSED
```

O produto não pode alegar conversa local pt-BR contínua ainda. O ASR pinado já
foi adotado e o loopback sem dispositivo passou; a próxima ação externa é o
consentimento explícito para capturar microfone e validar acústica/barge-in. A
mesma autorização deve cobrir um playback curto da rota SAPI progressiva. TTS
distribuível permanece separado; Maria depende do Windows e não satisfaz
streaming PCM cross-platform.
