# RC9 — Materialização externa

O materializador publica transacionalmente uma matriz explícita por criação:
pacote `.casulo`, CLI T compilada, API loopback, serviço local e interface web
autocontida. Um target incompatível é recusado no manifesto antes do build.

O probe RC9 executa a criação extraída em clean-room fora do checkout, com
`python -X utf8 -I`, sem `PYTHONPATH`, cache, secrets, rede externa ou motor
owner. Ele percorre `export v1 -> import -> edit -> export v2`, preservando
identidade, constraints, capabilities, proveniência e source T. As duas versões
permanecem recuperáveis e recebem assinaturas Ed25519 externas rotuladas
`DEVELOPMENT_SIGNATURE_NOT_COMMERCIAL_RELEASE`.

A UI é local, sem scripts, com CSP; a API limita corpo e bind em 127.0.0.1. O
TCAP inclui source, IR, graph e código gerado. Os testes executam apenas efeitos
simulados. Isso é validação local de produto, não equivalência com um sandbox de
SO nem assinatura comercial.
