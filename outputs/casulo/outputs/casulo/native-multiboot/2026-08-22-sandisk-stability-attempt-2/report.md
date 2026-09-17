# Estabilidade física do SanDisk — tentativa 2

Estado: `BLOCKED_PHYSICAL_MEDIA_UNSTABLE`

Em uma janela read-only de 120 amostras, o SanDisk esteve presente em apenas
uma e ausente em 119. Durante a própria janela, o Windows registrou um novo
evento `disk/51` para `Harddisk1/DR5`. Ao final, o dispositivo permanecia como
`Present=false`, `Problem=45`.

Nenhuma montagem foi concluída e nenhum byte foi escrito. Essa mídia/porta não
é aceitável para instalação, redimensionamento ou atualização do bootloader.

