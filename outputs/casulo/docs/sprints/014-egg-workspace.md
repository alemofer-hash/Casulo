# Sprint 014 — Egg Workspace

## Entrega

- manifesto `casulo.toml`;
- lockfile endereçado por conteúdo;
- descoberta recursiva de fontes;
- módulos core e training no mesmo projeto;
- dependências locais;
- resolução de `use`;
- detecção de duplicatas e ciclos;
- ordem topológica determinística;
- build multifile e cache por workspace;
- entrypoint explícito;
- comandos `t init`, `t check .`, `t build .`, `t run .` e `t test .`;
- `t training-experiment` aceita um projeto com entrypoint training.

## Invariantes

- nenhuma dependência ausente é ignorada;
- nenhum ciclo é quebrado arbitrariamente;
- fontes sem `module` são rejeitadas;
- build repetido do mesmo conteúdo é cache hit;
- alteração de qualquer fonte produz outra identidade;
- projetos de treinamento continuam subordinados ao Pacto Científico.

## Próximo passo

O Sprint 015 introduzirá LarvaTensor, shapes, dtype, contratos de aliasing e
uma ABI versionada para bibliotecas e extensões.
