# Sequência exata da primeira sessão do Codex

## Entrada

Abra o Codex no diretório:

```text
C:\Users\guimo\Downloads\ex
```

Entregue `01_PROMPT_GOAL_CODEX.md` integralmente. Depois forneça este comando de missão:

```text
Execute somente o STAGE ZERO. Não reorganize, formate, atualize dependências ou corrija testes antes do snapshot bruto. Comece pelo preflight somente leitura, produza inventário e mapa de riscos, pare antes de git add/commit se encontrar segredos ou arquivos não classificados, e exija minha revisão do staging. Ao concluir, retorne exatamente o contrato de evidências definido no /GOAL.
```

## Resposta mínima esperada do Codex

```text
STATUS: PASS | FAIL | BLOCKED
EVIDENCE:
CHANGES:
RESOURCE_BUDGET:
RISKS:
NEXT_GATE:
```

## Autoridade da primeira sessão

Permitido:

- inspeção somente leitura;
- criação de inventários e relatórios;
- `.gitignore` conservadora;
- inicialização Git após inspeção;
- staging e apresentação para revisão;
- commit/tag após revisão explícita;
- testes não destrutivos depois do snapshot.

Não permitido:

- apagar duplicatas;
- mover/reorganizar arquivos antes do snapshot;
- atualizar dependências;
- executar scripts desconhecidos;
- corrigir testes;
- baixar modelos;
- instalar toolchain;
- abrir portas;
- mudar firewall;
- enviar conteúdo a remoto.

## Próxima sessão

Somente após `STAGE_ZERO_COMPLETE`, autorizar auditoria arqueológica e baseline executável. Não começar o Dia 1 por intuição arquitetural.

