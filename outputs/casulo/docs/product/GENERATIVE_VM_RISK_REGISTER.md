# Registro de riscos — VM generativa

| ID | Risco | Guarda atual | Estado |
|---|---|---|---|
| GV-R01 | policy determinística parecer generativa | exclusão e auditoria do artifact/entrypoint generativo | MITIGATED_VERIFIED |
| GV-R02 | peso/runtime adulterado | revisão, tamanho, SHA-256, manifesto e adoption receipt por arquivo | MITIGATED_VERIFIED |
| GV-R03 | download esgotar disco | pico calculado e reserva mínima de 20 GiB | MITIGATED_BY_DESIGN |
| GV-R04 | prompt injection/context poisoning | contexto tipado, output não confiável, tools por schema | MITIGATED_BY_DESIGN |
| GV-R05 | modelo fabricar grant/approval | capability broker e confirmação humana externas ao modelo | MITIGATED_BY_DESIGN |
| GV-R06 | resultado tardio após cancelamento | operation generation/epoch e consolidação transacional testadas | MITIGATED_VERIFIED |
| GV-R07 | repair loop infinito | 2 projetos, 3 candidatos por revisão, 4 reparos e falha explícita | MITIGATED_VERIFIED |
| GV-R08 | QMP ou bridge virar túnel genérico | transporte local restrito, sem rede e mensagens versionadas | MITIGATED_VERIFIED |
| GV-R09 | guest montar disco interno | somente arquivos regulares confinados | MITIGATED_BY_DESIGN |
| GV-R10 | overlay/snapshot crescer sem limite | base única, overlay esparso e reset seguro; quota futura | MONITORED |
| GV-R11 | química/voz/visual serem aprovados artificialmente | inspeção de Guilherme obrigatória | OPEN_HUMAN |
| GV-R12 | Cloud/public contaminados | builds separados e auditoria public selada | MITIGATED_VERIFIED |
| GV-R13 | Live USB antecipado | operações de mídia física proibidas neste GOAL | BLOCKED_BY_POLICY |
| GV-R14 | aquecimento em inferência CPU | sessões curtas, quatro threads, cancelamento e segurança física | MONITORED_G1_PASS |
| GV-R15 | reasoning oculto consumir saída estruturada | llama.cpp `--reasoning off`, JSON visível e trace | MITIGATED_VERIFIED |
| GV-R16 | teste neural impossível de satisfazer em T | análise prévia de tamanho/gramática por unidade | MITIGATED_VERIFIED |
| GV-R17 | runtime concluir sem conteúdo | conclusão vazia vira falha terminal e regressão | MITIGATED_VERIFIED |

Vetores já cobertos no Sprint 1: ZIP traversal, symlink, nomes de device
Windows, archive bounds, cache adulterado, overwrite, origem externa,
consentimento divergente, contexto excessivo, stream malformado, falha local e
cancelamento antes e durante o dispatch. O probe neural real aprovou carga,
streaming, sampling normal variável, seed debug reproduzível e encerramento
sem processo órfão. Prompt injection e consolidação transacional continuam no
escopo do Sprint 2.

Gates posteriores cobriram confirmação material, reparo limitado, simulação sem
efeitos, cancelamento, bridge serial tardio, base imutável, restore/reset,
receipts reais, export sanitizado e ausência de componentes privados no wheel
público. Permanecem humanos: química, voz e estética. Permanecem técnicos:
sessão Native residente, voz duplex e quota explícita do overlay.

O cenário G10 integrado passou 16/16 na tentativa 12. As tentativas 1–11
permanecem como evidência negativa e originaram regressões; nenhuma foi removida
ou usada para selecionar silenciosamente resultado positivo.
