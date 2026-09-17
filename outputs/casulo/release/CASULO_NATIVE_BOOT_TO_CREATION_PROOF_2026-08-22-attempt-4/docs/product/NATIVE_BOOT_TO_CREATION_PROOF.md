# Casulo Native — boot até criação verificável

Estado técnico: `CASULO_NATIVE_BOOT_TO_CREATION_PROOF`  
Data do selo: 2026-08-22  
Assinatura: `DEVELOPMENT_SIGNATURE_NOT_COMMERCIAL_RELEASE`

## Resultado

O kernel Casulo iniciou por UEFI em QEMU/WHPX, sem Linux ou Windows dentro do
guest, carregou localmente o Qwen3-4B Q4_K_M owner, executou inferência
autorregressiva de 34 tokens, publicou cada token somente após a política T,
construiu uma especificação de criação, compilou e executou um artefato T,
simulou-o, julgou sua aceitação por outra política T e materializou uma forma na
superfície Stark + Jobs.

Pedido congelado em linguagem natural:

```text
Crie uma funcao simples que some dois numeros e retorne o resultado.
```

Saída do modelo, idêntica ao oráculo host independente:

```text
NOME=SomeDoisNumeros;FUNCAO=SomeDoisNumeros;ENTRADA=numero1,numero2;SAIDA=resultado.
```

O programa T gerado foi compilado pelo pipeline geral já validado, recebeu 7 e
11, retornou 18, passou na simulação sem efeitos e somente então foi aceito.

## Cadeia real

```text
UEFI -> kernel Casulo -> modelo Qwen3 owner read-only
     -> tokenizer/prompt congelados -> 36 blocos por posição -> logits
     -> greedy debug -> política T por token -> streaming
     -> CreationSpec validada -> fonte T -> TCAP content-addressed
     -> execução em ring 3 -> simulação -> juiz T
     -> materialização -> cena Stark + Jobs
```

O modelo propõe conteúdo. T e os componentes determinísticos decidem
publicação, contrato, compilação e aceitação. O GGUF, os pesos Qwen3 e o formato
Transformer permanecem bootstrap estrangeiro manifestado; o kernel, transporte,
runtime `no_std`, políticas, receipts, criação e renderer são Casulo.

## Prova positiva

Três boots independentes passaram com a mesma imagem e os mesmos 34 IDs. O
tempo completo observado foi 410,752 s, 381,087 s e 547,131 s; são observações
funcionais, não benchmark de desempenho. Cada boot contabilizou:

- 83 posições efetivamente executadas;
- 2.988 blocos Transformer;
- 20.999 matvecs;
- 1.304.096.000 blocos quantizados;
- 333.848.576.000 multiplicações-acumulações lógicas;
- 206.714.780.160 bytes lógicos de pesos lidos ao longo das chamadas;
- 29.202.944 bytes de arena de criação;
- 2.497.280.256 bytes da fonte do modelo carregados;
- 34 receipts de publicação encadeados por SHA-256;
- resultado T 18, simulação PASS e aceitação PASS.

Hashes principais:

| Objeto | SHA-256 |
| --- | --- |
| Imagem Native | `25193857a96d6c14328d92fb128d6e666a31478dee05cc8cca6a35252932a534` |
| Qwen3-4B-Q4_K_M | `7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5` |
| System pack | `4f5e9fb34de09a3fe59b49c233802312a1c2e4d86ec7d00ca2d1dc1638f7eeb1` |
| Política T de token | `394e70542844f1c1bcfbbd73df41e223f6a1d5a7b1f613a636fa9b72d907b60e` |
| Política T de artefato | `4544901e4dfc9bc996f28356a62093f5e475e6ed16d031b2602b092b9ee907e7` |
| Política T de aceitação | `88a84acf9f864c7144b5203c977ee356680837c960541148590f52a175ddf8eb` |
| Fonte T gerada/compilada | `cc120e8f626c222674f8d950027f2265a05a59bd2167689bc746273f557ea0b3` |
| Materialização | `e9442e34f04d7498de01d277d5465671128bcc9811ecebe45cee809a365c2ef4` |
| Cauda dos receipts de token | `84723086bc187d40479ec5ad631859fc662bc966841d9edc1a1d7806b1b411cf` |
| Receipt de aceitação | `88160a9262dbe82ed912508cd9ab3a0edb1091b089783bab476e9cf761a89fb1` |

## Prova de cancelamento

Um quarto boot publicou somente o primeiro token (`N`) e recebeu cancelamento
na fronteira seguinte. O kernel registrou `CANCELLED_CLEAN`, rejeitou saída
tardia, não publicou CreationSpec, não compilou, não simulou, não materializou e
manteve hashes de modelo e imagem intactos. O boot passou em 486,235 s.

## Como inspecionar

Pré-requisitos locais já adotados:

- Windows bare-metal com WHPX;
- QEMU owner detectável pelo Machine Profile;
- modelo no cache owner com tamanho e SHA-256 exatos;
- aproximadamente 6 GiB de RAM disponível para a VM.

Por PowerShell, na raiz do repositório:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File release/CASULO_NATIVE_BOOT_TO_CREATION_PROOF.ps1
```

Ou dê duplo clique em:

```text
release\START_CASULO_NATIVE_CREATION_PROOF.vbs
```

O launcher valida hashes antes do boot, usa `shell=False`, desliga rede do guest,
anexa apenas arquivos regulares allowlisted e read-only, abre a janela QEMU e
grava serial append-only em `%LOCALAPPDATA%\Casulo\native-creation-proof`. A
janela se encerra após o gate. `Ctrl+C` é encaminhado como cancelamento seguro.

## O que esta prova não é

- não é ainda uma conversa aberta e veloz;
- não aceita prompt arbitrário nesta imagem: pedido, contexto e greedy debug
  estão congelados para falsificabilidade;
- não possui sampling estocástico, contexto longo, memória persistente ou voz;
- não usa GPU/TPU e não demonstra controle Native desses dispositivos;
- `fw_cfg` é transporte de qualificação em QEMU, não driver físico final;
- o modelo completo cabe na RAM configurada; ainda não prova o método
  FROZEN/WARM/HOT aplicado aos pesos do Transformer;
- Stark + Jobs nesta prova é a cena Native mínima, não o design final;
- não mede performance, energia, compressão física ou superioridade;
- não é release comercial nem autoriza publicação, Cloud ou USB.

## Fronteiras preservadas

`Cloud=RELEASE_LOCKED`, `guest_network=OFF`, `USB/block_devices=PROHIBITED`,
`external_API=NONE`, `scientific_benchmark=NOT_STARTED`. Nenhum dispositivo
físico foi escrito. A próxima etapa de mídia externa depende de autorização
literal e identificação inequívoca do dispositivo.
