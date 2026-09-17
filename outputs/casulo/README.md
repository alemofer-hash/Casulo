# Casulo

## Casulo Native: boot até criação

O vertical slice Native selado inicia o kernel Casulo sem Linux no guest,
executa localmente uma criação neural Qwen3-4B congelada, aplica políticas T por
token e por artefato, compila/simula/materializa o resultado e demonstra
cancelamento fail-closed. Ele é uma prova funcional deliberadamente estreita e
ainda lenta, não o produto conversacional final.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File release/CASULO_NATIVE_BOOT_TO_CREATION_PROOF.ps1
```

Detalhes e limites: [docs/product/NATIVE_BOOT_TO_CREATION_PROOF.md](docs/product/NATIVE_BOOT_TO_CREATION_PROOF.md).

## Semantic Multiverse owner

A primeira versao inspecionavel preserva o G10 e acrescenta universos
semanticos content-addressed com lifecycle FROZEN/WARM/HOT, transicoes T de
estado suficiente e receipts reais. Para verificar e iniciar:

```powershell
python tools/casulo_semantic_multiverse.py doctor --repo .
powershell -NoProfile -ExecutionPolicy Bypass -File release/CASULO_SEMANTIC_MULTIVERSE_VM_INSPECT.ps1
```

O runbook completo esta em
[docs/product/SEMANTIC_MULTIVERSE_VM_HANDOFF.md](docs/product/SEMANTIC_MULTIVERSE_VM_HANDOFF.md).
Cloud permanece `RELEASE_LOCKED`; USB, QPU e block devices permanecem negados.

> **Direção de produto ativa (2026-08-11):** o Casulo está sendo transformado
> em um ambiente cognitivo voice-first, com memória orgânica, intenção
> incremental, simulação segura e materialização portátil. A pesquisa histórica
> de desempenho foi preservada, mas não é gate, promessa comercial nem caminho
> padrão de desenvolvimento. Consulte
> [docs/product/EXECUTION_STATE.md](docs/product/EXECUTION_STATE.md).

## Perfis e edições

- `casulo-owner`: build privado de Guilherme Moura Fernandes, com
  `OwnerEngineAdapter` direto e sem cota comercial;
- `casulo-public`: build distribuível que contém apenas `CloudEngineClient` e,
  durante o desenvolvimento, conversa somente com `CloudTestHarness`;
- `casulo-cloud-standby`: infraestrutura first-party compilável e testável,
  sempre `RELEASE_LOCKED` até decisão explícita futura.

Os builds são mutuamente exclusivos. Nome, e-mail, hostname ou flag escondida
no cliente nunca concedem privilégios owner.

Casulo é um invento original da **Teloscorp** para **Otimização de Tráfego de
Informação**.

Ele recebe uma fonte integral, reconhece sua estrutura, mede o atrito da
travessia, escolhe um tratamento, reorganiza o conteúdo sem descarte silencioso
e libera uma **Borboleta**: a informação completa, mais navegável, enriquecida
e acompanhada por prova de conservação.

## A evolução

```text
Egg
  → Larva
    → Crisálida
      → Metamorfose
        → Borboleta
```

- **Egg**: fonte original, imutável e identificada por hash.
- **Larva**: conteúdo ingerido, inventariado e perfilado.
- **Crisálida**: decisão e plano de tratamento.
- **Metamorfose**: reorganização conservativa e enriquecimentos.
- **Borboleta**: pacote integral otimizado e verificável.

O **Casulo** é o orquestrador de todas as fases.

## Compressão estrutural sem perda — experimental

O caminho v1 separa explicitamente `base + dynamics + residual`, analisa
ISO BMFF/HEVC, executa transforms reversíveis sob autoridade causal T e exige
reconstrução por um decoder independente:

```powershell
casulo-compress structural-analyze <video.mp4>
casulo-compress structural-probe <video.mp4> <diretorio-append-only>
casulo-compress structural-pack <video.mp4> <arquivo.zip> --evidence-dir <evidencia>
casulo-compress structural-verify <arquivo.zip>
casulo-compress structural-unpack <arquivo.zip> <restaurado.mp4>
casulo-compress gop-analyze <video.mp4>
casulo-compress gop-probe <video.mp4> <diretorio-append-only>
casulo-compress gop-verify <arquivo.casulo-gop.zip>
casulo-compress gop-unpack <arquivo.casulo-gop.zip> <corpus-restaurado.bin>
```

O probe atual prova a execução da arquitetura, não vantagem de compressão. O
resultado líquido observado foi expansão tanto no caminho estrutural quanto na
extensão GOP/NAL e permanece preservado em
[STRUCTURAL_COMPRESSION_IMPLEMENTATION_2026-09-09.md](docs/product/STRUCTURAL_COMPRESSION_IMPLEMENTATION_2026-09-09.md)
e [HEVC_GOP_IMPLEMENTATION_2026-09-10.md](docs/product/HEVC_GOP_IMPLEMENTATION_2026-09-10.md).

### CASV — formato visual causal próprio

O caminho novo não tenta colocar outro compressor em torno do HEVC. Ele compila
mídia canônica para um arquivo `.casv` contendo `base + aparência + dinâmica +
residual`, executado por renderer determinístico e reconstruído por decoder
independente:

```powershell
casulo-compress casv-pack frames.rgb video.casv --width 96 --height 54 --frames 24 --fps-numerator 24 --evidence-dir evidencia
casulo-compress casv-verify video.casv
casulo-compress casv-unpack video.casv frames-restaurados.rgb
casulo-compress casv-probe C:\CasuloLab\campaigns\novo-probe-append-only
casulo-compress casv-import fonte.mp4 recorte.casv --frames 2 --crop 0 0 256 144 --evidence-dir evidencia
casulo-compress casv-import fonte.mp4 recorte-10bit.casv --frames 2 --crop 0 0 256 144 --preserve-source-pixel-format --evidence-dir evidencia-10bit
casulo-compress casv-play recorte.casv
casulo-compress casv-stream-pack frames.rgb video-v02.casv --width 1920 --height 1080 --frames 60 --fps-numerator 30 --pixel-format RGB8 --segment-kib 8192 --evidence-dir evidencia-v02
casulo-compress casv-stream-inspect video-v02.casv
casulo-compress casv-stream-verify video-v02.casv
casulo-compress casv-stream-unpack video-v02.casv frames-restaurados.rgb
casulo-compress casv-stream-extract video-v02.casv trecho.rgb --start-frame 20 --frames 10
casulo-compress casv-stream-probe C:\CasuloLab\campaigns\novo-probe-stream-append-only
casulo-compress casv-stream-import fonte.mp4 video-v02.casv --frames 60 --segment-kib 8192 --max-canonical-mib 1024 --evidence-dir evidencia-v02
casulo-compress casv-program-pack frames.yuv video-v03.casv --width 256 --height 144 --frames 8 --fps-numerator 60000 --fps-denominator 1001 --pixel-format YUV444P10LE --frames-per-segment 8 --evidence-dir evidencia-v03
casulo-compress casv-program-inspect video-v03.casv
casulo-compress casv-program-verify video-v03.casv
casulo-compress casv-program-unpack video-v03.casv frames-restaurados.yuv
casulo-compress casv-program-extract video-v03.casv trecho.yuv --start-frame 2 --frames 2
casulo-compress casv-program-import fonte.mp4 video-v03.casv --frames 8 --crop 0 0 256 144 --preserve-source-pixel-format --frames-per-segment 8 --max-canonical-mib 4 --evidence-dir evidencia-v03
casulo-compress casv-program-probe C:\CasuloLab\campaigns\novo-probe-programa-append-only
casulo-compress casv-tiled-pack frames.yuv video-v04.casv --width 256 --height 144 --frames 2 --fps-numerator 60000 --fps-denominator 1001 --pixel-format YUV444P10LE --tile-width 64 --strip-height 48 --evidence-dir evidencia-v04
casulo-compress casv-tiled-inspect video-v04.casv
casulo-compress casv-tiled-verify video-v04.casv
casulo-compress casv-tiled-unpack video-v04.casv frames-restaurados.yuv
casulo-compress casv-tiled-import fonte.mp4 video-v04.casv --frames 2 --crop 0 0 256 144 --preserve-source-pixel-format --tile-width 64 --strip-height 48 --max-canonical-mib 4 --evidence-dir evidencia-v04
casulo-compress casv-tiled-probe C:\CasuloLab\campaigns\novo-probe-tiled-append-only
casulo-compress casv-compact-pack frames.yuv video-v05.casv --width 256 --height 144 --frames 2 --fps-numerator 60000 --fps-denominator 1001 --pixel-format YUV444P10LE --tile-width 64 --strip-height 48 --evidence-dir evidencia-v05
casulo-compress casv-compact-inspect video-v05.casv
casulo-compress casv-compact-verify video-v05.casv
casulo-compress casv-compact-unpack video-v05.casv frames-restaurados.yuv
casulo-compress casv-compact-import fonte.mp4 video-v05.casv --frames 2 --crop 0 0 256 144 --preserve-source-pixel-format --tile-width 64 --strip-height 48 --max-canonical-mib 4 --evidence-dir evidencia-v05
casulo-compress casv-compact-probe C:\CasuloLab\campaigns\novo-probe-compacto-append-only
casulo-compress casv-temporal-pack frames.yuv video-v06.casv --width 256 --height 144 --frames 8 --fps-numerator 60000 --fps-denominator 1001 --pixel-format YUV444P10LE --tile-width 64 --strip-height 48 --keyframe-interval 8 --evidence-dir evidencia-v06
casulo-compress casv-temporal-inspect video-v06.casv
casulo-compress casv-temporal-verify video-v06.casv
casulo-compress casv-temporal-unpack video-v06.casv frames-restaurados.yuv
casulo-compress casv-temporal-import fonte.mp4 video-v06.casv --frames 8 --crop 0 0 256 144 --preserve-source-pixel-format --tile-width 64 --strip-height 48 --keyframe-interval 8 --max-canonical-mib 4 --evidence-dir evidencia-v06
casulo-compress casv-temporal-probe C:\CasuloLab\campaigns\novo-probe-temporal-append-only
```

O corte `CASV/0.1` é bounded e aceita RGB8 e `YUV444P10LE`. O `CASV/0.2`
acrescenta container forward-only, segmentos independentes, decoder incremental
com memória limitada, extração seletiva, importação direta de FFmpeg stdout e
player por pipe sem mídia temporária. O `CASV/0.3` integra por segmento um
programa nativo RGB8/YUV10 `base + dinâmica + residual`, oferece os três
candidatos reais a T e mantém reconstrução independente. Em dois probes curtos
derivados da fonte 8K, o payload causal foi 1,39% e 1,57% menor que zlib no
mesmo bloco; menos de 0,8% dos pixels foram previstos exatamente e o custo de
encode permaneceu alto. Isso é um sinal de engenharia delimitado, não prova de
compressão de vídeo natural, 8K integral ou vantagem sobre HEVC. Nenhuma versão
inclui áudio; o contrato PCM futuro existe separadamente.

O `CASV/0.4` substitui frame inteiro por faixas e tiles bounded e oferece a T
quatro candidatos reversíveis por tile. No crop natural medido, o payload dos
tiles ficou 11,845% e o record stream 9,190% menores que zlib global, mas o
manifesto de 16.271 bytes inverteu o resultado: o archive final ficou 8,017%
maior. Isso valida tiling e o sinal do preditor, não uma vitória de compressão.
O layout 8K foi validado aritmeticamente; o encode 8K integral não foi feito.
O `CASV/0.5` troca o manifesto embutido por um índice binário compacto e faz T
julgar o arquivo inteiro contra zlib antes de publicá-lo. No mesmo crop real de
dois quadros, o archive caiu para 84.958 bytes contra 94.890 do zlib global:
10,4669% menor, com SHA-256 canônico idêntico. Os artifacts forenses externos
não entram no playback e foram reportados separadamente; archive mais auditoria
ainda perde para zlib. Trata-se de um único recorte real, não de vantagem contra
HEVC, vídeo natural como classe ou 8K integral.

O `CASV/0.6` acrescenta predição temporal XOR/subtração contra o tile homólogo
do quadro anterior, com keyframes e spool limitado. A rota temporal e a
causalidade T passaram no controle sintético, mas a hipótese falhou no clip
natural de oito quadros: nenhuma das 252 oportunidades temporais foi escolhida.
O archive de 326.603 bytes venceu zlib em 10,1626%, porém perdeu para zstd,
x265 lossless e FFV1; contra FFV1 foi 66,9971% maior. O resultado negativo é a
base preservada. O `CASV/0.7` executou a compensação de movimento reversível
seguinte e incluiu cada vetor no custo: o mecanismo passou no sintético, mas
selecionou zero vetores em três holdouts naturais. As razões contra FFV1 foram
1,712257, 1,739936 e 1,783692. O ramo translacional foi, portanto, rejeitado e
a fronteira seguinte é uma gramática visual causal — não uma alegação de codec
competitivo.

Consulte
[CASULO_CAUSAL_VISUAL_FORMAT_0_1.md](docs/spec/CASULO_CAUSAL_VISUAL_FORMAT_0_1.md),
[CASULO_CAUSAL_VISUAL_FORMAT_0_2.md](docs/spec/CASULO_CAUSAL_VISUAL_FORMAT_0_2.md),
[CASULO_CAUSAL_VISUAL_FORMAT_0_3.md](docs/spec/CASULO_CAUSAL_VISUAL_FORMAT_0_3.md),
[CASULO_CAUSAL_VISUAL_FORMAT_0_4.md](docs/spec/CASULO_CAUSAL_VISUAL_FORMAT_0_4.md),
[CASULO_CAUSAL_VISUAL_FORMAT_0_5.md](docs/spec/CASULO_CAUSAL_VISUAL_FORMAT_0_5.md),
[CASULO_CAUSAL_VISUAL_FORMAT_0_6.md](docs/spec/CASULO_CAUSAL_VISUAL_FORMAT_0_6.md),
[CASULO_CAUSAL_VISUAL_FORMAT_0_7.md](docs/spec/CASULO_CAUSAL_VISUAL_FORMAT_0_7.md),
[CASV_CV1_4_PROGRAM_STREAM_2026-09-10.md](docs/product/CASV_CV1_4_PROGRAM_STREAM_2026-09-10.md),
[CASV_CV1_5_SPATIAL_TILING_2026-09-10.md](docs/product/CASV_CV1_5_SPATIAL_TILING_2026-09-10.md),
[CASV_CV1_6_COMPACT_INDEX_2026-09-10.md](docs/product/CASV_CV1_6_COMPACT_INDEX_2026-09-10.md),
[CASV_CV1_7_TEMPORAL_2026-09-10.md](docs/product/CASV_CV1_7_TEMPORAL_2026-09-10.md)
e [CASV_CV1_8_MOTION_2026-09-11.md](docs/product/CASV_CV1_8_MOTION_2026-09-11.md).

## Lei do invento

Todo conteúdo recebido precisa aparecer:

1. no conteúdo integral reorganizado; ou
2. na quarentena, com motivo explícito.

O contador `descartes_silenciosos` precisa ser sempre zero.

## Uso Python

```python
from casulo import Casulo

borboleta = Casulo().evoluir(
    "entrada.csv",
    destino="saida-casulo",
)

print(borboleta.prova_conservacao)
```

## Linha de comando

```powershell
python -m casulo entrada.csv --destino saida-casulo
```

Um perfil opcional em JSON pode definir campos esperados, aliases, campo
temporal e volume de referência:

```json
{
  "nome": "operacao",
  "campos_esperados": ["timestamp", "origem", "valor"],
  "aliases": {
    "data_hora": "timestamp"
  },
  "campo_temporal": "timestamp",
  "volume_referencia_bytes": 100000
}
```

```powershell
python -m casulo entrada.csv --destino saida --perfil perfil.json
```

## Pacote liberado

```text
saida/
├─ 00_egg/
│  └─ fonte_original.*
├─ 01_larva/
│  └─ inventario.json
├─ 02_crisalida/
│  └─ plano_de_evolucao.json
├─ 03_metamorfose/
│  ├─ conteudo_integral.jsonl
│  ├─ quarentena.jsonl
│  └─ enriquecimentos.json
├─ 04_borboleta/
│  ├─ indice.json
│  └─ prova_de_conservacao.json
├─ MARCA_E_AUTORIA.txt
└─ manifesto.json
```

## Formatos iniciais

- CSV/TSV e outros delimitadores comuns;
- JSON;
- texto linha a linha;
- XLSX quando `openpyxl` estiver instalado.

Formatos não compreendidos continuam fisicamente preservados no Egg e são
liberados na quarentena, nunca descartados.

## Validação

```powershell
python -m pytest -q tests/product tests/test_casulo.py tests/test_t_frontend.py tests/test_t_semantics_ir.py tests/test_t_workspace.py tests/test_t_tcap.py tests/test_t_metamorphosis.py::TMetamorfoseGraphTests
```

Esse é o gate curto de produto e correção do compilador. Ferramentas científicas
permanecem arquivadas e exigem opt-in deliberado
`CASULO_ENABLE_LEGACY_RESEARCH=1`; elas não rodam no CI ou release padrão.

## Linguagem T — implementação histórica preservada

O compilador aberto da linguagem T agora vive no próprio repositório, sem
depender de um backend escondido em executável.

```powershell
python -m pip install -e ".[parity]"
t doctor
t pytorch-doctor
t pytorch-doctor --compile
t check examples/t/balanco_hidrico.t
t inspect examples/t/balanco_hidrico.t
t inspect examples/t/balanco_hidrico.t --symbols
t inspect examples/t/balanco_hidrico.t --ir
t inspect examples/t/balanco_hidrico.t --graph
t build examples/t/balanco_hidrico.t --output build/balanco
t build examples/t/balanco_hidrico.t --output build/balanco --native
t run build/balanco --input examples/t/hydrocell.json
t run build/balanco --input benchmarks/data/water-balance-f64.json --native
t run build/balanco --input examples/t/hydrocell_batch.json --batch
t run build/balanco --input examples/t/hydrocell_batch.json --adaptive
t benchmark build/balanco --input examples/t/hydrocell_batch.json --repeat 1000
t native-benchmark build/balanco --input benchmarks/data/water-balance-f64.json --repeat 2000
t simd-benchmark build/balanco --input benchmarks/data/water-balance-f64.json --repeat 2000
t training-experiment examples/t/flood_surrogate_training.t --output build/training-proof --workers auto
t tensor-compile examples/tensor/mlp-forward.tensor.json
t autograd-compile examples/tensor/linear-mse-training.tensor.json --wrt weight
t autograd-check examples/tensor/linear-mse-training.tensor.json --input examples/tensor/linear-mse-input.json --wrt weight
t numpy-execute examples/tensor/linear-mse-training.tensor.json --input examples/tensor/linear-mse-input.json --wrt weight
t pytorch-parity examples/tensor/linear-mse-training.tensor.json --input examples/tensor/linear-mse-input.json --wrt weight
t tensor-cpu-plan examples/tensor/linear-mse-training.tensor.json --wrt weight --workers auto
t tensor-cpu-run examples/tensor/linear-mse-training.tensor.json --input examples/tensor/linear-mse-input.json --wrt weight --workers auto
t tensor-cpu-plan examples/tensor/mlp-mse-medium.tensor.json --wrt weight1 weight2 --workers 4 --gemm-workers 1 --provider openblas
t tensor-causal-profile examples/tensor/mlp-mse-medium.tensor.json --output build/causal-profile --wrt weight1 weight2 --workers 4 --gemm-workers 1 --provider openblas
t tensor-lab-preregister examples/tensor/mlp-mse-scientific.tensor.json --output evidence/tensor-lab/preregistration.json --wrt weight1 weight2 --workers 4 --target-sample-ms 250 --cpu-affinity 0 1 2 3 --max-cv 0.15
t tensor-lab-run examples/tensor/mlp-mse-scientific.tensor.json --preregistration evidence/tensor-lab/preregistration.json --output benchmarks/results/tensor-lab
t tensor-lab-judge --preregistration evidence/tensor-lab/preregistration.json --report benchmarks/results/tensor-lab/tensor-lab-report.json --output evidence/tensor-lab/verdict.json
t tensor-suite-preregister examples/tensor-suite/cases.json --output evidence/tensor-suite --workers 4 --gemm-workers 1 --provider openblas --prior-exploratory-disclosure "MLP médio observado; estes shapes ainda não foram cronometrados."
t tensor-suite-run examples/tensor-suite/cases.json --preregistration evidence/tensor-suite/suite-preregistration.json --output benchmarks/results/tensor-suite
t tensor-suite-judge --preregistration evidence/tensor-suite/suite-preregistration.json --report benchmarks/results/tensor-suite/suite-report.json --output evidence/tensor-suite/suite-verdict.json
t check examples/t-project-training
t build examples/t-project-training
t experiment examples/t/balanco_hidrico.t --output build/borboleta
```

Em Windows com várias instalações de Python, confirme `where.exe t`. Se o
primeiro launcher apontar para outro ambiente, use
`python -m casulo.t.cli <comando>` no Python em que `casulo`, NumPy e PyTorch
foram instalados.

O compilador aberto contém:

- `EggLexer`: linhas, comentários, indentação e localização;
- `EggParser`: AST do núcleo T 1.0;
- `LarvaAnalyzer`: primeiro gate semântico;
- `LarvaTensor`: shape, dtype, device, layout, ownership e aliasing verificáveis;
- ABI tensorial declarativa e registro versionado de operadores;
- Álgebra Linear Casulo/T com planejamento por trânsito, kernels identificados
  e auditoria estrutural;
- provedor GEMM próprio ou OpenBLAS ILP64 externo, sempre identificado por
  versão, símbolos e SHA-256;
- orçamento auditável de workers totais e threads internas do GEMM;
- `CrisálidaTensorIR` com nomes SSA e plano estático de memória;
- `MetamorfoseAutogradIR` com backward e acumulação explícitos;
- gradient check central por diferenças finitas e orçamento de trabalho;
- executor NumPy público para forward e backward;
- adaptador PyTorch CPU e paridade de intermediários, loss e gradientes;
- backend CPU tensorial C99/OpenMP para forward e backward;
- fusão ponto a ponto, arena por tempo de vida e scheduler limitado;
- julgamento nativo contra NumPy e PyTorch antes de qualquer aprovação;
- fallback explícito quando shape, operador, arena ou toolchain não são válidos;
- laboratório tensorial pré-registrado contra PyTorch eager e Inductor;
- seis ordens balanceadas, amostras pareadas e juiz independente;
- suíte confirmatória multi-caso, reinícios em processos novos e decisão
  agregada por unanimidade;
- tabela de símbolos com escopos;
- inferência e verificação de tipos;
- análise de emissão em todos os caminhos;
- `CrisálidaIR`: representação intermediária textual e JSON;
- backend Python de referência autocontido;
- grafo def-use da Metamorfose;
- classificação de determinismo, efeitos e custo;
- kernel de lote fundido;
- memoização por operação e deduplicação dentro do lote;
- benchmark escalar versus lote com prova de equivalência;
- laboratório Borboleta com dataset determinístico e amostras brutas;
- intervalo de confiança por bootstrap e ordem de execução alternada;
- telemetria de tempo, CPU, memória e energia elétrica detectável;
- relatório científico JSON e HTML autocontido;
- seletor adaptativo com perfil Larva e decisão Crisálida;
- escolha auditável entre recalcular e deduplicar;
- orçamento explícito de memória para cache;
- artefato reproduzível com fonte, IR, executável e manifesto;
- cache endereçado por conteúdo;
- executor com validação da entrada e da integridade do artefato;
- chave estrutural tipada especializada por operação;
- cache intralote com colisão verificada e vida útil explícita;
- buffers colunares `float64`/`int64` com evidência lateral;
- manifestação tardia com fallback conservativo para objetos;
- ABI `casulo-native-abi/0.1` com layout colunar `float64`;
- backend `c99-simd/0.3`, compilação AOT e DLL/SO endereçada por conteúdo;
- remoção de código morto e propagação segura de constantes e aliases;
- arena colunar reutilizável com capacidade em potência de dois;
- validação e marshal fundidos e especializados por esquema;
- manifestação de fronteira especializada por operação;
- benchmark com marshal, kernel e manifestação medidos separadamente;
- IC95% pareado do ganho por bootstrap;
- separação conservativa entre fase de guardas e laço numérico;
- perfil escalar estrito de controle e perfil SIMD específico da máquina;
- relatório de vetorização preservado na proveniência da build;
- fallback Python explícito para tipo, forma ou compilador incompatível;
- prova de equivalência Python escalar versus C99 nativo;
- diagnósticos estruturados, com código e posição;
- corpus golden de conformidade;
- workspace multifile com manifesto, lockfile, dependências e entrypoint;
- `t init`, `t check`, `t inspect`, `t build`, `t run`, `t test`, `t benchmark`,
  `t native-benchmark`, `t simd-benchmark`, `t training-experiment`,
  `t tensor-cpu-plan`, `t tensor-cpu-run`, `t tensor-lab-preregister`,
  `t tensor-lab-run`, `t tensor-lab-judge`, `t tensor-lab-verify`,
  `t experiment` e `t doctor`.

## Projetos T

Uma pasta com `casulo.toml` é uma unidade reproduzível de compilação:

```console
t init traffic-lab
t check traffic-lab
t build traffic-lab
t run traffic-lab --operation Main
t test traffic-lab
```

O compilador descobre `src/**/*.t`, resolve `use`, bloqueia ciclos e módulos
ausentes, determina uma ordem topológica e materializa todos os artefatos sob
uma única identidade. Um entrypoint `training` também pode ser entregue
diretamente ao laboratório:

```console
t training-experiment examples/t-project-training \
  --output build/project-training
```

O protocolo está em [docs/workspace-0.1.md](docs/workspace-0.1.md).

## Treinamento científico

A extensão `learn` descreve uma rede compacta e permite que o compilador funda
forward, backward, redução e SGD em C99/OpenMP:

```console
python -m pip install -e ".[ml]"
t training-experiment examples/t/flood_surrogate_training.t \
  --output build/training-proof \
  --workers auto \
  --samples 21
```

Contra PyTorch eager CPU com MKL/oneDNN e AVX2, a prova oficial atingiu
`9,743×`, com IC95% `9,217×–10,528×`, R² de validação `0,9568` e equivalência
numérica. Três replicações oficiais mantiveram o limite inferior acima de
`7,808×`.

Esse resultado vale para a MLP hidrológica declarada, em memória e no hardware
medido. Não é uma alegação sobre qualquer rede, GPU ou carga de treinamento.

O protocolo está em
[docs/training-benchmark-0.1.md](docs/training-benchmark-0.1.md), e o resultado
visual em
[benchmarks/results/2026-07-30-sprint012-training-proof/training-report.html](benchmarks/results/2026-07-30-sprint012-training-proof/training-report.html).
Todo o pacote pode ser rechecado sem dependências externas:

```console
python tools/verify_training_evidence.py
```

## Pacto científico

A partir da versão `0.13`, medições exploratórias continuam possíveis, mas não
podem liberar alegações públicas. Para isso, hipótese, desenho, baselines e
gates precisam ser selados antes da execução:

```console
t scientific-preregister examples/t/flood_surrogate_training.t \
  --output evidence/preregistration.json \
  --baseline pytorch-eager-cpu \
  --baseline pytorch-compile-inductor-cpu
```

O juiz independente pode responder `POSITIVE`, `NULL`, `NEGATIVE`,
`INCONCLUSIVE` ou `INVALID`. Ele recalcula as métricas e não possui função para
alterar ou otimizar o experimento.

A primeira aplicação obteve `8,958×` contra PyTorch eager, mas recebeu veredito
geral `INCONCLUSIVE`, porque `torch.compile` era obrigatório e não pôde ser
executado sem `cl.exe`. A falha foi preservada, não omitida.

O protocolo completo está em
[docs/scientific-covenant-1.0.md](docs/scientific-covenant-1.0.md).

O envelope de execução preserva integralmente a entrada, manifesta o resultado
e registra julgamentos, restrições, projeções, vínculos e estabilizações.

```text
build/balanco/
├─ source.t
├─ crisalida.ir.json
├─ metamorfose.graph.json
├─ casulo_artifact.py
├─ casulo_native.c
├─ casulo_native.abi.json
└─ manifest.json
```

O módulo gerado usa apenas a biblioteca padrão do Python e pode ser executado
fora da IDE. A fonte C99 também é portátil; o binário nativo é um derivado
reproduzível por plataforma e compilador, armazenado fora do artefato assinado.

O núcleo continua sem dependências obrigatórias. Para instalar o laboratório
científico e as ferramentas de desenvolvimento:

```console
python -m pip install -e ".[science,dev]"
```

A Borboleta chama energia de joules somente quando encontra um contador
elétrico cumulativo. Na ausência dele, publica `not_measured` e conserva tempo
de CPU apenas como proxy de trabalho computacional.

A especificação está em [docs/t-spec-1.0.md](docs/t-spec-1.0.md).
A IR está documentada em
[docs/crisalida-ir-0.1.md](docs/crisalida-ir-0.1.md).
O artefato está documentado em
[docs/python-backend-0.4.md](docs/python-backend-0.4.md).
O protocolo de buffers está em
[docs/typed-buffer-0.1.md](docs/typed-buffer-0.1.md).
A ABI nativa está em
[docs/native-abi-0.1.md](docs/native-abi-0.1.md).
O AOT e a arena estão em
[docs/aot-arena-0.1.md](docs/aot-arena-0.1.md).
O perfil SIMD está em
[docs/simd-0.1.md](docs/simd-0.1.md).
O grafo está documentado em
[docs/metamorfose-graph-0.1.md](docs/metamorfose-graph-0.1.md).
O protocolo de desempenho está em
[docs/benchmark-metamorfose-0.1.md](docs/benchmark-metamorfose-0.1.md).
O protocolo Borboleta está em
[docs/borboleta-protocol-0.4.md](docs/borboleta-protocol-0.4.md).
O seletor adaptativo está em
[docs/adaptive-cost-model-0.3.md](docs/adaptive-cost-model-0.3.md).
O fechamento do Marco 3 está em
[docs/sprints/010-aot-arena-marco3.md](docs/sprints/010-aot-arena-marco3.md).

## Demonstração congelada do marco 6×

O resultado ponta a ponta do Sprint 011 foi preservado como uma evidência
visual, autocontida e auditável:

- [demonstração para compradores](evidence/2026-07-30-marco4-6x/index.html);
- [protocolo e limites da evidência](evidence/2026-07-30-marco4-6x/README.md);
- [preparação comercial e de proteção intelectual](docs/commercial-and-ip-readiness.md).

A alegação congelada é `6,095936×` de ganho mediano pareado, com IC95% de
`5,994133×–6,230838×`, no experimento e hardware declarados. Ela não é uma
promessa universal de desempenho.

## Casulo e Teloscorp

**Casulo** é o invento. **Teloscorp** é sua autoria e origem pública.

O nome Teloscorp combina *télos* — finalidade — com *corp*, de corporação:
todo dado tem um fim para ser usado. A lembrança de uma corporação de histórias
em quadrinhos é intencional e integra a personalidade da marca.

Veja [NOTICE.md](NOTICE.md) para a atribuição que deve acompanhar distribuições
e derivados.
