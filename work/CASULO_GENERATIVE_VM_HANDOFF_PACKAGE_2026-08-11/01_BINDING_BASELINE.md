# BASELINE VINCULANTE

## 1. Estado recebido

O estado informado em 2026-08-11 é:

```text
formal_gate = PRODUCT_ALPHA_COMPLETE
scientific_goal = SUPERSEDED_BY_PRODUCT_GOAL_2026_08_11
new_scientific_benchmark_started = false
owner = PRODUCT_ALPHA_LOCAL_PASS
public = SIGNED_CLIENT_HARNESS_PASS
cloud = SIGNED_STANDBY_RELEASE_LOCKED
```

O repositório declara possuir:

- domínio, memória, Voice Duplex, Guide Presence e T Forge;
- frontend T vNext, effects/capabilities e TCAP 1.1;
- simulação first-party sem efeitos reais;
- materialização reprodutível;
- Campo da Criação com 12 estados;
- Casulo Native Foundation em QEMU/OVMF;
- separação owner/public/cloud;
- auditoria pública sem componentes privados;
- testes de produto aprovados.

O Codex deve confirmar o estado no repositório. Este documento é direção e inventário recebido, não substituto para evidência executável.

## 2. Lacuna central

A inteligência owner atual é descrita como referência determinística first-party, não um motor generativo completo.

Portanto:

```text
platform_alpha = COMPLETE
first_generative_owner_engine = NOT_COMPLETE
generative_vm_handoff = NOT_COMPLETE
```

Fechar essa lacuna é a missão inteira deste pacote.

## 3. Riscos preservados

- a frase “Pare, Casulo” ainda possui risco de qualidade ASR por dispositivo;
- AEC e voz redistribuível continuam incompletos;
- assinaturas são de desenvolvimento;
- Native não possui drivers universais de áudio, GPU ou rede;
- Cloud permanece sem endpoint de produção;
- o worktree pode conter alterações e evidências históricas não rastreadas;
- modelos generativos locais podem exigir download, licença, hash e consentimento;
- o host possui pouco mais de 80 GB livres, suficiente com orçamento e imagens esparsas, mas não para acumular modelos e VMs indiscriminadamente.

## 4. Decisões que continuam valendo

- nenhuma campanha científica nova;
- nenhum claim de superioridade ou energia;
- `casulo-owner` usa motor direto e privado;
- `casulo-public` e `casulo-cloud-standby` não avançam nesta etapa;
- nenhuma API comercial de IA;
- modelo generativo nunca cria permissions/grants;
- memória, simulação e materialização continuam fail-closed;
- mouse/teclado são fallback; voz continua interface principal;
- nenhum dispositivo físico é escrito automaticamente.

## 5. Transição exigida

Antes de implementar geração:

1. auditar o estado real;
2. preservar o worktree preexistente;
3. registrar um checkpoint reproduzível do Alpha sem adicionar tudo cegamente;
4. mapear o motor determinístico atual;
5. garantir que ele permaneça apenas como test double/reference, nunca como release generativo;
6. manter regressões P0–P15 verdes durante a transição.

