# Sprint 025.1 — Ablação pareada da agenda GEMM

**Estado:** pré-registrada; nenhuma amostra executada

## Pergunta

No mesmo backend Casulo/OpenBLAS, a agenda GEMM adaptativa supera a agenda fixa
de dois workers com estabilidade suficiente para se tornar a política padrão?

## Desenho selado

- três reinícios independentes;
- oito pares fixa/adaptativa por reinício;
- quatro primeiras posições para cada variante dentro de cada processo;
- janela mínima compartilhada de 250 ms;
- mesmo número de invocações para as duas variantes;
- paridade com NumPy antes de qualquer medição;
- dois workers máximos;
- CV máximo de 15%;
- bootstrap hierárquico por processo e por par;
- efeito prático mínimo de 2%;
- margem de equivalência de 2%;
- mesmo estado de alimentação nos três blocos;
- ao menos 60% de bateria no início de cada bloco quando desconectado.

O pré-registro v1 foi supersedido sem execução porque a bateria observada estava
em 41%, próxima do bloqueio térmico de 40%, e o contrato de alimentação ainda
não estava explícito. Nenhum resultado de ablação foi observado antes da v2.

Uma cópia intermediária v2 foi verificada, mas ficou retida por um handle do
filesystem antes da inclusão no Git. Ela permanece local e não é autoridade.
A cópia final foi novamente gerada a partir da v1, verificada e adicionada ao
Git antes de qualquer execução.

Pré-registro final válido:

`0644dec497cce9d3f307a629befdb76da94d4148edd6ce0e9592803663448865`

## Juiz

O ratio é `tempo_fixo / tempo_adaptativo`; valores acima de um favorecem a
agenda adaptativa. O juiz pode retornar:

- `ADAPTIVE`: IC95% inteiramente acima de 1 e mediana ao menos 1,02;
- `FIXED`: IC95% inteiramente abaixo de 1 e mediana no máximo 0,98;
- `EQUIVALENT`: IC95% inteiro entre 0,98 e 1,02;
- `INCONCLUSIVE`: qualquer resultado válido restante;
- `INVALID`: falha de paridade, telemetria, atestação ou alimentação.

Essa classificação escolhe uma política interna. Não constitui comparação com
backend externo, medição de energia ou alegação comercial.
