"""O piso de preco: a conta que decide se um anuncio entra ou nao."""

from decimal import Decimal

import pytest

from promoml.precificacao import Encargos, avaliar, piso_de_preco, piso_por_lucro, piso_por_margem
from promoml.regras import regras_de_dict

# Comissao zerada de proposito: estes testes exercitam a aritmetica do piso, e
# fixar a comissao aqui deixa as contas independentes do padrao das regras.
REGRAS = regras_de_dict({"comissao_pct": "0%"})  # imposto 11,5%, margem 5%, R$ 10 abaixo de 150


def encargos(custo, **extras):
    return Encargos.de_regras(Decimal(str(custo)), REGRAS, **extras)


def test_lucro_bate_com_a_formula_da_planilha_de_precificacao():
    """Caso real: ADEGA NEW ODIN, com imposto 11,5% e taxa 16,5%."""
    enc = Encargos(
        custo=Decimal("183.54"),
        imposto_pct=Decimal("0.115"),
        comissao_pct=Decimal("0.165"),
        frete=Decimal("101.95"),
    )
    resultado = avaliar(Decimal("452.13"), enc)
    assert resultado.lucro == Decimal("40.04")
    assert round(resultado.margem_pct, 4) == Decimal("0.0886")


def test_rebate_entra_somando_no_lucro():
    """A coluna Ribait e dinheiro que o ML devolve: aumenta o lucro."""
    base = Encargos(custo=Decimal("227.76"), imposto_pct=Decimal("0.115"),
                    comissao_pct=Decimal("0.165"), frete=Decimal("106.95"))
    com_rebate = Encargos(**{**base.__dict__, "rebate": Decimal("11.23")})
    preco = Decimal("524.8902")
    assert avaliar(preco, com_rebate).lucro - avaliar(preco, base).lucro == Decimal("11.23")
    assert avaliar(preco, com_rebate).lucro == Decimal("54.44")


def test_cupom_reduz_o_preco_que_vale_para_a_conta():
    enc = Encargos(custo=Decimal("50"), imposto_pct=Decimal("0.115"), cupom_pct=Decimal("0.10"))
    resultado = avaliar(Decimal("200"), enc)
    assert resultado.preco_efetivo == Decimal("180.00")
    assert resultado.imposto == Decimal("20.70")   # 11,5% de 180, nao de 200


def test_piso_por_margem_deixa_exatamente_a_margem_pedida():
    enc = encargos("200")
    piso = piso_por_margem(enc, Decimal("0.05"))
    assert avaliar(piso, enc).margem_pct >= Decimal("0.05")


def test_piso_por_lucro_deixa_exatamente_o_lucro_pedido():
    enc = encargos("50")
    piso = piso_por_lucro(enc, Decimal("10"))
    assert avaliar(piso, enc).lucro >= Decimal("10")


@pytest.mark.parametrize("custo", ["10", "50", "116.90", "120", "124", "125", "167", "200", "900"])
def test_piso_de_preco_sempre_satisfaz_as_duas_regras(custo):
    """No piso, ou o produto passa dos R$ 150 com 5%, ou deixa R$ 10 de lucro."""
    enc = encargos(custo)
    piso = piso_de_preco(enc, REGRAS)
    resultado = avaliar(piso, enc)
    assert resultado.margem_pct >= Decimal("0.05")
    if piso < REGRAS.limiar_preco_baixo:
        assert resultado.lucro >= Decimal("10")


def _lucro_exato(preco, enc):
    """Lucro sem arredondar, para falar de minimalidade no centavo."""
    return preco * (Decimal(1) - enc.fracao_percentual) - enc.custos_fixos


@pytest.mark.parametrize("custo", ["10", "80", "120", "125", "300"])
def test_piso_de_preco_e_o_menor_preco_viavel(custo):
    """Um centavo abaixo do piso, alguma das duas regras ja quebra."""
    enc = encargos(custo)
    piso = piso_de_preco(enc, REGRAS)
    abaixo = piso - Decimal("0.01")
    lucro = _lucro_exato(abaixo, enc)
    quebra_margem = lucro / abaixo < Decimal("0.05")
    quebra_lucro = abaixo < REGRAS.limiar_preco_baixo and lucro < Decimal("10")
    assert quebra_margem or quebra_lucro, f"piso nao e minimo para custo {custo}"


def test_produto_de_custo_intermediario_nao_e_recusado_pela_regra_dos_dez_reais():
    """Custo R$ 125: a R$ 148 os R$ 10 nao saem, mas a R$ 150 a regra e a dos 5%.

    O piso tem de ser R$ 150 - e nao um valor inflado pela regra que so vale
    abaixo do limiar.
    """
    enc = encargos("125")
    piso = piso_de_preco(enc, REGRAS)
    assert piso == Decimal("150")
    assert avaliar(piso, enc).lucro < Decimal("10")      # abaixo dos R$ 10...
    assert avaliar(piso, enc).margem_pct >= Decimal("0.05")  # ...mas dentro dos 5%


def test_sem_preco_viavel_quando_os_encargos_comem_o_preco_inteiro():
    enc = Encargos(custo=Decimal("100"), imposto_pct=Decimal("0.60"), comissao_pct=Decimal("0.40"))
    assert piso_de_preco(enc, REGRAS) is None


def test_rebate_maior_que_o_custo_nao_gera_piso_negativo():
    enc = Encargos(custo=Decimal("10"), imposto_pct=Decimal("0.115"), rebate=Decimal("50"))
    piso = piso_de_preco(enc, REGRAS)
    assert piso > 0
