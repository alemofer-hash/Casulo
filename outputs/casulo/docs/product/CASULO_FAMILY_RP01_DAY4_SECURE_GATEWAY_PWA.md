# CASULO FAMILY RP0.1 — Day 4 Secure Gateway and PWA

Data autoritativa: 2026-09-19

Branch: `rp0.1-family`

Baseline: `c3d67ceed309eb13cede2c3440ac8d841cb94497`

Tree de entrada: `994825b08edc2e623a5789f5e44f43f438dbe682`

## Resultado

O gate do Day 4 passou na tentativa autoritativa 8. O fluxo conversacional real foi exposto somente pelo Family Gateway em HTTPS na LAN privada, enquanto a única instância Qwen2.5-7B Q2_K/Vulkan permaneceu em loopback. Dois clientes foram pareados independentemente para o mesmo usuário, o acesso entre sessões foi negado, um dispositivo foi revogado sem afetar o outro e duas gerações reais sequenciais terminaram por streaming.

## Fatos comprovados

- O baseline de entrada é o commit `c3d67ceed309eb13cede2c3440ac8d841cb94497`, tree `994825b08edc2e623a5789f5e44f43f438dbe682`, na branch `rp0.1-family`; a working tree estava limpa antes das alterações.
- O remote `origin` foi confirmado como `PRIVATE` em `alemofer-hash/Casulo`, sem credencial embutida na URL.
- O Gateway HTTPS ouviu em `192.168.1.4:54770`; o runtime ouviu somente em `127.0.0.1:54760`.
- Houve uma única instância de runtime e no máximo uma geração ativa. A fila manteve capacidade explícita 2.
- Foram pareados dois dispositivos em sessões diferentes do mesmo usuário. A segunda sessão recebeu HTTP 401 ao tentar ler o job da primeira.
- A memória da primeira sessão recebeu uma entrada; a segunda sessão permaneceu sem entradas até seu próprio uso.
- A revogação do primeiro dispositivo invalidou sua sessão, enquanto o segundo dispositivo permaneceu autenticado e concluiu nova geração.
- Códigos, tokens, prompts completos e credenciais não foram registrados. O registry persiste apenas hashes salgados das credenciais.
- Cookies de dispositivo e sessão usam `Secure`, `HttpOnly` e `SameSite=Strict`; mutações autenticadas exigem origem válida e CSRF double-submit.
- O Gateway desabilita CORS, aplica CSP, HSTS e outros cabeçalhos defensivos, e recusa bind LAN sem TLS, autenticação e sub-rede privada explícita.
- A PWA é same-origin, não possui dependências externas, restaura sessão, faz pareamento, consome streaming e permite cancelamento/logout. O service worker nunca armazena `/v1/`.
- O bootstrap TLS criou CA e certificado ECDSA P-256 fora do Git, com chaves e owner token sob ACL do proprietário. Nenhuma raiz foi instalada e nenhum segredo foi impresso.
- Testes finais: Day 4 focal 6/6; Family 29/29; Product 722 passados e 1 skip; compilação Python, sintaxe JavaScript, JSON, hashes, diff e secret scan passaram.
- Após o encerramento havia zero `llama-server`, zero listener correspondente e zero falha de limpeza de sampler.
- A política térmica foi preservada literalmente:
  - `temperature_monitoring=EXTERNAL_MANUAL_HWINFO`
  - `temperature_telemetry_collected_by_runner=false`
  - `temperature_claim=NONE`

## Comportamento observado

- A primeira geração real produziu sete fragmentos, primeiro fragmento em 842,306 ms e término em 2.509,895 ms.
- A segunda geração, executada pelo dispositivo não revogado, produziu cinco fragmentos, primeiro fragmento em 785,950 ms e término em 1.957,279 ms.
- O máximo de working set do runtime foi 3.642.892.288 bytes.
- A menor RAM disponível foi 5.499.600.896 bytes, acima do piso absoluto de 1 GiB e acima do limiar pré-start de 5 GiB.
- O menor espaço livre foi 106.989.469.696 bytes, acima da reserva permanente de 30 GiB.
- A tentativa autoritativa durou aproximadamente 4,73 segundos entre os timestamps de início e conclusão, além do teardown registrado.

## Inferências

- A combinação de autenticação por dispositivo, ownership de job por sessão e revogação dinâmica impede que um dispositivo pareado reutilize a sessão de outro dentro do modelo de ameaça testado.
- Manter o runtime em loopback e expor somente o Gateway reduz a superfície LAN, mas não substitui hardening do host, distribuição segura da CA e avaliação em dispositivos físicos.

## Limitações

- Nenhum celular ou segundo computador físico foi pareado; os dois clientes independentes foram exercitados pelo runner HTTPS local contra o endereço LAN.
- A CA local não foi instalada em trust store de cliente físico.
- Os valores de role são persistidos, mas políticas distintas para papéis não proprietários não pertencem a este gate.
- A memória do Day 4 isola metadados por sessão; ela não é uma memória conversacional/RAG completa.
- Não houve soak prolongado ou ensaio multiusuário de capacidade.
- Nenhuma telemetria térmica foi coletada pelo runner e nenhuma alegação térmica é feita.

## Histórico negativo preservado

- Tentativa 1: primeiro certificado sem AKI; cliente TLS recusou; corrigido sem sobrescrever evidência.
- Tentativa 2: RAM caiu abaixo de 1 GiB durante o carregamento; chat recusado e limpeza aprovada.
- Tentativa 3: sandbox não pôde ler o owner token protegido por ACL; integração não executada.
- Tentativas 4 e 6: admissão de recursos recusou startup abaixo de 5 GiB.
- Tentativa 5: instrumentação consultou o endereço antes do startup preguiçoso; corrigida e limpa.
- Tentativa 7: SSE enviava HTTP 200 antes da autorização de ownership. Não houve entrega de dados, mas a semântica fail-closed estava incorreta; a autorização foi movida antes dos headers e ganhou teste de regressão.
- Tentativa 8: PASS autoritativo.

## Itens ainda não validados

- instalação e confiança da CA em dispositivo físico;
- pareamento e PWA em celular/computador real da LAN;
- comportamento prolongado com vários clientes autorizados;
- políticas diferenciadas por role;
- qualquer propriedade térmica.

## Evidência reproduzível

As tentativas 1–8 estão preservadas em `evidence/family/day4/`. `attempt-8` é a execução autoritativa. `final-receipt.json` agrega resultados e métricas; `SHA256SUMS.txt` sela todos os arquivos de evidência diretos e históricos.

O runner reproduzível é `scripts/14-verify-family-day4.py`. Ele valida baseline, admissão de RAM, TLS, topologia de portas, pareamento, isolamento, revogação, duas gerações reais, recursos e limpeza.
