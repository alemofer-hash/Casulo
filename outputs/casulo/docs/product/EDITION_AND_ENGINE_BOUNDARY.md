# Fronteira de edições e motor

## Propriedade

O motor principal, pesos, políticas privadas e adapter owner pertencem e ficam
sob controle de Guilherme Moura Fernandes.

## Builds mutuamente exclusivos

| Perfil | Conteúdo permitido | Conteúdo proibido |
|---|---|---|
| `casulo-owner` | `OwnerEngineAdapter`, motor privado, manifest e SBOM owner | dependência obrigatória de Cloud no fluxo principal |
| `casulo-public` | contratos públicos, `CloudEngineClient`, memória local, endpoint first-party pinado por release | motor, pesos, secrets, símbolos privados, fallback owner ou endpoint arbitrário |
| `casulo-cloud-standby` | protocolo, gateway, auth abstrata, jobs, eventos, policy, observabilidade, adapters de teste | bind/deploy de produção ou credenciais reais enquanto locked |

Não existe desbloqueio por nome, e-mail, hostname, variável escondida ou flag de
runtime do cliente. A separação é feita por targets, dependências, assinaturas,
manifests e supply chains distintas.

## Contrato comum

`CasuloEngine` define geração incremental, eventos de progresso, cancelamento e
resultado versionado. Owner liga esse contrato diretamente ao adapter privado.
Public liga somente ao cliente Cloud. O harness de desenvolvimento implementa o
mesmo protocolo sem fingir produção.

## Gate de distribuição

O CI deve inspecionar imports, dependências e conteúdo do artefato public e
falhar se localizar `OwnerEngineAdapter`, ativos privados, secrets ou fallback
owner. A ausência precisa ser provada por manifesto e auditoria do pacote, não
por convenção de nomes.

## Evidência do Product Alpha

- `casulo-owner`: `LocalOwnerMotor` privado executa diretamente o pipeline
  geral de criação e não invoca Cloud no vertical slice;
- `casulo-public`: wheel com 6 arquivos, zero componente proibido e content tree
  SHA-256 `6ea3f750d844ec7e519a2f81c012b8b6fda2dcacb92712aba50cc8721284d9d5`;
- `casulo-cloud-standby`: gateway e broker testáveis, mas todo production bind
  permanece negado por `CloudReleaseLock`;
- os três manifests são assinados por chaves Ed25519 de desenvolvimento
  distintas; somente chaves públicas e assinaturas entram nos artefatos;
- chaves privadas permanecem fora do repositório e não qualificam release
  comercial.

A prova é de separação estrutural e supply chain. Ela não depende de nome,
email, hostname, variável escondida ou flag runtime do cliente.
