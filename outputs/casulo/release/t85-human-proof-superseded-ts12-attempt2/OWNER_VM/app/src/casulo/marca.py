"""Fonte única da identidade do invento e de sua autoria pública."""

MARCA = "Casulo"
AUTORIA_PUBLICA = "Teloscorp"
NATUREZA_DO_INVENTO = "Otimização de Tráfego de Informação"
ASSINATURA_DO_INVENTO = (
    f"{MARCA} — invento original da {AUTORIA_PUBLICA} para "
    f"{NATUREZA_DO_INVENTO}."
)


def texto_de_atribuicao() -> str:
    return (
        f"{ASSINATURA_DO_INVENTO}\n"
        "A origem do invento e da marca acompanha toda Borboleta liberada.\n"
        "Teloscorp é a identidade pública de sua autoria e origem.\n"
        "Telos expressa finalidade: todo dado tem um fim para ser usado.\n"
    )
