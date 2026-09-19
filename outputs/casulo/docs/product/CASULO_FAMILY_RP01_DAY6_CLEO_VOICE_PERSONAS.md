# CASULO FAMILY RP0.1 — Dia 6: Cleo, voz e personas isoladas

Gate técnico: PASS. O versionamento final é atestado separadamente após commit e push, sem ciclo de hashes. Dia 7 não iniciado.

## Baseline e escopo

Repositório canônico: `C:\Users\guimo\Downloads\ex`; código em `outputs/casulo`.
Branch `rp0.1-family`; entrada `8d46bb6a8e6b8e3a872ba97207dc444f4b61e7dc`, tree `28fc3be2c7bd5b35b42c2fb455e59be1886d56e1`.
O primeiro preflight foi somente leitura e a working tree estava limpa. O relatório e os 65 arquivos selados do Dia 5 foram verificados e preservados. Não se usou o antigo Git aninhado para versionar este trabalho.

Nenhum download, nova biblioteca, modelo pesado adicional, regra de firewall, confiança de certificado do Windows, telefone, conta familiar real ou teste histórico de pesquisa foi introduzido. Nenhum soak foi executado. Componentes de voz e navegador já estavam disponíveis e foram reutilizados após verificação.

## Fatos comprovados

O caminho executável é PWA/HTTPS Gateway → identidade autenticada → ASR loopback → resolução de persona → RAG isolado → Family Supervisor → Qwen2.5-7B Q2_K/Vulkan → política da resposta final → TTS loopback → WAV/PWA. A identidade/rota já é validada antes de aceitar áudio e novamente antes de RAG, prompt, inferência, síntese e entrega.

- Três instâncias versionadas: `cleo.host.guilherme`, `cleo.family.alexandra` e `cleo.family.eduardo`. Família somente em harness sintético; nenhum enrollment familiar de produção está habilitado neste launcher.
- `WORK`/`PLAY_PRIVATE` existem somente no host. Configurações familiares não contêm campos privados, e pedidos de escalada recebem recusa genérica antes de RAG/modelo.
- O host exige credenciais do owner, origem loopback, dispositivo/sessão registrados, desktop desbloqueado, rota `LOCAL_PRIVATE` e um participante declarado. Texto falado não autentica. Rota desconhecida/compartilhada e perda de autenticação negam acesso.
- Registros têm contratos exatos versionados. Ativação afetiva aceita somente frases diretas neutras explicitamente reconhecidas; ambiguidade, citações, RAG e marcadores externos ao harness não ativam. Trabalho/segurança restaura WORK, e risco suprime humor.
- Sessões, jobs, consultas RAG, citações e cancelamentos familiares permanecem separados nos testes. O prompt de sistema é um campo interno que a API não aceita. Trechos recuperados continuam no campo de dados do usuário, nunca escolhem perfil.
- Uma instância Qwen, uma geração ativa; FIFO existente com capacidade 2. Nenhuma geração pesada concorrente foi executada. `cache_prompt=false`, cache RAM desabilitado e limpeza nativa do único slot antes/depois de cada requisição Cleo; diretório de slots permaneceu vazio.
- Modelo e voz aceitam autenticação interna, escutam somente `127.0.0.1`; acesso interno sem credencial retornou 401. O launcher Dia 6 restringe também o Gateway a HTTPS loopback; LAN/mobile continua no gate posterior.
- ASR: whisper.cpp v1.9.2, commit `306c88f4d1286aec1bf96e544632897886af5501`, base Q5_1, CPU/2 threads. TTS: Microsoft Maria Desktop pt-BR via System.Speech, instalada no Windows. Áudio PCM16 mono 16 kHz, sem arquivos temporários.
- A tentativa final `attempt-5` concluiu o pipeline real e o navegador Chromium isolado. Também comprovou cancelamento ASR pelo Gateway, cancelamento nativo TTS, recuperação e encerramento dos processos. As tentativas anteriores foram preservadas.
- A PWA cancelou gravação sem upload, encerrou tracks antes do processamento, desabilitou novo microfone durante playback e voltou a IDLE após conclusão. O teste usou microfone simulado com WAV neutro e áudio físico silenciado; a captura de tela foi inspecionada.
- Família final: 70 testes aprovados, incluindo 34 focais do Dia 6. Product: 722 aprovados e um skip permitido. Nenhuma expectativa histórica foi alterada para obter aprovação.

Os números finais de latência, RAM, working set, disco, contadores, endereços, PIDs, versões e hashes estão em `evidence/family/day6/final-receipt.json`, `resource-samples.jsonl`, resultados JUnit e recibos por tentativa. As inspeções posteriores não encontraram processos ou listeners pertencentes ao runner.

## Privacidade e retenção

Conversas Cleo usam SQLite `:memory:` limitado a 16 jobs; retenção terminal de 120 s e descarte imediato pelo coordenador de voz. Não se cria `jobs.sqlite3` em disco. A auditoria contém identificadores, contagens e hashes, não áudio, transcrição, prompt ou resposta completos. Memória RAG explicitamente ingerida mantém a política isolada do Dia 5; não houve ingestão de material pessoal neste gate.

Entrada de voz: até 20 s; saída PCM até 1.920.000 bytes, texto TTS até 2.048 caracteres, subprocesso até 120 s; turno até 180 s e áudio concluído até 30 s. Há no máximo 16 recibos de voz e oito workers HTTP. Cancelamento, erro e encerramento liberam buffers, subprocessos e pipes. A PWA descarta Blob URLs, interrompe playback após revogação observada e cancela ao ocultar/fechar a página. Perda abrupta de rede sem mensagem de cancelamento é limitada pelo TTL; não se promete revogação retroativa de bytes já entregues.

Somente as fixtures neutras necessárias e suas saídas foram preservadas nos diretórios de evidência, com proveniência e hashes. Nenhum áudio íntimo ou caso de teste íntimo foi gravado. A ACL do estado é restrita ao owner. Não se afirma apagamento físico de RAM, pagefile, SSD ou caches internos do navegador.

## Comportamento observado e falhas preservadas

1. `attempt-1`: falha antes da resposta porque a versão de llama.cpp exige `--slot-save-path` inclusive para a operação `erase`. A documentação da API lista a operação, mas a condição adicional está no código do servidor. Foi habilitado um diretório privado vazio, com chave interna efêmera; salvar/restaurar cache não é chamado. A tentativa falha não vazou processos/portas.
2. `attempt-2`: pipeline real passou; ainda sem navegador.
3. `attempt-3`: pipeline passou; navegação HTTPS do navegador expirou. O handshake foi transferido para os workers limitados, removendo o bloqueio de aceitação causado por pré-conexões.
4. `attempt-4`: pipeline e navegador passaram. A segunda rodada de testes encontrou um `WinError 10053` intermitente na recusa HTTP de um teste legado. Foi adicionado descarte limitado do corpo POST não lido antes do fechamento, sem parse nem autorização; o novo teste determinístico e a suíte Family completa passaram. O diagnóstico de RST por corpo pendente é uma inferência de transporte, não captura de pacote.
5. `attempt-5`: revalidação integrada final após o ajuste HTTP, com evidências completas.

## Inferências e limites

- A arquitetura e os endpoints observados sustentam operação local/offline; não se executou ensaio físico com a interface de rede desligada. Telemetria própria do Windows está fora do runner.
- A versão pequena de ASR confundiu “céu” com “seu” num smoke neutro. Não se qualificaram sotaques, ruído, distância, vocabulário aberto nem qualidade ampla de transcrição.
- Maria oferece síntese local funcional, mas não foi qualificado controle confiável de prosódia WORK/PLAY_PRIVATE. A separação comprovada é por texto/metadata; não há claim de interpretação vocal, atriz, efeito psicológico ou sensualidade acústica.
- A rota privada e o único participante são declarações do owner verificadas junto da sessão/localidade/desktop; não há sensor de presença nem autenticação biométrica.
- O classificador de registro é deliberadamente estreito e conservador. Não se provou entendimento irrestrito de intenção. Modelos pequenos podem errar; os testes adversariais não são prova universal de resistência a prompt injection.
- Não se validaram microfone/alto-falante físicos, dispositivos Android, enrollment real de Alexandra/Eduardo, revogação por aparelho perdido, SQLite criptografado, full duplex ou wake word.
- No navegador de teste, o certificado foi primeiro verificado pela CA no runner e sua chave pública foi fixada por SPKI numa instância descartável. Não houve bypass TLS global nem instalação de raiz no Windows. Uma sessão de produção continua exigindo HTTPS e confiança do certificado.

Registro térmico literal, sem consultar sensores:

```text
temperature_monitoring=EXTERNAL_MANUAL_HWINFO
temperature_telemetry_collected_by_runner=false
temperature_claim=NONE
```

## Reprodução, integridade e rollback

No diretório de código, configure `PYTHONPATH=src;private/casulo-owner/src` com o Python existente. Execute `scripts/16-verify-family-day6.py` com `--repo` apontando para o diretório canônico, diretórios **novos** de estado/evidência, `--tls-dir` do bootstrap privado anterior e as opções de Node/Playwright para o navegador. O script recusa baseline diferente, modelo já existente, hashes divergentes e piso de recursos violado. O baseline Day 5 pode ser acessado em checkout isolado para repetir o gate sem alterar esta branch.

`scripts/17-test-family-day6.py` executa apenas os escopos autorizados e conserva stdout/JUnit. `scripts/18-seal-family-day6.py` exige aprovação real e dos testes, valida schema/contratos e produz os recibos. `scripts/19-attest-family-day6.py --seal-manifest` sela todas as evidências e este relatório; sem essa opção, produz fora do Git um recibo pós-commit completo, verificando SHA remoto, PRIVATE, fsck e working tree limpa.

O recibo pós-commit separado resolve a autorreferência criptográfica: um arquivo não pode conter o SHA literal do commit que inclui o próprio arquivo. Ele é reproduzível a partir do commit e do remote; o recibo versionado contém a evidência técnica e o comando para reconstruí-lo. Nenhum histórico/tag é reescrito.

Rollback operacional: encerrar o launcher Dia 6. Não apagar modelos, vozes, evidências ou repositórios antigos. O launcher e a documentação Day 5 foram preservados; o único serviço futuro exposto à LAN continua sendo o Gateway. Nenhum serviço ficou ativo após os testes.

Fontes primárias: [API llama.cpp b10964](https://github.com/ggml-org/llama.cpp/blob/b10964/tools/server/README.md), [condição de slots no servidor](https://github.com/ggml-org/llama.cpp/blob/b10964/tools/server/server-context.cpp), [whisper.cpp](https://github.com/ggml-org/whisper.cpp), [System.Speech](https://learn.microsoft.com/en-us/dotnet/api/system.speech.synthesis.speechsynthesizer). O SBOM e o recibo de proveniência registram licenças, versões, fontes, flags e hashes locais; a voz Windows não é redistribuída como dependência aberta.

## Próximo gate

Dia 7 — enrollment mobile/PWA, isolamento e revogação de dispositivo perdido, com acesso remoto seguro e sem exposição direta de ASR, TTS ou modelo. Não iniciar automaticamente.
