# Segurança, LAN e pareamento de dispositivos

## Modelo de ameaça mínimo

Proteger contra:

- vizinho ou visitante na mesma rede;
- dispositivo familiar perdido;
- usuário tentando acessar memória alheia;
- prompt tentando invocar shell ou exfiltrar dados;
- serviço interno exposto acidentalmente;
- token vazado em log;
- processo travado consumindo RAM/CPU/disco;
- conteúdo malicioso em documentos ingeridos.

Não declarar segurança de produção ou resistência a atacante local administrador no RP0.1.

## Pareamento

1. Owner abre o painel local no notebook.
2. Solicita código de pareamento aleatório, de uso único e validade máxima de cinco minutos.
3. Telefone acessa a URL HTTPS e envia o código.
4. Gateway cria identificador de dispositivo e credencial aleatória revogável.
5. Owner associa dispositivo a um usuário/perfil.
6. Credencial é armazenada em cookie `Secure`, `HttpOnly`, `SameSite=Strict` ou mecanismo equivalente.
7. Toda sessão registra usuário, dispositivo, horário, ação e resultado; nunca conteúdo secreto integral.

Não usar endereço MAC como identidade. Browsers não o fornecem de forma confiável e ele pode mudar. IP serve apenas como restrição auxiliar.

## Rede

- Gateway em `8443/TCP` na interface/sub-rede aprovada;
- serviços internos em `127.0.0.1`;
- firewall somente no perfil `Private`;
- regra limitada à sub-rede familiar;
- UPnP e port forwarding desativados;
- nenhuma configuração DMZ;
- IP do laptop reservado por DHCP;
- rede de convidados não recebe acesso;
- verificar isolamento de clientes no roteador.

## TLS local

A PWA e o microfone do navegador exigem contexto seguro. Criar uma CA local exclusiva do Casulo, manter a chave privada apenas no owner host e instalar somente o certificado público raiz nos dispositivos aprovados.

Nunca colocar chave privada, certificados de dispositivo ou cookies no Git/ZIP.

## Classes de ferramenta

| Classe | Exemplos | Regra |
|---|---|---|
| R0 | responder, buscar memória própria | automático |
| R1 | ler workspace autorizado | automático e auditado |
| R2 | criar/editar por patch | aprovação configurável + snapshot |
| R3 | executar testes/comandos allowlisted | limites e receipt |
| R4 | apagar, mover, instalar, rede externa | aprovação explícita por ação |
| R5 | administrador, credenciais, sistema | bloqueado no RP0.1 |

## Kill switch

O owner deve conseguir:

- pausar a fila;
- cancelar geração atual;
- desativar ferramentas;
- revogar dispositivo;
- desligar listener LAN mantendo acesso local;
- iniciar modo somente leitura;
- restaurar snapshot anterior.

