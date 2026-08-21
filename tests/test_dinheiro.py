"""Leitura de numeros vindos de planilha, onde nada e padronizado."""

from decimal import Decimal

import pytest

from promoml.dinheiro import (
    centavos_abaixo, centavos_acima, formatar, para_decimal, para_percentual,
    real_acima, terminacao_90,
)


@pytest.mark.parametrize(
    "entrada, esperado",
    [
        ("R$ 1.234,56", "1234.56"),   # moeda brasileira
        ("1.234,56", "1234.56"),
        ("1,234.56", "1234.56"),      # moeda americana
        ("1234.56", "1234.56"),
        ("1.234", "1234"),            # ponto de milhar sem decimais
        ("12.34", "12.34"),           # ponto decimal
        ("1.234.567", "1234567"),
        ("-45,90", "-45.90"),
        (47.1, "47.1"),
        (0, "0"),
    ],
)
def test_para_decimal_entende_os_formatos_de_planilha(entrada, esperado):
    assert para_decimal(entrada) == Decimal(esperado)


@pytest.mark.parametrize("entrada", [None, "", "-", "abc", "=SOMA(A1:A2)", True])
def test_para_decimal_devolve_none_quando_nao_ha_numero(entrada):
    assert para_decimal(entrada) is None


@pytest.mark.parametrize(
    "entrada, esperado",
    [
        ("12,5%", "0.125"),   # percentual explicito
        (11.5, "0.115"),      # numero maior que 1 e percentual
        ("16,5", "0.165"),
        (0.15, "0.15"),       # ja fracionario, fica como esta
        ("0,5%", "0.005"),
    ],
)
def test_para_percentual(entrada, esperado):
    assert para_percentual(entrada) == Decimal(esperado)


def test_arredondamentos_protegem_o_lado_certo():
    assert centavos_acima(Decimal("10.001")) == Decimal("10.01")
    assert centavos_abaixo(Decimal("10.009")) == Decimal("10.00")
    assert real_acima(Decimal("47.10")) == Decimal("48.00")
    assert terminacao_90(Decimal("47.10")) == Decimal("47.90")
    assert terminacao_90(Decimal("47.95")) == Decimal("48.90")


def test_formatar_usa_padrao_brasileiro():
    assert formatar(Decimal("1234567.891")) == "1.234.567,89"
    assert formatar(Decimal("-45.9")) == "-45,90"
    assert formatar(None) == ""
