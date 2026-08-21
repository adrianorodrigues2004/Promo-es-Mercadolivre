"""Conversao e arredondamento de valores monetarios.

Todo o dinheiro circula como ``Decimal`` para evitar os erros de ponto
flutuante que apareceriam ao somar centavos de centenas de anuncios.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP

CENTAVO = Decimal("0.01")
ZERO = Decimal("0")

_MOEDA_OU_PCT = re.compile(r"(?i)^\s*-?\s*(?:r\$|us\$|\$)?\s*|\s*%\s*$")
# Depois de tirar moeda e percentual, o que sobra tem de ser so numero: assim
# "=SOMA(A1:A2)" e "MLB4090546705" nao viram valores por acidente.
_SO_NUMERO = re.compile(r"\d[\d.,]*$")


def para_decimal(valor: object) -> Decimal | None:
    """Converte celula de planilha em ``Decimal``; ``None`` quando nao ha numero.

    Aceita os formatos que aparecem nos exports do Mercado Livre:
    ``1234.56``, ``1.234,56``, ``R$ 1.234,56``, ``12,5%`` e numeros nativos.
    """
    if valor is None:
        return None
    if isinstance(valor, Decimal):
        return valor
    if isinstance(valor, bool):
        return None
    if isinstance(valor, (int, float)):
        return Decimal(str(valor))

    bruto = str(valor).replace("\xa0", " ").strip()
    negativo = bruto.startswith("-") or (bruto.startswith("(") and bruto.endswith(")"))
    texto = _MOEDA_OU_PCT.sub("", bruto.strip("()")).strip()
    if not _SO_NUMERO.fullmatch(texto):
        return None

    tem_ponto = "." in texto
    tem_virgula = "," in texto
    if tem_ponto and tem_virgula:
        # O separador decimal e o ultimo a aparecer: "1.234,56" ou "1,234.56".
        decimal_e_virgula = texto.rfind(",") > texto.rfind(".")
        texto = texto.replace(".", "").replace(",", ".") if decimal_e_virgula else texto.replace(",", "")
    elif tem_virgula:
        texto = texto.replace(",", ".")
    elif tem_ponto:
        # "1.234" e milhar; "1.234.567" tambem. "12.34" e decimal.
        partes = texto.lstrip("-").split(".")
        if len(partes) > 2 or (len(partes) == 2 and len(partes[1]) == 3 and len(partes[0]) <= 3):
            texto = texto.replace(".", "")

    try:
        numero = Decimal(texto)
    except InvalidOperation:
        return None
    return -numero if negativo else numero


def para_percentual(valor: object) -> Decimal | None:
    """Le um percentual e devolve a fracao equivalente (``12,5%`` -> ``0.125``).

    Numeros ja fracionarios (<= 1 sem sinal de ``%``) sao mantidos como estao,
    porque algumas planilhas exportam ``0,15`` no lugar de ``15%``.
    """
    numero = para_decimal(valor)
    if numero is None:
        return None
    if isinstance(valor, str) and "%" in valor:
        return numero / Decimal(100)
    if numero > 1:
        return numero / Decimal(100)
    return numero


def centavos(valor: Decimal) -> Decimal:
    """Arredonda para 2 casas (meio para cima) - uso geral de exibicao."""
    return valor.quantize(CENTAVO, rounding=ROUND_HALF_UP)


def centavos_acima(valor: Decimal) -> Decimal:
    """Arredonda 2 casas para cima - usado em pisos de preco, protege a margem."""
    return valor.quantize(CENTAVO, rounding=ROUND_CEILING)


def centavos_abaixo(valor: Decimal) -> Decimal:
    """Arredonda 2 casas para baixo - usado em tetos de preco."""
    return valor.quantize(CENTAVO, rounding=ROUND_FLOOR)


def real_acima(valor: Decimal) -> Decimal:
    """Sobe para o real inteiro seguinte (R$ 47,10 -> R$ 48,00)."""
    return valor.quantize(Decimal("1"), rounding=ROUND_CEILING).quantize(CENTAVO)


def terminacao_90(valor: Decimal) -> Decimal:
    """Sobe para a proxima terminacao ``,90`` (R$ 47,10 -> R$ 47,90)."""
    inteiro = valor.quantize(Decimal("1"), rounding=ROUND_FLOOR)
    candidato = inteiro + Decimal("0.90")
    if candidato < valor:
        candidato = inteiro + Decimal("1.90")
    return candidato.quantize(CENTAVO)


ARREDONDAMENTOS = {
    "centavo": centavos_acima,
    "centavo_acima": centavos_acima,
    "real_acima": real_acima,
    "terminacao_90": terminacao_90,
}


def formatar(valor: Decimal | int | float | None, casas: int = 2) -> str:
    """Formata no padrao brasileiro: ``1.234,56``."""
    if valor is None:
        return ""
    if not isinstance(valor, Decimal):
        valor = Decimal(str(valor))
    quantizado = valor.quantize(Decimal(1).scaleb(-casas), rounding=ROUND_HALF_UP)
    inteiro, _, fracao = f"{abs(quantizado):.{casas}f}".partition(".")
    grupos = []
    while len(inteiro) > 3:
        grupos.insert(0, inteiro[-3:])
        inteiro = inteiro[:-3]
    grupos.insert(0, inteiro)
    texto = ".".join(grupos)
    if casas:
        texto = f"{texto},{fracao}"
    return f"-{texto}" if quantizado < 0 else texto
