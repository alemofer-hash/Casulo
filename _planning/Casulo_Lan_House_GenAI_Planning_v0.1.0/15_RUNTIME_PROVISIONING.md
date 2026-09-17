# Provisionamento do runtime local

Este procedimento ocorre depois do Stage Zero e da instalação da toolchain. Ele não deve ser executado cegamente sobre componentes já existentes: primeiro descubra se o diretório consolidado contém forks, patches ou bridges do Casulo.

## 1. Diretórios lógicos

```text
vendor/        fontes externas pinadas
runtime/       binários compilados
models/        pesos fora do Git
licenses/      licenças correspondentes
runtime-data/  memória, índices, receipts e logs
```

Esses nomes podem ser adaptados à estrutura canônica encontrada na auditoria.

## 2. llama.cpp

Fluxo obrigatório:

1. verificar se já existe cópia modificada;
2. registrar origem e commit;
3. construir baseline CPU;
4. testar binário e servidor somente em `127.0.0.1`;
5. construir backend Vulkan/OpenVINO/SYCL apenas se suportado;
6. comparar com o mesmo modelo, prompt e contexto;
7. congelar o vencedor por commit, flags e SHA-256.

Exemplo de build CPU com CMake/Ninja, a ser adaptado pelo Codex ao ambiente auditado:

```powershell
cmake -S .\vendor\llama.cpp -B .\build\llama-cpu -G Ninja `
  -DCMAKE_BUILD_TYPE=Release `
  -DGGML_NATIVE=ON
cmake --build .\build\llama-cpu --config Release
```

Exemplo de build Vulkan, somente após driver/SDK e `vulkaninfo` aprovados:

```powershell
cmake -S .\vendor\llama.cpp -B .\build\llama-vulkan -G Ninja `
  -DCMAKE_BUILD_TYPE=Release `
  -DGGML_VULKAN=ON
cmake --build .\build\llama-vulkan --config Release
```

O comando final do servidor deve conter binding explícito de loopback, modo offline após provisionamento, contexto medido e um único slot pesado. Não copie flags de versões diferentes sem consultar `--help` do binário congelado.

## 3. whisper.cpp e TTS

Antes de compilar novamente:

- localizar código e binários já validados;
- verificar hashes de `small-q5_1` e `base-q5_1`;
- localizar bridge MinGW e TTS Maria;
- reproduzir smoke existente;
- preservar perfil rápido e perfil de qualidade;
- isolar o defeito do smoke estrito de barge-in.

Se reconstrução for necessária, congelar commit, compilador, flags e hashes nos mesmos moldes do runtime LLM.

## 4. Modelos

Downloads são manuais e entram primeiro em quarentena. Para cada arquivo:

```powershell
Get-FileHash 'C:\caminho\modelo.gguf' -Algorithm SHA256
```

Preencher `manifests/model-registry.template.json`, salvar licença e executar a bateria definida em `09_MODEL_RUNTIME_POLICY.md`. Nunca permitir download automático durante uma conversa familiar.

## 5. Validação de binding

Depois de iniciar o runtime:

```powershell
Get-NetTCPConnection -State Listen |
  Where-Object LocalPort -in 8081,8082,8083,8084 |
  Select-Object LocalAddress,LocalPort,OwningProcess
```

Todos devem mostrar `127.0.0.1` ou equivalente loopback. `0.0.0.0`, `::` ou endereço LAN são bloqueadores de release.

## 6. Referências oficiais

- https://github.com/ggml-org/llama.cpp/blob/master/docs/build.md
- https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md
- https://github.com/ggml-org/whisper.cpp/blob/master/README.md

