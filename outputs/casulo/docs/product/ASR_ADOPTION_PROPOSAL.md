# Proposta de adoção ASR — aguardando consentimento

Estado: `PROPOSED_NOT_DOWNLOADED`.

O corte inicial recomendado para este i5/16 GB é `whisper.cpp v1.9.2` com o
modelo multilíngue `small-q5_1`. O engine é MIT; a distribuição oficial de
modelos declara MIT. O arquivo possui 190.085.487 bytes e SHA-256
`ae85e4a935d7a567bd102fe55afc16bb595bdb618e11b2fc7591bc08120411bb`.

Por que este corte:

- multilíngue, ao contrário das variantes `.en`;
- 190 MB, adequado ao espaço livre atual de aproximadamente 13,08 GB;
- qualidade potencial maior que tiny/base, sem adotar medium/large antes de
  medir latência em conversa;
- FFI/process boundary substituível; não vira a identidade do Casulo.

Após consentimento, a sequência será: baixar fonte/tag e modelo em cache
isolado, conferir commit/hash/licença, compilar adapter sem rede em runtime,
executar corpus pt-BR curto, medir endpointing/barge-in e só então decidir se o
modelo entra em `casulo-voice`. Nenhum download ocorreu nesta etapa.

O caminho de adoção já está implementado: consentimento literal, checkout Git
no commit exato, verificação de worktree limpo, tamanho/SHA-256 do modelo,
rollback, receipt, build offline da ABI first-party e doctor read-only. Essa
infraestrutura passou em backend/stub; não substitui a validação contra o
engine/modelo reais.

Fontes primárias consultadas:

- repositório oficial `ggml-org/whisper.cpp`, tag `v1.9.2`, commit completo
  registrado pelo `git ls-remote`;
- `models/README.md` oficial para modelos multilíngues e tamanhos;
- repositório oficial de modelos `ggerganov/whisper.cpp` para SHA-256.

Uma decisão separada continua necessária para TTS redistribuível. Microsoft
Maria é apenas fallback do sistema hosted.
