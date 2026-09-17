# Workspace T 0.1

## Finalidade

O Workspace T transforma uma pasta em unidade reproduzível de compilação.
Cada projeto declara fontes, entrypoint, dependências locais e módulos
externos permitidos em `casulo.toml`.

## Estrutura mínima

```text
project/
├── casulo.toml
├── casulo.lock
├── src/
│   ├── main.t
│   └── library.t
└── tests/
    └── smoke.t
```

`casulo.lock` é gerado pelo build e sela o compilador, o workspace e o hash de
cada fonte.

## Manifesto

```toml
[project]
name = "traffic-lab"
version = "0.1.0"
kind = "application"
entry = "traffic_lab.main"
source = "src"
external_modules = ["casulo.std"]

[dependencies]
hydrology = { path = "../hydrology" }
```

Projetos `application` exigem `entry`. Projetos `library` podem omiti-lo.
Dependências 0.1 são locais e também precisam possuir `casulo.toml`.

## Fases

- `EggProjectManifest`: lê e valida a intenção declarada;
- `EggModule`: identifica fonte, módulo, tipo e hash;
- `LarvaWorkspace`: resolve módulos, dependências e ordem;
- `CrisalidaWorkspaceBuild`: materializa todos os artefatos;
- `workspace.json`: manifesta a Borboleta executável do projeto;
- Quarentena: módulo ausente, duplicado, cíclico ou incompatível bloqueia o
  build.

## Comandos

```console
t init traffic-lab
t check traffic-lab
t build traffic-lab
t run traffic-lab --operation Main
t test traffic-lab
```

Para um projeto cujo entrypoint seja `training`:

```console
t training-experiment examples/t-project-training \
  --output build/project-training \
  --baseline pytorch-eager-cpu
```

## Diagnósticos

| Código | Significado |
|---|---|
| `T4001` | manifesto ausente |
| `T4002` | manifesto inválido |
| `T4005` | arquivo sem declaração `module` |
| `T4010` | módulo duplicado |
| `T4011` | módulo usado e não resolvido |
| `T4012` | ciclo entre módulos |
| `T4013` | entrypoint ausente |
| `T4020` | módulo core inválido |
| `T4021` | módulo de treinamento inválido |
| `T4040` | destino contém outro workspace |

## Limites deliberados

O formato 0.1 resolve e compila módulos, mas ainda não permite que símbolos de
um módulo sejam referenciados diretamente por outro. `use` estabelece a
dependência e a ordem; ligação de símbolos e a ABI de bibliotecas pertencem ao
próximo protocolo.
