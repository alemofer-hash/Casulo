# GATES E TESTES DE ACEITAÇÃO

## P0 — Auditoria limpa

- `AGENTS.md` e README lidos;
- worktree preexistente preservado;
- testes baseline registrados;
- nenhum benchmark científico no default;
- evidência histórica arquivada e intacta.

## P1 — Modelo de domínio

- schemas versionados;
- migração testada;
- delta inválido não altera estado;
- permissões nunca aumentam implicitamente;
- serialização canônica possui golden tests.

## P2 — Memória

- restart recupera criação;
- decisão rejeitada não reaparece como atual;
- memória derivada possui proveniência;
- ambiguidade material gera pergunta;
- export/delete testados;
- raw history não é substituído por resumo.

## P3 — Voz

- ASR/TTS inteiramente locais no perfil offline;
- pt-BR smoke test;
- transcrição parcial não consolida intenção;
- barge-in cancela fala;
- silêncio e pensamento incompleto não geram interrupção excessiva;
- fallback acessível funciona.

Budgets devem ser calibrados e registrados por classe de máquina, não fixados universalmente.

## P4 — Guia

- continua disponível com worker ocupado;
- não inventa porcentagem/progresso;
- pergunta somente quando risco/ambiguidade justificam;
- adaptação material exige consentimento;
- modo de correção respeita contrato;
- testes adversariais para bajulação, pressão, estereótipos e certeza falsa.

## P5 — T e capabilities

- frontend -> análise -> IR -> graph -> `.tcap` sem atalho invisível;
- módulos resolvidos;
- capability ausente falha;
- generative model não consegue fabricar grant;
- parsers fuzzados;
- corrupção/hash inválido -> quarentena;
- compatibilidade T 1.0 preservada ou migração explícita.

## P6 — Incrementalidade

- delta local preserva hashes fora de `Impact(A)`;
- conflito de base version não sobrescreve estado;
- undo por intenção reidrata versão correta;
- testes afetados selecionados corretamente;
- regeneração total exige motivo registrado.

## P7 — Visual

- todos os 12 estados representáveis;
- cores/efeitos correspondem a semântica;
- sem dados decorativos falsos;
- voz não degrada por renderer;
- low-end mode mantém significado;
- snapshots/visual regression em cenas canônicas.

## P8 — Simulação

- nenhuma capability real disponível;
- relógio virtual;
- injection de falha;
- pause/interruption;
- replay determinístico quando aplicável;
- invariantes avaliadas antes de aprovação.

## P9 — Inteligência local

- funciona sem internet após instalação/cache;
- modelo/voz possuem hash, licença e card;
- arquivo malformado é rejeitado;
- RAM/VRAM limitadas;
- context selection preserva restrições obrigatórias;
- nenhum endpoint comercial obrigatório no código default.

## P10 — Materialização

- pacote Casulo round-trip;
- API local executável;
- secrets excluídos;
- manifest + SBOM + hashes;
- sandbox test;
- dependências declaradas;
- artefato permanece funcional sem assinatura Casulo Cloud.

## P11 — Installer

- `doctor` não muta sistema;
- download exige consentimento;
- hash/licença verificados;
- estimativa de tempo honesta;
- falha recuperável não corrompe instalação;
- uninstall/export de memória documentados;
- sem cadastro obrigatório.

## P12 — Native

- boot QEMU/OVMF reproduzível;
- panic/serial/framebuffer;
- isolamento ring 3 mínimo;
- `.tcap` validado e executado;
- imagem é arquivo regular;
- nenhuma escrita em block device real;
- shutdown seguro.

## P13 — End-to-end

Cenário obrigatório:

1. iniciar Casulo;
2. conversar por voz em pt-BR;
3. criar um agente cotidiano simples;
4. observar estados visuais progressivos;
5. interromper o Guia;
6. corrigir personalidade sem mudar permissões;
7. fechar Casulo;
8. reabrir e dizer “lembra daquilo?”;
9. retomar ponto correto;
10. simular ação proibida;
11. corrigir política;
12. materializar como API local;
13. executar fora do Casulo;
14. importar novamente;
15. comprovar identidade e versão.

## Testes transversais

### Segurança

- path traversal;
- zip bomb/model bomb;
- overflow/tamanho;
- segmentos `.tcap` sobrepostos;
- capability escalation;
- prompt injection em memória importada;
- exfiltração de secrets;
- network denied-by-default;
- parser fuzz;
- crash recovery.

### Privacidade

- áudio local;
- telemetria opt-in;
- criptografia local;
- delete/export;
- logs sem secrets;
- crash dump sanitizado.

### UX contratual

- usuário não precisa tocar mouse/teclado no cenário P13;
- nenhuma informação essencial depende apenas de cor;
- Guide pode ser silenciado/interrompido;
- mensagem de espera informa tempo aproximado;
- conversa de espera é desligável;
- nenhuma unidade “token” aparece no caminho normal.

### Confiabilidade

- cancelamento não corrompe memória;
- queda durante write recupera WAL/event log;
- migração reversível/backup;
- processo background não trava presence loop;
- degradação de GPU cai para renderer simples.

## Testes que não pertencem ao gate do produto

- pares T versus PyTorch;
- IC95% de speedup;
- energia por treinamento;
- RAPL/wattímetro;
- comparação de schedulers para paper;
- reprodução multi-host científica;
- ablação causal do benchmark FloodSurrogate.

## Evidência de aprovação

Cada gate registra:

- comando;
- versão/commit;
- ambiente;
- resultado;
- logs relevantes;
- limitações;
- arquivos de teste;
- estado `PASS`, `FAIL`, `BLOCKED_ENVIRONMENT` ou `NOT_APPLICABLE`.

Não usar `NOT_APPLICABLE` para esconder capacidade obrigatória do Product Alpha.

