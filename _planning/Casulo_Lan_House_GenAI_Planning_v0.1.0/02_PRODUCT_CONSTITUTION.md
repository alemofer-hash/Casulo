# Constituição do CASULO FAMILY RP0.1

## Produto

O Casulo é a infraestrutura cognitiva; o modelo de linguagem é um órgão substituível. A identidade do sistema reside na memória, políticas, ferramentas, contratos, proveniência e execução local.

## Usuários

- `owner`: administração, modelos, ferramentas, backups e pareamento;
- `family`: conversa, voz, memória própria e documentos autorizados;
- `restricted`: conversa e ferramentas explicitamente permitidas;
- `guest`: sessão efêmera, sem memória persistente por padrão.

## Invariantes

1. O notebook é a única autoridade de inferência.
2. Clientes são terminais; não recebem pesos nem executam o modelo.
3. O Gateway é a única fronteira de rede.
4. Serviços internos usam loopback ou transporte local autenticado.
5. Memória pertence a um usuário ou espaço explicitamente compartilhado.
6. Ferramentas são deny-by-default.
7. Toda mutação importante é reversível ou exige confirmação explícita.
8. Internet indisponível não interrompe chat, voz, memória ou programação local.
9. O sistema não promete verdade sem evidência; registra proveniência e incerteza.
10. Desempenho nunca justifica quebrar isolamento ou auditabilidade.

## Fora do escopo do RP0.1

- acesso remoto pela internet;
- aplicativo móvel nativo;
- treinamento de modelo fundacional;
- fine-tuning;
- múltiplas gerações pesadas simultâneas;
- integração com contas externas;
- automação residencial ou financeira;
- execução administrativa autônoma;
- Casulo Native bare-metal como requisito de entrega;
- equivalência de inteligência com modelos de fronteira.

## Definição de independência

Independência significa que inferência, memória, ferramentas, voz, interface e dados continuam funcionando sem assinatura ou servidor de terceiros. Software e pesos abertos são dependências empacotadas, licenciadas, verificadas e substituíveis, não serviços operacionais obrigatórios.

