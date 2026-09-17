# Sprint 013 — Pacto científico e prova ampla

**Estado:** em andamento.

## Entregue nesta etapa

- Pacto Científico `1.0` com doze invariantes;
- `EggPreRegistro` imutável e content-addressed;
- vínculo obrigatório entre desenho selado e execução;
- execução sem pré-registro marcada como exploratória;
- juiz independente com cinco classificações;
- bootstrap independente de 10.000 reamostragens;
- sondagem que preserva indisponibilidade de baseline;
- verificação da cadeia pré-registro → relatório → veredito;
- primeiro resultado formalmente `INCONCLUSIVE`.

## Primeira aplicação

O experimento
`sha256:c143ed9de4c57373370e7985356eb379ac7a636fd0b2d5ba8e0728957d886302`
registrou antes da medição:

- PyTorch eager CPU;
- PyTorch `torch.compile`/Inductor CPU;
- 21 pares;
- três aquecimentos;
- 2.000 reamostragens no runner;
- limiar de superioridade `1×`;
- limiar comercial `6×`.

A parcela eager obteve `8,957846×`, com IC95% independente
`8,075179×–9,872416×`, equivalência e qualidade aprovadas.

O veredito final foi `INCONCLUSIVE`: `torch.compile` falhou antes da medição
porque `cl.exe` não está instalado. O ganho eager permanece válido em seu
escopo, mas não é promovido a prova ampla contra PyTorch compilado.

## Trabalho restante do Sprint 013

1. instalar o toolchain C++ exigido pelo Inductor;
2. repetir a sondagem em novo arquivo, sem apagar a falha;
3. implementar a medição pareada do baseline compilado;
4. executar carga sustentada e maior que a memória imediata;
5. adicionar filas limitadas, backpressure, checkpoint e cancelamento;
6. medir eficiência de quatro workers;
7. emitir novo veredito usando todos os baselines pré-registrados.

O Sprint somente termina após a execução completa ou uma conclusão negativa
tecnicamente sustentada. Indisponibilidade não conta como vitória.
