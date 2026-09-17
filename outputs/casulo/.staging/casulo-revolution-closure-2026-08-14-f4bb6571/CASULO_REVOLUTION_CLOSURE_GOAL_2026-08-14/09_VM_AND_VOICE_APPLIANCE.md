# VM E VOZ — O CASULO COMO APPLIANCE

## 1. Jornada normal

```text
duplo clique
-> preflight read-only
-> doctor silencioso
-> tela Casulo com estimativa humana
-> consentimento de áudio quando necessário
-> boot
-> Campo da Criação
-> conversa por voz
-> shutdown/snapshot automático
```

O caminho normal não mostra PowerShell, QEMU, Python, JSON, paths ou stack trace.
Modo técnico opt-in pode mostrar detalhes.

## 2. Launcher

Entregas equivalentes, preferencialmente executáveis nativos:

```text
START_CASULO_OWNER
VERIFY_CASULO_OWNER
RESTORE_CLEAN_STATE
COLLECT_OWNER_FEEDBACK
```

O launcher:

- localiza dependências pinadas sem depender do `PATH` global;
- valida hashes e espaço;
- nunca resolve target com glob destrutivo;
- verifica que imagens são arquivos regulares;
- inicializa base read-only + overlay esparso;
- registra apenas logs sanitizados;
- traduz falhas em `RecoveryProposal`;
- abre o display e devolve foco ao usuário;
- suporta shutdown gracioso, timeout e força limitada.

## 3. Layout de estado

```text
release/human-proof/
  system/base.qcow2             # imutável
  owner/overlay.qcow2           # descartável/snapshot
  owner/data/                   # memória e criações cifradas
  exchange/inbox/               # import quarantined
  exchange/outbox/              # export atômico
  logs/                         # sanitizados/quota
  snapshots/                    # metadata/ref, sem cópia cega
```

O guest não recebe disco interno, clipboard, shared root ou rede por default.
Exchange é confinado e arquivos importados são não confiáveis.

## 4. Ponte host/guest robusta

Se a inferência ainda estiver no host, `HostAcceleratorService` substitui script
ad hoc:

```text
Handshake:
  protocol_version
  session_nonce
  guest_build_hash
  service_build_hash
  model/adapter hashes
  limits

Frame:
  type, request_id, generation, payload_length,
  deadline, payload_hash, payload
```

Requisitos:

- transporte exclusivamente local;
- auth por sessão e replay protection;
- limite de frame/linha/fila/contexto;
- schemas e enums allowlisted;
- sem shell, comando, host path ou arbitrary file access;
- cancellation e stale generation;
- watchdog/backpressure;
- incompatibilidade falha fechada;
- ausência produz modo degradado e diagnóstico, não fake engine.

## 5. Pipeline de voz

```text
microfone PCM16
-> device calibration
-> high-pass / NS / AGC
-> AEC com render reference
-> VAD + double-talk
-> whisper.cpp partial/final
-> semantic endpointing
-> TurnCoordinator
-> Guide
-> incremental text segmenter
-> local streaming TTS
-> playback/jitter buffer
```

Entrada/saída seguem contrato de tempo monotônico. O caminho acústico tem
prioridade sobre inferência e renderer.

## 6. Barge-in

Barge-in não depende de “Pare, Casulo”. Qualquer fala humana acima de critérios
locais:

1. interrompe playback imediatamente;
2. cancela a sessão TTS;
3. abre captura/ASR;
4. decide depois se a fala também cancela/modifica o job;
5. rejeita resultado tardio pela geração da sessão.

```text
T_barge = t_playback_stopped - t_local_speech_decision
```

O sentido transcrito pode falhar sem impedir a interrupção acústica. Registrar
separadamente qualidade ASR e latência do stop.

## 7. ASR pt-BR

Reutilizar `whisper.cpp`/modelos já adotados se hashes/licenças passarem.
Implementar:

- perfil por dispositivo;
- VAD adaptativo;
- endpointing por silêncio e semântica;
- glossário dinâmico para Casulo/T sem manipular transcript como sucesso;
- partial/final/reset;
- troca/perda de dispositivo;
- locale explícito;
- fallback textual honesto.

Métricas diagnósticas:

```text
WER = (S + D + I) / N
RTF = processing_time / audio_duration
```

O gate principal é sucesso de intenção falada no dispositivo, não uma única
frase-sentinela.

## 8. AEC/NS/AGC

Auditar primeiro WebRTC AEC3 ou SpeexDSP atrás de ABI estreita. AEC recebe a
referência exata do áudio enviado ao playback e estima/recebe delay do device.

```text
ERLE = 10 log10(sum d(n)^2 / sum e(n)^2)
```

Testar far-end-only, near-end-only, double-talk, mudança de volume e dispositivo.
Licença/NOTICE/PATENTS integram SBOM. Não adotar fork obscuro quando upstream
auditável estiver disponível.

## 9. TTS redistribuível

O Goal precisa selecionar pelo menos um backend local com cadeia completa de:

```text
runtime license
model/weights license
voice/data license
G2P/phonemizer license
redistribution obligations
hashes and notices
```

Candidatos não são autorização automática:

- Kokoro-82M possui pesos Apache-2.0 e opções pt-BR, mas caminhos comuns usam
  eSpeak NG GPL-3.0-or-later; exigir SBOM e decisão jurídica/arquitetural;
- Piper atual é GPL-3.0; pode ser componente separado se obrigações forem
  aceitas, nunca ingressar silenciosamente no public;
- System.Speech/Maria serve ao owner Windows, mas não é apresentado como backend
  redistribuível/cross-platform;
- caminho first-party G2P pt-BR em T + modelo permissivo é desejável, mas requer
  testes linguísticos e não deve ser improvisado.

Gate:

- implementar backend owner utilizável;
- implementar ou selar backend redistribuível com auditoria completa;
- se nenhuma cadeia passar, estado final não pode afirmar RC-D7 integral;
- manter adapter substituível e perfil de voz externo aos pesos do Guide.

## 10. Perfil de voz

```text
VoiceProfile = (
  backend, voice_id, locale, speed, pitch?, energy,
  pause_policy, sentence_chunking, expressiveness,
  technical_pronunciations, fallback
)
```

A tela permite escolher/ajustar; a voz dos sonhos de Guilherme permanece decisão
da fase de capricho. Clonagem de terceiros exige consentimento e direitos.

## 11. Turn-taking e silêncio

- primeiro acknowledgment curto quando útil;
- TTS incremental não lê markdown/código bruto;
- segmentos respeitam frase e prosódia;
- usuário pode dizer “fica quieto e trabalha”;
- durante wait, falar apenas com informação nova, decisão ou conversa iniciada;
- estimativa muda com eventos reais;
- nenhum percentual inventado.

## 12. Gates automatizados e físicos

Automatizados:

- PCM sintético e loopback;
- ASR protocol/limits/reset;
- TTS cancellation;
- AEC impulse/delay fixtures;
- device disappearance;
- fallback;
- thread starvation sob inferência;
- zero PCM persistido.

Físicos, somente com consentimento contemporâneo:

- enumeração/calibração do dispositivo;
- sessão pt-BR de pelo menos 30 minutos/50 utterances;
- ruído moderado, distância e volume;
- double-talk e interrupções naturais;
- playback contínuo sem underrun;
- sessão com jobs concorrentes;
- avaliação subjetiva de voz.

Thresholds de performance são pré-registrados por Machine Profile. Alvos
iniciais para calibração, não claims universais:

```text
quiet_intent_success >= 95%
moderate_noise_intent_success >= 85%
barge_in_p95 <= 150 ms após decisão local
false_barge_in <= 2/h
ASR_RTF_p95 < 1
TTS_first_audio_p95 <= 1 s
```

Se o hardware real não for usado, marcar `PHYSICAL_VOICE_VALIDATION=PENDING` e
não declarar prova física. O handoff final pode ficar pronto para Guilherme
executá-la, mas nenhum P1 conhecido do caminho suportado pode permanecer.

## 13. Referências primárias

- whisper.cpp: https://github.com/ggml-org/whisper.cpp
- WebRTC AEC3: https://webrtc.googlesource.com/src/+/main/modules/audio_processing/aec3/
- SpeexDSP: https://github.com/xiph/speexdsp
- ONNX Runtime/Windows: https://onnxruntime.ai/docs/get-started/with-windows.html
- Kokoro: https://huggingface.co/hexgrad/Kokoro-82M

