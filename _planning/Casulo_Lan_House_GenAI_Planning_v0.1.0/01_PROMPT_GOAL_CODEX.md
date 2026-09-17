# PROMPT MESTRE PARA O CODEX

Copie integralmente o bloco abaixo para uma sessão do Codex aberta em:

`C:\Users\guimo\Downloads\ex`

```text
/GOAL

Você é o engenheiro principal responsável por auditar, preservar e transformar o conteúdo consolidado em C:\Users\guimo\Downloads\ex no CASULO FAMILY RP0.1 em exatamente dez dias de execução disciplinada.

MISSÃO

Entregar um motor generativo pessoal e familiar, local e offline-first. Este notebook Intel Core i5, 16 GB RAM, GPU integrada e SSD de 256 GB com 127 GB livres será o servidor principal da “Lan House GenAI”. O modelo roda somente no laptop. Celulares e computadores explicitamente autorizados acessam uma PWA por HTTPS na LAN e nunca precisam executar o modelo.

O produto final deve oferecer:

1. chat local em português por texto;
2. entrada e saída de voz local;
3. acesso responsivo pelo navegador/PWA do telefone;
4. usuários e memórias estritamente separados;
5. pareamento e revogação por dispositivo;
6. RAG sobre documentos autorizados;
7. agente de programação que leia, planeje, altere por patch, teste, revise e reverta;
8. fila de execução adequada a 16 GB de RAM;
9. receipts, hashes, snapshots, auditoria e rollback;
10. funcionamento da bateria final sem API paga, chave externa ou inferência cloud.

ARQUITETURA OBRIGATÓRIA

- O Casulo Gateway é o único serviço exposto à LAN, por HTTPS.
- O runtime generativo, ASR, TTS, memória e workers escutam apenas em loopback.
- O gateway autentica usuário e dispositivo, aplica cotas, fila, políticas e auditoria.
- O modelo é um componente substituível; não é autoridade sobre políticas ou resultados.
- Preserve e integre, quando realmente implementados, T -> AST -> análise semântica -> IR versionada -> grafo -> TCAP -> loader -> scheduler, GuidePresence, EXPANSION/CRYSTALLIZATION, JobEvent, proveniência, hash, memória local e pipeline de voz existente.
- Não presuma que documentação equivale a implementação. Toda alegação deve apontar para código, teste ou evidência reproduzível.

RESTRIÇÕES DE HARDWARE

- Trabalhe com 16 GB de RAM e GPU integrada.
- Use inicialmente modelo GGUF de 7–9B quantizado em aproximadamente 4 bits.
- Mantenha somente um modelo principal carregado por vez.
- Contexto inicial de 8k; 16k apenas após benchmark de RAM e latência.
- Uma geração pesada simultânea; demais requisições entram em fila.
- Não use modelo de 20–30B, treinamento fundacional ou fine-tuning no caminho crítico.
- Preserve pelo menos 30 GB livres no SSD durante todo o sprint.

STAGE ZERO — OBRIGATÓRIO ANTES DE ALTERAR CÓDIGO

1. Inventarie arquivos, tamanhos, extensões e hashes.
2. Confirme a ausência de repositórios .git residuais; os repositórios anteriores foram excluídos conscientemente pelo proprietário.
3. Faça varredura local de segredos sem imprimir seus valores.
4. Identifique arquivos grandes, artefatos gerados, modelos e dados privados.
5. Crie .gitignore conservadora, preservando fontes, testes, documentos, lockfiles e fixtures pequenas.
6. Inicialize Git e crie um commit bruto de preservação antes de reorganizar ou formatar.
7. Crie tag anotada casulo-stage0-raw-2026-09-17.
8. Gere e verifique um git bundle em outro dispositivo quando o caminho externo estiver disponível.
9. Execute git fsck --full e exija working tree clean.
10. Emita STAGE_ZERO_COMPLETE ou pare com bloqueio explícito e evidências.

MÉTODO DE TRABALHO

- Audite primeiro; implemente depois.
- Não apague nem sobrescreva conteúdo do usuário.
- Não use git reset --hard, git clean -fd, checkout destrutivo ou remoção recursiva.
- Preserve mudanças preexistentes e mantenha commits pequenos, reversíveis e semanticamente nomeados.
- Use patches para edição.
- Faça baseline antes de corrigir testes.
- Registre cada dependência, licença, versão e SHA-256.
- Não introduza Docker, Kubernetes, Redis, banco vetorial externo ou serviço cloud no caminho crítico.
- Prefira Rust/Python/SQLite/FTS5 e os componentes já presentes no repositório.
- Use llama.cpp como backend inicial de inferência e mantenha sua API apenas no loopback.
- Reaproveite whisper.cpp/TTS Maria/bridge existente somente após validar o código real.
- Não exponha shell, filesystem ou modelo diretamente à rede.
- Para cada ferramenta, defina schema, permissões, timeout, orçamento, efeitos e rollback.
- Requisições destrutivas, administrativas ou fora do workspace exigem confirmação humana.

GATES DIÁRIOS

Dia 0: snapshot Git, bundle, inventário e auditoria estrutural.
Dia 1: mapa arqueológico do Casulo, baseline de testes e arquitetura canônica.
Dia 2: modelo local servido em loopback, benchmark CPU/Vulkan e perfil escolhido.
Dia 3: gateway, sessões, streaming, fila e cancelamento.
Dia 4: loop agente-ferramenta com JSON Schema, sandbox, receipts e rollback.
Dia 5: memória/RAG local com isolamento por usuário e proveniência.
Dia 6: integração e estabilização da voz, inclusive barge-in.
Dia 7: PWA HTTPS, pareamento e revogação de dispositivos na LAN.
Dia 8: modo construtor de código com patch, testes, revisão e limites.
Dia 9: hardening, instalador, inicialização, backup e recuperação.
Dia 10: bateria offline completa, documentação e release CASULO FAMILY RP0.1.

CONTRATOS DE SEGURANÇA

- deny-by-default;
- nenhuma porta pública no roteador;
- firewall restrito ao perfil Private e à sub-rede familiar;
- tokens de pareamento de uso único, curtos e expirados;
- credenciais nunca em Git ou logs;
- memória, índices e histórico separados por usuário;
- áudio bruto efêmero por padrão;
- ferramentas executadas com usuário sem privilégios;
- limites de CPU, RAM, tempo, saída e iterações;
- toda escrita relevante produz diff, receipt e snapshot anterior;
- o proprietário consegue revogar qualquer dispositivo imediatamente.

CRITÉRIO DE PRONTO

O trabalho só termina como SUCCESS quando, com a internet bloqueada:

1. dois dispositivos autorizados acessam a PWA por HTTPS;
2. dispositivo não pareado é recusado;
3. dois usuários não conseguem acessar memória um do outro;
4. chat textual funciona em português;
5. voz completa funciona sem enviar áudio externamente;
6. uma tarefa de código é planejada, alterada por patch, testada e revertida;
7. uma tentativa destrutiva é bloqueada;
8. reinicialização do laptop recupera fila, memória e estado consistente;
9. nenhum processo de inferência escuta na LAN;
10. não há chave de API nem requisição de inferência externa;
11. uso de RAM e disco permanece dentro dos limites definidos;
12. release, hashes, SBOM, licenças, testes e limitações são registrados.

FORMATO DE RELATO

Ao fim de cada gate, retorne:

STATUS: PASS | FAIL | BLOCKED
EVIDENCE: comandos, arquivos, testes e métricas
CHANGES: arquivos e commits
RESOURCE_BUDGET: RAM, disco, temperatura e tempo
RISKS: riscos abertos sem suavização
NEXT_GATE: uma única próxima etapa autorizada

Não declare equivalência com Codex, GPT ou qualquer modelo de fronteira. Meça utilidade operacional no hardware real. Quando houver ambiguidade, preserve dados, pare a mutação e peça decisão. Não encerre o sprint por encontrar uma necessidade técnica: resolva-a se estiver dentro do escopo; se exigir autoridade, hardware ou dados não fornecidos, registre bloqueio preciso.
```

