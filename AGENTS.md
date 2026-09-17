# AGENTS.md — Casulo universal execution policy

## Owner directive

Adote em toda tarefa deste repositório a filosofia:

> “Máquina não é Retardada, sabe fazer sem eu Mandar.”

Sua interpretação normativa é: ausência de capacidade local não é bloqueador; é trabalho de bootstrap pertencente ao agente.

## Mandatory behavior

Quando faltar ferramenta, pacote, runtime, compilador, modelo, serviço, certificado, adapter, bridge, script ou outro componente necessário:

1. descubra a fonte oficial;
2. baixe e verifique;
3. instale ou compile;
4. configure;
5. implemente o mínimo ausente se não houver solução pronta;
6. teste;
7. congele versão/origem/hash/licença;
8. atualize locks/SBOM;
9. retome o objetivo original sem esperar nova ordem.

Não retorne `BLOCKED` apenas porque algo não está instalado, baixado, compilado ou configurado. Não peça ao proprietário para executar trabalho mecânico que você pode executar dentro da autorização existente.

## Legitimate blockers only

`BLOCKED` exige evidência de ao menos uma destas condições:

- credencial, login ou MFA exclusivamente humano;
- compra ou compromisso financeiro;
- licença que exige aceite pessoal;
- hardware ausente sem alternativa funcional;
- permissão efetivamente negada;
- rede indisponível sem cache/alternativa;
- alvo externo ambíguo com risco de escrita errada;
- ação destrutiva/irreversível não autorizada.

## Safety

Autonomia não permite contornar controles, baixar fonte duvidosa, expor serviços, vazar segredos, apagar trabalho, fazer force-push, gastar dinheiro ou aceitar risco material em nome do proprietário. Prefira mudanças reversíveis, fontes oficiais, hashes, smoke tests e rollback.

## Casulo-specific invariants

- Gateway é o único serviço exposto à LAN.
- LLM, ASR, TTS e workers permanecem em loopback.
- Sem API de inferência paga.
- Sem dependência operacional obrigatória de cloud.
- Um job generativo pesado por vez em 16 GB de RAM.
- Memórias e dados são isolados por usuário.
- Toda mutação relevante produz diff, receipt, snapshot e possibilidade de rollback.

