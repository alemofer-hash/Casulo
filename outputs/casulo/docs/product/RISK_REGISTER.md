# Registro de riscos

| ID | Risco | Severidade | Mitigacao atual | Estado |
|---|---|---:|---|---|
| R-001 | vazamento do motor owner no build public | critica | targets exclusivos, auditoria de artefato, CI fail-closed | aberto |
| R-002 | Cloud acidentalmente exposta | critica | `RELEASE_LOCKED`, sem bind/deploy/credenciais reais | controlado |
| R-003 | progresso ficticio do Guia | alta | eventos canonicos e testes contratuais | aberto |
| R-004 | modelo fabricar grants | critica | capability broker fora do modelo, deny-by-default | aberto |
| R-005 | partial transcript consolidar intencao | alta | estado provisorio + endpointing + confirmacao | aberto |
| R-006 | memoria perder proveniencia ou delete | critica | arquivos imutaveis, hash chain, DPAPI, projecoes reconstruidas, testes de corrupcao/export/delete | controlado parcial |
| R-007 | dependencia/modelo sem licenca redistribuivel | alta | ledger, cards, hashes, consentimento de download | aberto |
| R-008 | rota `learn` contornar frontend/IR geral | alta | classificada legacy; proibida como caminho invisivel do produto | controlado parcial |
| R-009 | Python/Rust divergirem semanticamente | alta | contratos versionados + testes de paridade antes de migracao | aberto |
| R-010 | escopo native bloquear produto hosted | alta | perfis separados e roadmap de convergencia | controlado |
| R-011 | hardware local insuficiente para voz/modelo | media | perfil base-q5_1/4 threads medido localmente; Machine Profile e fallback acessivel | controlado parcial |
| R-012 | benchmark historico reaparecer como claim | alta | ADR, guard CLI, CI sem science/PyTorch | controlado |
| R-013 | dois writers criarem fork no log de memoria | alta | V1 declara single-writer; lock multi-processo e gate pre-release | aberto |
| R-014 | modelo ASR grande demais, impreciso ou sem licenca comprovada | alta | small/base pinados por hash, receipts por modelo e captura pt-BR; sentinela de barge-in ainda imprecisa | controlado parcial |
| R-015 | ABI compilar no stub e divergir do upstream real | alta | build real pinado, link autocontido, doctor carrega ABI e boundary smoke passa | controlado |
| R-016 | fallback hosted ser confundido com TTS streaming redistribuivel | alta | cards distinguem buffered, playback progressivo e PCM; tudo nao redistribuido | controlado parcial |
| R-017 | licenca permissiva do engine ocultar GPL/model card na cadeia TTS | critica | ledger por componente; sherpa/Piper bloqueado para revisao; CI verifica disabled/not downloaded | controlado parcial |
| R-018 | pressao de disco induzir remocao perigosa ou instalacao incompleta | alta | limpador dry-run, raizes protegidas, alvos opt-in e receipts; reserva atual ~57 GiB | controlado |
| R-019 | barge-in cancelar antes de a transcricao estar semanticamente estavel | alta | separar VAD de interpretacao, preservar transcricao rejeitada, calibrar por dispositivo e planejar AEC | aberto |
| R-020 | gramatica inicial de intencao ser estreita demais para conversa natural | media | manter clarificacao honesta, separar adapter semantico do contrato e ampliar somente com testes/RFC | aberto |
| R-021 | Campo estrutural passar sem revisao visual automatizada real | media | demo local selada, testes de HTML/CSP/a11y e revisao humana pendente; controlador interno reportado quebrado | aberto |
| R-022 | doubles estaticos nao representarem toda a semantica do mundo real | alta | receipts delimitam simulacao, cenarios sao explicitos e efeitos reais permanecem proibidos | aberto |
| R-023 | API materializada ser confundida com execucao produtiva de effects | alta | bind loopback, resposta simulation-only, manifest sem engine e `real_effects_included=false` | controlado parcial |
| R-024 | harness Cloud de teste ser confundido com servico publicado | critica | principal test-only, metricas sem conteudo, demo declara standby e bind de producao falha incondicionalmente | controlado |
| R-025 | doctor ou instalador alterar a maquina sem consentimento | critica | doctor/plan read-only, frase derivada do plano, staging confinado, sem rede/download no initializer | controlado parcial |
| R-026 | gate Native tocar disco real ou reativar benchmark historico | critica | arquivo regular sob repo, imagem read-only, rede off, marcadores de produto sem tempo/energia/loss | controlado |
| R-027 | contexto neural sofrer truncamento implicito ou consumir compute desproporcional | alta | budgets por operacao, teto conservador UTF-8, drops explicitos, receipts e gates fail-closed | controlado parcial |
| R-028 | especialização local ser extrapolada como substituição da álgebra neural geral | alta | inventário explícito, policy T fail-closed, claim class limitada, fallback denso e evidência separada do tensor stack histórico | controlado parcial |
| R-029 | interface fluida sugerir progresso ou disponibilidade neural inexistentes | alta | eventos tipados, estados PRESENCE/MODEL separados, milestones com hash, porcentagem proibida e cancelamento fail-closed | controlado parcial; prova humana pendente |
| R-030 | plano de controle Native ser confundido com port completo do produto | alta | adapters Hosted listados no serial, documento de fronteira, gate sem claim de voz/modelo e boot QEMU somente de correção | controlado parcial |
