# CASULO FAMILY RP0.1 — Day 3 Supervisor Integration

Data autoritativa: 2026-09-19

Branch: `rp0.1-family`

Baseline: `be19c85df370277fb2a71915e57f7e883e0508e6`

Tree de entrada: `29bd537b005f336677059f4205b1353aa0033d29`

## Resultado

O gate do Day 3 passou. O adapter proprietário iniciou exatamente uma instância de `llama-server` para Qwen2.5-7B-Instruct Q2_K com Vulkan, sempre em `127.0.0.1`. O Family Supervisor manteve uma única geração ativa, uma fila FIFO limitada a dois itens e backpressure determinístico em HTTP 429.

## Fatos comprovados

- A execução autoritativa foi `evidence/family/day3/attempt-6`; as tentativas 1–5 foram preservadas como histórico negativo.
- O runtime efetivo ouviu temporariamente em `127.0.0.1:52578`; o Gateway de validação ouviu temporariamente em outro endereço loopback. Nenhum deles foi exposto à LAN.
- O adapter usou `Qwen/Qwen2.5-7B-Instruct-GGUF`, revisão `293ca9a10157b0e5fc5cb32af8b636a88bede891`, arquivo Q2_K SHA-256 `a0fc885ff014d73c02dcc4ad093f110c6dd4e0e308f84efe1accf078d364a87a` e `llama.cpp` b10964/Vulkan.
- O máximo observado foi uma geração e uma requisição de adapter ativas.
- A fila tinha capacidade 2. Com uma geração ativa, duas requisições ficaram enfileiradas e a excedente recebeu HTTP 429 com `Retry-After: 1`; ela não iniciou inferência.
- O cancelamento cobriu item enfileirado, geração ativa, substituição enfileirada e desconexão do cliente. Nenhum cancelamento foi apresentado como conclusão.
- Após cancelamento, a fila avançou em FIFO, uma geração curta posterior terminou com sucesso e o supervisor retornou a `READY` sem transição `DEGRADED` ou `FAILED`.
- O streaming foi incremental e ordenado, com evento terminal inequívoco. A resposta não foi registrada integralmente; as evidências guardam contagem de caracteres e hashes dos fragmentos.
- O menor valor de RAM disponível foi 2.182 GiB; o maior working set do runtime foi 3.396 GiB; o menor espaço livre foi 106.319 GiB.
- Ao terminar, havia zero `llama-server.exe` e zero listeners correspondentes. O supervisor terminou em `STOPPED`.
- Testes: foco Day 3 15/15; Family 23/23; Product autoritativo 722 passados e 1 skip.
- A telemetria térmica não foi coletada pelo runner, conforme decisão explícita do proprietário:
  - `temperature_monitoring=EXTERNAL_MANUAL_HWINFO`
  - `temperature_telemetry_collected_by_runner=false`
  - `temperature_claim=NONE`

## Comportamento observado

- A geração FIFO concluída teve primeiro fragmento em 1331.503 ms e duração total de 2073.641 ms.
- A geração curta posterior ao cancelamento teve primeiro fragmento em 797.981 ms e duração de 2270.218 ms.
- A execução integrada autoritativa durou aproximadamente 12.1 segundos entre os timestamps do runner, além do startup e teardown registrados nas transições.
- Foram aceitas/enfileiradas 6 requisições, rejeitada 1, canceladas 4, concluídas 2 e falharam 0.

## Inferências

- Os limites de fila, buffer e uma geração ativa reduzem o risco de crescimento de memória sob concorrência, mas a carga validada é a bateria controlada do Day 3, não um ensaio de capacidade multiusuário prolongado.
- A recuperação demonstrada sustenta o próximo gate no Gateway, desde que autenticação, isolamento de sessão e TLS sejam adicionados sem expor a porta do modelo.

## Limitações

- Temperatura foi observável somente pelo usuário no HWiNFO externo; não existe dado térmico coletado pelo runner e nenhuma alegação térmica é feita.
- O modelo Q2_K foi escolhido pela margem de RAM; esta etapa não requalificou qualidade semântica além da qualificação preservada do Day 2.
- O Gateway usado no ensaio ficou apenas em loopback e HTTP local. HTTPS, pareamento de dispositivo e exposição LAN pertencem ao Day 4.
- As tentativas 1–5 registram evolução do fixture e da semântica de cancelamento; somente `attempt-6` é autoritativa.

## Itens ainda não validados

- autenticação e revogação de dispositivos reais;
- sessões e memória persistente isoladas por usuário;
- PWA em celular ou computador da LAN;
- certificado HTTPS e política de origem;
- operação prolongada sob múltiplos clientes autorizados;
- qualquer propriedade térmica.

## Evidência reproduzível

Os arquivos autoritativos estão em `evidence/family/day3/`. `final-receipt.json` agrega os números e hashes; `SHA256SUMS.txt` sela cada arquivo de evidência direto desse diretório. O runner reproduzível é `scripts/11-verify-family-day3.py`.
