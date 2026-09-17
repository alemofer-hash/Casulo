# Casulo como jogo local de invenção

## Norte

O Casulo deve parecer menos uma ferramenta de programação e mais um mundo local
em que ideias ganham forma. A pessoa dá um nome ao Guia, conversa em português
comum e descreve o que imagina sem precisar saber como fabricar. O Guia sustenta
a conversa; o motor registra silenciosamente intenção, requisitos, riscos,
verificadores e decisões de engenharia até existir um artefato confirmável.

A metáfora de produto é um jogo pesado instalado no computador: modelo,
memória, compilador, simulação e fabricação vivem localmente. Não há cota de
mensagens apresentada como unidade criativa nem API externa obrigatória. Isso
não remove limites físicos: contexto, RAM, disco, temperatura e tempo continuam
reais, devem ser gerenciados honestamente e nunca ocultados atrás de uma promessa
de capacidade infinita.

## Contrato da conversa principal

1. A pessoa fala da ideia do jeito que ela apareceu.
2. O Guia desenvolve a imagem e mostra o que entendeu em linguagem cotidiana.
3. O motor separa internamente evidência explícita, inferência e lacuna.
4. Decisões de linguagem, framework, API, banco, arquitetura, algoritmo, modelo,
   servidor e hardware pertencem ao motor de engenharia — nunca são dever de
   casa do usuário.
5. Só uma escolha humana material pode interromper o fluxo. Ela deve ser
   formulada em termos de experiência, comportamento, prioridade, autonomia,
   risco ou gosto observável.
6. Antes da fabricação, a pessoa confirma a imagem da intenção. Inferência não
   confirmada não vira requisito silenciosamente.
7. Depois da confirmação, RequirementGraph, T, verificação, reparo, simulação e
   materialização trabalham em segundo plano e reportam apenas eventos reais.
8. O resultado volta como algo utilizável e reeditável, não como uma resposta
   textual fechada.

## Limite honesto da expressão “entender exatamente”

“Entender exatamente” é um critério de produto, não uma propriedade já provada
do modelo. Operacionalmente significa:

- preservar todas as falas e sua proveniência;
- marcar inferências como inferências;
- exibir um espelho curto da criação antes de fabricar;
- perguntar somente quando duas interpretações materiais permanecem possíveis;
- exigir confirmação humana para transformar inferência em requisito;
- permitir correção sem destruir a versão anterior;
- recusar fabricação quando a intenção continuar materialmente ambígua.

O Casulo não lê pensamentos. Ele precisa ser muito bom em reconstruir intenção
sem fingir certeza.

## Fluxo de produto

```text
nomear o Guia
→ imaginar em voz alta
→ espelho criativo curto
→ escolha humana rara, se material
→ acordo
→ fabricação local em background
→ forma viva e eventos reais
→ simulação
→ artefato executável
→ conversa para corrigir
→ nova versão causal
```

## Engenharia invisível, evidência visível sob demanda

A interface principal esconde terminologia técnica; ela não apaga a engenharia.
O `IntentTwin`, o RequirementGraph, as rotas, os sources T, diagnostics,
receipts, manifests, SBOMs e hashes continuam persistidos e acessíveis no modo
avançado. A simplicidade da experiência é uma projeção validada sobre um núcleo
auditável, não um atalho que ignora requisitos.

## Vertical slice de 2026-08-20

Implementado no source owner corrente:

- `:criar` inicia com uma única fala livre;
- a segunda pergunta obrigatória de comportamento observável foi removida;
- o comportamento observável é reconstruído internamente e só ganha autoridade
  após o espelho e a confirmação humana;
- hipóteses e rota neural deixaram de ser despejadas na conversa principal,
  mas continuam persistidas;
- milestones reais de `IntentDelta`, RequirementGraph, T, simulação e
  materialização recebem uma projeção cotidiana; o texto técnico e o mesmo hash
  de evidência continuam juntos no evento para inspeção avançada;
- `CreativeIntentProjection` mostra resumo e, no máximo, uma escolha material,
  enquanto registra contagens e proveniência do ledger interno;
- perguntas contendo escolhas explícitas de implementação são recusadas pelo
  contrato e voltam ao repair bounded do reconstrutor;
- `:nome` persiste uma identidade escolhida pelo usuário com hash e escrita
  atômica;
- o nome é validado antes de entrar no contexto neural para não virar instrução;
- o `GuidePresence` hosted passou a pedir cenas e resultados reconhecíveis, não
  “finalidade” e “restrição”.

Este slice não demonstra ainda criação arbitrária perfeita, qualidade humana,
voz final, ausência total de atrito nem execução independente do checkout. Ele
define e exerce a primeira fronteira de experiência que as próximas versões
precisam preservar.

## Próximo gate de produto

Uma sessão local deve permitir, sem abrir controles avançados:

1. escolher o nome do Guia;
2. conversar livremente por cinco turnos;
3. iniciar uma criação inédita com uma única descrição leiga;
4. receber no máximo uma pergunta, não técnica;
5. reconhecer ou corrigir o espelho;
6. continuar conversando durante a fabricação;
7. abrir o artefato resultante;
8. pedir uma correção em linguagem comum;
9. observar somente o subgrafo afetado mudar;
10. retomar a criação depois de reiniciar.

Qualidade, prazer de uso e química permanecem julgamento de Guilherme. Testes
automatizados verificam contratos e regressões, não substituem essa decisão.
