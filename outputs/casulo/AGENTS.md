# Instruções operacionais do Casulo

Escopo: todo o repositório, salvo instrução mais específica em subdiretório.

1. O objetivo ativo é produto voice-first. O GOAL científico está
   `SUPERSEDED_BY_PRODUCT_GOAL_2026_08_11`.
2. Não execute benchmarks longos, pares T/PyTorch, RAPL, HWiNFO, ablações ou
   paper gates no caminho padrão. Reprodução histórica exige autorização
   deliberada e `CASULO_ENABLE_LEGACY_RESEARCH=1`.
3. Preserve worktree e evidência histórica. Não mova nem apague campanhas para
   “limpar” o repositório.
4. Não reescreva o sistema inteiro. Entregue slices executáveis e teste cada
   contrato antes de migrar Python para Rust.
5. Não instale silenciosamente pacotes, drivers, pesos ou vozes. Primeiro rode
   doctor, registre versão/hash/licença e solicite a ação adequada.
6. `casulo-owner`, `casulo-public` e `casulo-cloud-standby` são builds
   mutuamente exclusivos. Public nunca pode conter/importar owner.
7. Cloud permanece `RELEASE_LOCKED`; produção, DNS, bind e credenciais reais
   exigem decisão futura explícita.
8. Capabilities são deny-by-default. Modelo generativo não cria grants.
9. T vNext não recebe sintaxe sem RFC semântica, AST, diagnósticos, lowering,
   IR/grafo, goldens e migração.
10. Atualize `docs/product/EXECUTION_STATE.md` após cada gate real. Não declare
    Product Alpha sem todas as evidências exigidas.
11. A partir de 2026-09-09, a trilha ativa solicitada pelo proprietário é a
    prova de compressão sem perda em vídeo 8K real e 100 milhões de registros.
    O produto voice-first e a pesquisa científica anterior ficam congelados e
    preservados. Testes sintéticos são regressão de engenharia, nunca prova das
    fontes reais; expansão e derrota contra baselines devem ser publicadas.
