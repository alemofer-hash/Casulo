# Perfil mínimo HWiNFO para o gate energético

Estado: `READY_FOR_MANUAL_UI_ACTION`.

O perfil mantém o polling global em 250 ms e reduz somente os sensores
monitorados. A configuração atual e o CSV foram identificados e preservados no
`protocol.json`; o registro do HWiNFO foi exportado antes da mudança.

## Ação manual

1. Pare apenas o logging atual; não feche o HWiNFO.
2. Abra a janela **Estado dos sensores** e expanda os grupos.
3. Selecione grupos inteiros que não sejam CPU ou bateria e pressione `Delete`
   para **Disable Monitoring**. Não use apenas Hide.
4. Mantenha habilitados os grupos do Intel Core i5-1235U, incluindo `DTS` e
   `Enhanced`, e o grupo da bateria `L21M3PF0`.
5. Confirme que todos os nomes listados em `mandatory_sensor_literals` no
   `protocol.json` continuam monitorados.
6. Inicie um **novo** CSV, sem reutilizar o arquivo histórico, mantendo 250 ms.

Após a ação, o Casulo inspecionará o novo cabeçalho antes de qualquer janela
idle. Sensor ausente reprova o perfil; nenhum campo será inferido.
