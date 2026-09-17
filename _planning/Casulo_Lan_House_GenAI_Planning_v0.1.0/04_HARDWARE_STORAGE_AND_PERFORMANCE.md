# Hardware, armazenamento e orçamento

## Máquina congelada para o sprint

- CPU: Intel Core i5;
- RAM: 16 GB;
- GPU: integrada;
- SSD: 256 GB;
- espaço livre confirmado: 127 GB;
- papel: servidor central e estação de desenvolvimento.

## Orçamento do SSD

| Categoria | Meta | Limite de alerta |
|---|---:|---:|
| Reserva permanente do Windows/pagefile | 30 GB | nunca consumir |
| WSL2 e toolchain | 20 GB | 28 GB |
| repositório, builds e testes | 15 GB | 22 GB |
| modelos LLM ativos e fallback | 16 GB | 22 GB |
| voz e embeddings | 4 GB | 6 GB |
| caches/offline bundle | 15 GB | 22 GB |
| memória, índices, logs e snapshots | 12 GB | 20 GB |
| margem ainda não alocada | 15 GB | — |

Gate permanente: interromper downloads/builds automáticos se o espaço livre cair abaixo de 30 GB.

## Orçamento de RAM

| Componente | Meta aproximada |
|---|---:|
| Windows e serviços | 3–4 GB |
| WSL/Casulo | 2–3 GB |
| modelo 7–9B Q4 + KV | 6–8 GB |
| voz, embeddings e gateway | 1–2 GB |
| margem | 1–2 GB |

Regras:

- um modelo principal carregado;
- uma geração pesada simultânea;
- contexto inicial 8192;
- mmap preferido;
- sem `mlock` antes de comprovar margem;
- KV cache quantizado somente depois de teste de qualidade;
- não usar swap como estratégia normal de inferência.

## Benchmarks obrigatórios

Cada candidato deve ser medido em CPU e no backend acelerado disponível:

- tempo de carregamento;
- tokens por segundo de prompt e geração;
- RAM comprometida e working set;
- temperatura, clock e throttling;
- qualidade em português;
- chamadas de ferramenta válidas;
- edição de código em tarefa real;
- recuperação após cancelamento;
- estabilidade em 30 e 120 minutos.

O backend mais rápido só vence se completar todos os testes sem corrupção, travamento ou pressão de memória inaceitável.

