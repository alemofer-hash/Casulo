"""Fonte única da identidade do invento."""

MARCA = "Casulo"
INVENTOR = "Guimo"
NATUREZA_DO_INVENTO = "Otimização de Tráfego de Informação"
ASSINATURA_DO_INVENTO = (
    f"{MARCA} — invento original de {INVENTOR} para {NATUREZA_DO_INVENTO}."
)


def texto_de_atribuicao() -> str:
    return (
        f"{ASSINATURA_DO_INVENTO}\n"
        "A origem do invento e da marca acompanha toda Borboleta liberada.\n"
        "Crédito público provisório: Guimo; substituir pelo nome formal antes do release.\n"
    )

