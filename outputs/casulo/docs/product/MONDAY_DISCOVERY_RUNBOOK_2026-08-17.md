# Roteiro humano M1 — descoberta de 2 a 4 horas

## Iniciar

Abra por duplo clique:

```text
product-demos\human-proof\monday-discovery-2026-08-17-attempt1\START_MONDAY_DISCOVERY.vbs
```

A janela mostrará a raiz append-only da sessão. Se ela não mostrar
`Presença real disponível`, registre uma nota e encerre; não force voz.

## Bloco 1 — boot e presença, 15–25 minutos

1. Observe quanto demora para o estado real de presença aparecer.
2. Converse por texto sobre um tema livre por 5–10 turnos.
3. Registre em **Nota** qualquer silêncio, repetição, bajulação, tom de
   atendente, resposta brilhante ou discordância útil.
4. Use `:universos`, `:rota` e `:memoria`.
5. Use `:snapshot` e então `:restore`; confirme que a janela continua usável.

## Bloco 2 — memória, 20–35 minutos

1. Dê um nome sintético a uma decisão, por exemplo “marcador Saturno Azul”.
2. Mude de assunto por vários turnos.
3. Pergunte “lembra daquilo?” e julgue recall, incerteza e proveniência.
4. Procure um controle de projeto. A ausência já é M1-F003; não simule que
   houve troca de projeto.
5. Registre toda mistura percebida como `PROJECT_BLEED` e toda falha de recall
   como `MEMORY`.

Não introduza segredos ou dados pessoais necessários apenas ao teste.

## Bloco 3 — criação simples, 30–50 minutos

1. Clique **Criar**.
2. Peça um agente pequeno e verificável com um requisito HARD explícito.
3. Escreva uma frase/comportamento observável esperado.
4. Confirme somente se a rota representa sua intenção.
5. Durante o job, envie uma pergunta curta pelo campo principal. Isso mede se
   Presence continua disponível enquanto o trabalho roda.
6. Compare intenção, T gerado, simulação, pacote e visual.
7. Registre divergência como `INTENT_ARTIFACT_DIVERGENCE`.

## Bloco 4 — criação complexa e correção, 40–70 minutos

1. Crie algo envolvendo ao menos três universos e duas restrições HARD.
2. Verifique se o Guia esclarece ambiguidade antes de confirmar.
3. Após materializar, peça uma correção localizada importante.
4. Observe se uma nova versão real aparece ou se o Guia apenas conversa.
5. Compare manifest/TCAP/artefato e registre `CREATION` ou
   `INTENT_ARTIFACT_DIVERGENCE`.
6. Inspecione qual visual abriu: mapa semântico ou forma viva da criação.

## Bloco 5 — voz opcional, 10–25 minutos

Voz não é obrigatória. Para testá-la, clique **Falar (8 s)**, leia o aviso e
digite exatamente o consentimento exibido. Teste:

- transcrição pt-BR;
- TTS;
- interrupção durante fala;
- retorno ao texto após falha.

PCM bruto não deve aparecer em nenhum artifact. Registre qualidade como
opinião humana `VOICE`; o observer não a inventará.

## Bloco 6 — export, reboot e retomada, 25–40 minutos

1. Use `:export` uma vez e preserve o resultado.
2. Perto do fim, use `:export` de novo para testar M1-F005; isso pode encerrar
   o processo filho, então não faça antes de salvar notas.
3. Feche pelo botão **Sair**.
4. Abra novamente o mesmo launcher; uma nova `session-*` será criada.
5. Confirme HOT vazio e recall/memória retomados.
6. Registre uma nota `SESSION_VERDICT`, ainda que a severidade seja
   `UNASSESSED`.

## Consolidar sem inventar julgamento

Depois das duas sessões:

```powershell
python tools/monday_discovery.py analyze-campaign --campaign-root "$env:LOCALAPPDATA\Casulo\monday-discovery\2026-08-17"
```

O comando apenas organiza eventos e notas. A incorporação final no atlas deve
preservar `HUMAN_OPINION_GUILHERME` separada de `AUTOMATED_DIAGNOSTIC`.
