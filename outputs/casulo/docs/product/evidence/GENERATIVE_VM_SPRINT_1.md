# Evidência — Sprint 1 da VM generativa

## Resultado

`LOCAL_STOCHASTIC_INFERENCE_PASS`

O modelo Qwen3-4B Q4_K_M e o runtime llama.cpp b10362 foram baixados somente
após consentimento literal, verificados por tamanho e SHA-256 e promovidos de
staging para cache local. O runtime abriu apenas loopback, não usou shell e foi
encerrado ao fim do probe.

## Prova neural local

- três execuções normais concluídas e produziram três hashes distintos;
- todas emitiram múltiplos fragmentos de streaming;
- duas execuções de diagnóstico com seed fixa produziram o mesmo hash;
- uma execução foi cancelada depois do primeiro fragmento e terminou em
  `CANCELLED`;
- os traces registram hashes de modelo, contexto e saída, sampling e tempos;
- `external_ai_api_used=false`;
- `fake_engine_used=false`;
- `scientific_benchmark=false`.

## Artefatos e hashes

- candidato: `qwen3-4b-q4km-llamacpp-b10362`;
- manifesto do candidato:
  `42b2c54788298c10c781695d48f9f7867f5cb25e6407f90dcf0ff45466c70562`;
- modelo:
  `7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5`;
- archive do runtime:
  `a9d95d26cf00664f2902f73cb0fd9b167a3a1f252294bb2f8b236305f57d6363`;
- adoption receipt:
  `915c3a7ede5894f179b99d56d48c547949c75667731b865d4bfd279080bd52cc`;
- evidência do probe:
  `899c0d25b3d3c48b25c5c4acb930e3c66d98c2001a42d4182a6aa2ca2b3f8edd`.

Arquivo do probe:
`product-demos/generative-vm/sprint1/g1-local-inference.json`.

## Limite da evidência

G1 prova inferência local neural, estocástica e streaming no host atual. Não
prova ainda qualidade relacional, planejamento, síntese T, reparo, execução na
VM ou aprovação humana de voz/estética.
