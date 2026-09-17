# Evidência — Sprint 5 Voice Duplex (fundação)

Data: 2026-08-11

Estado: `PARTIAL_GATE_PASS_PHYSICAL_DUPLEX_SMOKE_PENDING`

## Entrega executável

- frames PCM16 mono e contrato de captura lazy via `sounddevice` já instalado;
- VAD energético determinístico;
- transcrições parciais e finais com endpointing;
- barge-in que cancela a sessão de fala antes de aceitar a nova parcial;
- ponte de transcript final para a fila `PRESENCE` do Hosted Shell;
- falha explícita quando não existe ASR pt-BR adotado;
- TTS Microsoft Maria pt-BR apenas como fallback opcional do sistema;
- dois modelos ASR pinados/adotados no host, ainda desabilitados por padrão;
- boundary ASR JSONL assíncrono, limitado e sem invocação de shell;
- `casulo-voice doctor` somente leitura, com verificação de receipt/hash/binário;
- fallback textual explícito que cancela fala e produz evento final sem fingir ASR.
- worker first-party com PCM16 -> float32, limite de 120 s, partial/final/reset;
- ABI C++ estreita compilada contra stub e contra o source pinado real;
- adoção transacional/idempotente com consentimento literal e rollback;
- build offline guardado, sem rede, com receipt e SHA-256 do bridge.
- fallback Maria buffered PCM com sink cancelável e voice card explícito.

## Gate integrado

```text
209 passed, 42 subtests passed in 6.99s
public files scanned: 12
public forbidden findings: 0
cloud release state: RELEASE_LOCKED
```

Comandos:

```powershell
python -m compileall -q src/casulo/product tests/product
python -m pytest -q --basetemp .tmp-product-sprint5-partial-gate/pytest `
  tests/product tests/test_t_frontend.py tests/test_t_semantics_ir.py `
  tests/test_t_workspace.py tests/test_t_tcap.py tests/test_t_backend.py `
  tests/test_t_metamorphosis.py tests/test_t_native.py `
  tests/test_semantic_scheduler.py
python tools/audit_public_artifact.py editions/casulo-public
```

Doctor executado sem cache:

```powershell
python -m casulo.product.voice_cli doctor `
  --manifest release/voice-candidates/whisper-cpp-v1.9.2.json `
  --cache .tmp-voice-cache-never-created-final
```

Resultado esperado e observado: exit `3`, `asr_pt_br=NOT_INSTALLED`,
`download_performed=false`, `ready=false` e nenhum diretório de cache criado.

O código nativo foi compilado contra o `whisper.cpp` pinado, ligado sem runtimes
MinGW externos não sistêmicos e carregado pelo doctor. Os modelos small e base
passaram tamanho/SHA-256 e possuem receipts por modelo.

Após consentimento, os comandos preparados são:

```powershell
python -m casulo.product.voice_cli adopt-asr `
  --manifest release/voice-candidates/whisper-cpp-v1.9.2.json `
  --cache "$env:LOCALAPPDATA\Casulo\cache\voice" `
  --consent DOWNLOAD_WHISPER_CPP_190085487_BYTES

python -m casulo.product.voice_cli build-asr `
  --manifest release/voice-candidates/whisper-cpp-v1.9.2.json `
  --cache "$env:LOCALAPPDATA\Casulo\cache\voice" `
  --repository .
```

Esses comandos foram executados após autorização. O doctor retorna
`bridge_loadable=true` e `ready=true`.

## Perfil rápido e boundary real

`casulo-voice smoke-asr` percorreu o processo isolado/JSONL com silêncio
sintético, sem microfone ou alto-falante. Em uma micro-medição de UX neste
i5-1235U, 1 s de áudio/4 threads fechou em aproximadamente 4,13 s no
`small-q5_1` e 1,29 s no `base-q5_1`. O segundo preservou a frase sintética:

```text
Olá, eu sou o casulo. Todo dado tem uma finalidade.
```

Isso seleciona o perfil rápido local; não é benchmark científico nem claim para
outros hosts.

## TTS hosted progressivo

Além da rota PCM buffered, `WindowsDirectStreamingTts` usa playback SAPI direto
que começa antes do fim da síntese e é cancelável encerrando o processo
isolado. Texto viaja por variável de ambiente, não pelo comando. O teste de
contrato passou, mas nenhum som foi reproduzido automaticamente; o smoke físico
aguarda consentimento de dispositivo.

## TTS — resultado real e claim corrigida

`System.Speech.SetOutputToAudioStream` recusou stdout porque o stream não era
seekable. Um protótipo de stream seekable/forwarding travou e foi encerrado;
ele foi rejeitado e não entrou no produto. A classe final é
`WindowsBufferedPcmTts`, declara `streaming_pcm=false` e usa `MemoryStream`
seekable antes de entregar PCM ao sink cancelável.

Smoke real sem abrir alto-falante ou microfone:

```text
pcm_bytes=90944
pcm16_even=true
sink_closed=true
error=null
streaming_pcm=false
```

Portanto, TTS local pt-BR buffered está comprovado neste host. Playback
progressivo está implementado separadamente, mas ainda não foi tocado no
dispositivo; TTS redistribuível continua aberto.

## Preflight real do host

- `sounddevice 0.5.5` presente; dispositivo Realtek enumerado;
- permissão de microfone Windows permitida;
- Microsoft Maria Desktop pt-BR presente;
- reconhecedor do Windows disponível somente em en-US, portanto inelegível;
- Whisper e dois pesos verificados foram instalados; ffmpeg/voz redistribuível
  continuam ausentes;
- nenhum áudio foi capturado ou reproduzido durante este gate.

## Gate que permanece aberto

`PHYSICAL_DUPLEX=AWAITING_EXPLICIT_DEVICE_CONSENT`.

O manifesto imutável `release/voice-candidates/whisper-cpp-v1.9.2.json` propõe
`whisper.cpp` v1.9.2 no commit
`306c88f4d1286aec1bf96e544632897886af5501` e o modelo multilingual
`ggml-small-q5_1.bin` de 190.085.487 bytes com SHA-256
`ae85e4a935d7a567bd102fe55afc16bb595bdb618e11b2fc7591bc08120411bb`.
O estado adotado do host fica nos receipts do cache, não é escrito de volta no
manifesto de candidato.

Download e build do ASR foram concluídos. Captura de voz e teste auditivo ainda
dependem de decisão explícita. O Sprint 5 e o Product Alpha não estão completos.

Nenhum benchmark científico novo foi iniciado.
