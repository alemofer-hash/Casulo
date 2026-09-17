# ADR SM-001 — Semantic Multiverse

Status: `ACCEPTED_FOR_OWNER_ALPHA_INSPECTION`  
Escopo: Hosted/VM owner, sem Cloud, USB, QPU ou benchmark científico.

## Decisão

Fatorar conhecimento e capacidades instaladas em universos semânticos
versionados. O núcleo conversacional e as restrições confirmadas permanecem
HOT; especialistas percorrem `FROZEN -> WARM -> HOT` sob quota. Transições T
carregam estado suficiente tipado e sempre emitem receipts. Bases são imutáveis
e endereçadas por conteúdo; memórias singulares são deltas.

O modelo local pode propor conteúdo e candidatos. Schema, hashes, policy,
capabilities, lifecycle, transições, persistência, T Forge e materialização são
autoridades determinísticas. Uma transição nunca amplia permissions.

## Workload canônico e equivalência

O workload inicial cria um agente local inédito que atravessa pelo menos três
domínios dentre intenção, sinais, engenharia, diagnóstico, interface e
materialização. O caminho fatorado é operacionalmente equivalente ao caminho de
referência quando ambos preservam intenção, constraints obrigatórias, unidades,
incerteza, provenance, capabilities, compilação e materialização. Texto
generativo e trajetórias internas não precisam ser idênticos.

Thresholds locais congelados para este Goal:

- pelo menos 6 universos instalados;
- subconjunto HOT estrito em toda tarefa principal;
- quota HOT de 3 universos e 96 MiB nos fixtures;
- rota exige margem mínima `0.08`; abaixo disso, pede clarificação;
- projeção suficiente deve preservar todos os required fields e ser menor ou
  igual ao envelope completo; divergência usa fallback completo;
- 20 sessões não podem publicar blobs base duplicados;
- prefetch é abandonado antes de causar eviction do universo leased;
- GC somente relata candidatos, sem deletar bytes.

## Consequências

O sistema ganha observabilidade, isolamento e retomada, mas pode errar o
roteamento, acordar universos em excesso ou perder contexto numa projeção. Por
isso margem, fallback, receipts, leases, quarantine e harness de equivalência
são parte do produto, não telemetria opcional.

## Não alegações

Não demonstra compressão universal, igualdade bit a bit, datacenter literal em
32 GB, vantagem quântica/energética, superioridade geral, patenteabilidade ou
fim de datacenters.
