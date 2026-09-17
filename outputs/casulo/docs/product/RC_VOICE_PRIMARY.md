# RC8 — Voz primária, implementação automatizada

O caminho de entrada usa whisper.cpp v1.9.2 e `ggml-base-q5_1` já adotados e
verificados em cache local. O pipeline preserva PCM16, VAD, partial/final,
endpointing, duplex, barge-in e cancelamento geracional; nenhum áudio bruto é
persistido por padrão.

Foi adicionada uma referência first-party de high-pass, supressão por noise
gate, cancelamento de eco por referência e AGC limitado. Ela existe para fechar
contratos e fixtures; não substitui a futura adoção auditada de AEC3/SpeexDSP
sem comparação física.

Saída owner preferencial neste host: Microsoft Maria/System.Speech, componente
do Windows e não redistribuído. O fallback redistribuível é
`casulo-first-party-formant`: código/G2P MIT, sem pesos ou áudio gravado. Ele é
robótico e provisório, mas é síntese real, streaming e cancelável — não replay.
Piper/sherpa continua `LICENSE_REVIEW_REQUIRED_NOT_ADOPTED`.

O gate automatizado não abre microfone nem toca som. Permanecem:

```text
PHYSICAL_VOICE_HUMAN_VALIDATION=PENDING
VOICE_CHEMISTRY=PENDING_GUILHERME
DESIGN_STATUS=PROVISIONAL_OWNER_REVIEW_REQUIRED
```

