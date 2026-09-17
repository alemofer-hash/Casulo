# Proposta de TTS pt-BR — revisão de licença obrigatória

Data: 2026-08-11

Estado: `NO_CANDIDATE_ADOPTED`.

## Resultado

Não existe ainda um corte completo engine + fonemizador + voz que possa ser
adotado silenciosamente como dependência redistribuível do Casulo.

### Piper successor

`OHF-Voice/piper1-gpl` é o sucessor ativo e suporta pt-BR, mas usa GPL-3.0. Ele
não será congelado como default de um produto que separa motor privado, cliente
público e supply chains sem uma decisão jurídica/arquitetural explícita.

### sherpa-onnx + Piper voice

`sherpa-onnx` v1.13.5 está pinado apenas para revisão no commit
`3dc7c569f31ca2cd4a20ed6f7db780327e6714c5` e possui licença top-level
Apache-2.0. Porém, quando TTS é habilitado, o próprio build inclui
`espeak-ng-for-piper` e `piper-phonemize`; eSpeak NG é GPL-3.0-or-later.
Logo, a licença top-level não resolve a cadeia distribuída.

A voz `pt_BR-edresson-low` existe e é pequena para este host:

- ONNX: 63.104.526 bytes;
- SHA-256: `de4cecee38b30bb1a6378a337af605d59f0c377df702c6a6752870db8991cd84`;
- configuração: 4.168 bytes, SHA-256
  `f138992d2e777d1e3aa0bbb14c2d324307b0f342c1bcf20978765b3bea506c56`;
- model card: SHA-256
  `d8fb0dab2d61ad9796904836fb2fc0ac7e324d89e80bc9ef14e328b77e5cb66f`;
- corpus declarado pelo card: CC BY 4.0;
- qualidade declarada: low.

O repositório de vozes declara MIT em nível global, mas o Casulo trata o model
card específico como restrição mais próxima e não o sobrepõe silenciosamente.

## Decisão atual

- Maria/System.Speech: fallback hosted buffered, não redistribuído;
- Piper GPL: não adotado;
- sherpa/Piper: `LICENSE_REVIEW_REQUIRED_NOT_ADOPTED`;
- TTS streaming redistribuível: gate aberto;
- downloads: zero.

Alternativas futuras legítimas:

1. aceitar conscientemente obrigações GPL em um processo/edição separado;
2. selecionar uma engine permissiva com fonemização pt-BR também permissiva;
3. construir frontend fonético e voz próprios do Casulo com dataset/licença
   auditáveis.

Nenhuma dessas escolhas é inferida por este documento.
