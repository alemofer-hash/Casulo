# Evidência Sprint 2 e fronteiras transversais

## Hosted Shell

- `SILENCE` é apresentado no boot;
- evento de voz sintético pt-BR gera `FIRST_INTENT`;
- partial transcript permanece provisório;
- `PRESENCE` executa antes de `BACKGROUND`;
- playback buffer aceita cancelamento;
- storage atômico bloqueia path traversal.

O input é explicitamente `synthetic-not-asr`; nenhuma alegação de ASR/TTS real
é feita neste Sprint.

## Builds separados

```text
casulo_public-0.1.0a1-py3-none-any.whl
SHA256 096068C3B42D3DC158932D1ED1EFF8F2C5CC890C02FAADDFE52831193EBF46F4

casulo_owner-0.1.0a1-py3-none-any.whl
SHA256 225743ABCA394E492C6ED2E204DD973F0529A7E77CED7F12E7280174F86D7D51

casulo_cloud_standby-0.1.0a1-py3-none-any.whl
SHA256 3DE04609B8BEAA7128EC01D54BEE1E5C349E25A36E11CE3D2D2231A325FB6AB2
```

Auditoria do wheel public: 6 arquivos, zero achado proibido,
`content_tree_sha256=6ea3f750d844ec7e519a2f81c012b8b6fda2dcacb92712aba50cc8721284d9d5`.

Pacote durável: `outputs/casulo/product/2026-08-11-sprint2-edition-boundary/`.

Teste consolidado após as fronteiras: `74 passed, 42 subtests passed`.

Resultado: `SPRINT_2_PASS` para o slice hosted mínimo; P14/P15 permanecem
`PARTIAL_PASS` até SBOM/assinatura e servidor standby completo.
