# DEPENDÊNCIAS E ORÇAMENTO DE ARMAZENAMENTO

## 1. Regra geral

O repositório e seus locks são fonte de verdade. Antes de adicionar dependência:

1. inventariar o que já existe;
2. verificar licença e redistribuição;
3. pinar versão/commit e hash;
4. registrar em ledger e SBOM;
5. manter atrás de interface;
6. evitar dependência duplicada;
7. obter consentimento antes de download pesado.

Nenhuma API comercial de IA é permitida.

## 2. Toolchain

- toolchain Rust já adotada;
- LLVM/Clang/LLD;
- CMake/Ninja para runtimes C/C++;
- Python apenas onde já for referência/orquestração;
- QEMU x86-64;
- OVMF/EDK II;
- WHPX no Windows host;
- ferramentas de imagem QCOW2;
- ferramentas existentes de assinatura/SBOM;
- Whisper bridge já auditada para ASR pt-BR;
- runtime local de inferência atrás de FFI estreita.

Fontes primárias candidatas:

- llama.cpp: https://github.com/ggml-org/llama.cpp
- whisper.cpp: https://github.com/ggml-org/whisper.cpp
- QEMU: https://www.qemu.org/docs/master/
- UEFI: https://uefi.org/specs/

## 3. Modelo generativo local

Não fixar um modelo por popularidade ou memória do agente. O Sprint 1 produz uma shortlist usando:

- execução real na máquina detectada;
- licença compatível com uso owner e futuro serviço privado;
- model card e proveniência;
- suporte ao runtime pinado;
- qualidade pt-BR;
- capacidade de seguir schemas e gerar código;
- tamanho dentro de RAM e disco;
- contexto suficiente para CreationSpec/T;
- quantização identificada;
- ausência de obrigação de enviar dados externamente.

O modelo pode ser peso aberto/bootstrap local, mas o motor principal continua sendo a composição first-party `CasuloEngine + Memory + TForge + Verification + Relationship`. Nenhum fornecedor externo vira identidade do produto.

Antes de baixar pesos:

- mostrar nome, origem, licença, tamanho e espaço restante projetado;
- pedir consentimento explícito;
- baixar para staging;
- verificar hash;
- adotar transacionalmente;
- permitir remoção segura do modelo anterior apenas com autorização.

## 4. Sampling e runtime

O runtime precisa oferecer:

- streaming;
- cancelamento;
- KV cache quando suportado;
- sampling configurável;
- seed observável para diagnóstico;
- limites de contexto/memória;
- parser robusto de model files;
- nenhum shell textual no caminho de produção;
- processo isolado ou FFI limitada;
- timeout e circuit breaker.

## 5. Voz

Reutilizar o caminho pt-BR já comprovado quando íntegro:

- ASR local verificado;
- VAD/endpointing;
- TTS atual como voz provisória honesta;
- barge-in;
- fallback textual.

Não bloquear o motor generativo por clonagem ou voz definitiva. Não adotar engine/voz com licença incompatível apenas para melhorar estética nesta etapa.

## 6. VM

Baseline:

- QEMU + WHPX;
- máquina Q35;
- OVMF;
- imagem base read-only;
- overlay QCOW2 esparso;
- snapshots limitados;
- QMP local restrito;
- virtio quando suportado pelo guest.

Não criar cópias completas da imagem para cada teste. Usar base única + overlays e manifestar parent hash.

## 7. Orçamento para pouco mais de 80 GB livres

Orçamento de trabalho, não reserva pré-alocada:

| Componente | Faixa alvo |
|---|---:|
| código, toolchains e builds incrementais | 10–15 GiB |
| modelo generativo owner | 4–12 GiB |
| ASR/TTS/embeddings | 2–5 GiB |
| imagem VM base esparsa | 8–16 GiB aparentes, menos fisicamente quando vazia |
| overlay, snapshots e feedback | até 12 GiB |
| caches/staging temporário | até 8 GiB |
| reserva operacional intocável | 20 GiB |

Regras automáticas:

- `doctor` mede espaço antes de build/model/VM;
- tarefa pesada não começa se projetar menos de 20 GiB livres ao final;
- snapshots têm quota e política de retenção;
- staging incompleto é identificável e removível;
- limpeza informa targets exatos e nunca toca Casulo/Jaderson por colisão;
- nenhuma remoção material sem autorização;
- não duplicar pesos entre host e guest quando um blob store verificado puder ser usado com isolamento.

## 8. Gate futuro de mídia externa

Esta etapa não usa mídia externa. O próximo GOAL só poderá habilitar operações quando:

```text
external_target_explicitly_selected == true
external_target_is_removable == true
external_target_is_not_internal_system_disk == true
external_usable_capacity_gib > 80
owner_confirmed_exact_device == true
```

`80 GiB` exatos falham o gate; a condição é estritamente maior que 80 GiB.

