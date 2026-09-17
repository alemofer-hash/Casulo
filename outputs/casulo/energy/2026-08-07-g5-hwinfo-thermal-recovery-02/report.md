# Calibração rejeitada por contaminação do observador

Esta tentativa foi interrompida antes de qualquer workload TCAP ou Eager e antes de pares definitivos. A guarda física relia todo o CSV em cada poll, elevando o próprio overhead do runner. Os dados permanecem preservados, mas não autorizam conclusão energética.

A implementação substituta `bounded-live-tail-v1` lê no máximo 256 KiB por poll; a integração científica continua usando o snapshot completo imutável.

`TOTAL_SYSTEM_WALL=BLOCKED_PHYSICAL_INSTRUMENT`

`CASULO_NATIVE_ENERGY=BLOCKED_PHYSICAL_INSTRUMENT`
