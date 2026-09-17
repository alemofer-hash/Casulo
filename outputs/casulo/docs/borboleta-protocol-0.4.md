# Protocolo Borboleta 0.4

## Finalidade

A Borboleta é a manifestação verificável do trabalho do Casulo. Ela não é uma
captura de tela nem uma promessa de desempenho: é um pacote de experimento que
liga uma fonte T, um artefato compilado, um dataset identificável e todas as
amostras brutas às conclusões publicadas.

## Contrato público

```python
from casulo.t import (
    ArtifactBuilder,
    BorboletaConfig,
    BorboletaLaboratorio,
)

artifact = ArtifactBuilder().build("programa.t").output_dir
report = BorboletaLaboratorio().run(
    artifact,
    config=BorboletaConfig(records=2_000),
)
report.write("resultado")
```

As classes acima formam a API candidata a estável do protocolo
`casulo-borboleta/0.4`.

## Pacote de evidência

O comando:

```console
t experiment programa.t --output resultado
```

produz:

```text
resultado/
├── dataset.json
├── dataset-manifest.json
├── borboleta-report.json
└── borboleta-report.html
```

O manifesto registra protocolo, semente, quantidade de registros, taxa de
duplicação e SHA-256. O relatório contém ambiente, configuração, amostras
brutas, medianas, intervalo de confiança, prova de equivalência e ressalvas.

## Protocolo estatístico

1. gerar o dataset com PRNG e semente fixos;
2. executar uma vez cada estratégia e comparar o SHA-256 da projeção semântica;
3. realizar aquecimento;
4. desabilitar temporariamente o coletor de lixo;
5. alternar a ordem entre referência escalar, lote deduplicado e execução
   adaptativa;
6. conservar todas as amostras de tempo de parede e CPU;
7. calcular mediana e intervalo de 95% por bootstrap pareado;
8. registrar memória residente observada no início/fim e energia, quando
   mensurável;
9. publicar as limitações junto ao resultado.

O fator de velocidade é `tempo_escalar / tempo_casulo`. Valores acima de 1
favorecem o Casulo. O veredito é `improvement` quando todo o intervalo de 95%
fica acima de 1, `regression` quando fica abaixo de 1 e `inconclusive` quando o
intervalo cruza 1.

Alternar a ordem reduz viés sistemático causado por temperatura, turbo e carga
de fundo. O bootstrap usa a mesma semente do experimento, portanto o intervalo
é reproduzível a partir das amostras.

A comparação 0.4 usa três trajetórias:

1. referência escalar sem cache;
2. lote Casulo com cache frio e deduplicação forçada;
3. execução adaptativa completa, incluindo perfil, decisão e estratégia.

Somente duplicatas presentes no próprio lote são reutilizadas; nenhum resultado
de uma amostra anterior contamina a seguinte. A limpeza do cache faz parte do
tempo medido. A taxa de duplicação é sempre declarada no manifesto, e um ensaio
com `--duplicate-rate 0` isola o custo do lote sem reutilização.

O relatório conserva duas comparações. `comparison` mede o potencial e o custo
do kernel deduplicado quando forçado. `adaptation` mede o comportamento que um
usuário realmente recebe, de ponta a ponta. Uma previsão só é classificada como
correta ou incorreta quando o intervalo de 95% separa as estratégias; caso
contrário, o resultado é `INCONCLUSIVE_SAFE`.

Na versão 0.4, o perfil manifesta pares coincidentes da amostra, protocolo da
chave estrutural e escopo do cache. `RECALCULATE` usa o caminho escalar,
`FUSE_TYPED_BATCH` usa as colunas mesmo sem repetição suficiente e
`DEDUPLICATE_BATCH` combina colunas e reutilização.

Antes da medição temporal, a Borboleta executa uma chamada fria do lote de
objetos e outra do lote tipado sob `tracemalloc`. O bloco
`comparison.representation` registra pico rastreado, bytes e blocos retidos.
A telemetria `hot_path` informa bytes dos buffers e quantas estruturas
intermediárias da implementação de referência foram evitadas. Essa sonda não
fica dentro das amostras de velocidade.

A projeção semântica conserva entrada original, resultado, julgamentos,
restrições, estabilizações e demais evidências. Ela exclui somente o campo
`cache`, pois esse campo é telemetria da estratégia e precisa diferir quando uma
duplicata é reutilizada. A exclusão aparece em
`comparison.semantic_projection_excludes`; não é implícita.

## Semântica de energia

Há três estados permitidos:

| Qualidade | Fonte | Pode declarar joules? |
|---|---|---:|
| `measured_package_counter` | Linux powercap/RAPL | sim |
| `measured_external` | contador cumulativo indicado pelo operador | sim |
| `not_measured` | nenhum contador encontrado | não |

Em Linux, o laboratório detecta `/sys/class/powercap/intel-rapl*/energy_uj`.
Um medidor externo pode publicar a energia cumulativa, em joules, num arquivo e
definir `CASULO_ENERGY_COUNTER_FILE` com esse caminho.

Tempo de CPU é mantido como proxy de trabalho computacional. Ele nunca é
renomeado como energia elétrica.

## O que o experimento demonstra

- conservação da projeção semântica entre os caminhos comparados;
- vazão e latência do runtime para aquela carga e máquina;
- intervalo experimental, e não apenas o melhor resultado;
- custo de CPU, RSS observada e, quando disponível, energia elétrica.

Ele não demonstra acurácia meteorológica ou hidrológica. Isso pertence ao
protocolo de validação do gêmeo digital e requer dados observados, hindcasting e
comparação fora da amostra.
