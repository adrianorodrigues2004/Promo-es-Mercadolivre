"""Tabela de custos: leitura das colunas e casamento com o anuncio."""

from decimal import Decimal

import pytest

from promoml.custos import carregar_custos
from promoml.regras import Regras


def test_le_as_colunas_da_planilha_de_precificacao(custos_xlsx):
    tabela = carregar_custos(custos_xlsx)
    assert tabela.campos["custo"] == "Custo"
    assert tabela.campos["comissao_pct"] == "Taxa"
    assert tabela.campos["frete"] == "Frete "        # com espaco sobrando
    assert tabela.campos["id"] == "Código"
    assert tabela.campos["preco_atual"] == "Preço Atual"


def test_margem_desejada_nao_vira_margem_minima(custos_xlsx):
    """"Margem Desejada" e meta comercial, nao regra de corte da promocao."""
    tabela = carregar_custos(custos_xlsx)
    assert "margem_min_pct" not in tabela.campos
    custo, _ = tabela.buscar(id_anuncio="MLB4000000001")
    assert "margem_min_pct" not in custo.sobrescritas


def test_casa_mlb_com_e_sem_prefixo(custos_xlsx):
    """A planilha de custos guarda 4000000001; o ML manda MLB4000000001."""
    tabela = carregar_custos(custos_xlsx)
    custo, via = tabela.buscar(id_anuncio="MLB4000000001")
    assert custo.titulo == "MESA FOLGADA"
    assert via == "MLB (numero)"


def test_casa_pelo_preco_atual_quando_nao_ha_mlb(custos_xlsx):
    tabela = carregar_custos(custos_xlsx)
    custo, via = tabela.buscar(id_anuncio="MLB0000000000", preco_atual=Decimal("777.77"))
    assert custo.titulo == "ITEM SO POR PRECO"
    assert via == "preco atual"


def test_preco_ambiguo_nao_chuta_um_custo(custos_xlsx, tmp_path):
    """Dois produtos com o mesmo preco e custos diferentes: melhor nao casar."""
    from openpyxl import load_workbook

    wb = load_workbook(custos_xlsx)
    wb["Mercado Livre"].append(["OUTRO ITEM", "", 999, 10, 11.5, 11.5, 30, 0, 777.77])
    destino = tmp_path / "ambiguo.xlsx"
    wb.save(destino)

    tabela = carregar_custos(destino)
    custo, via = tabela.buscar(preco_atual=Decimal("777.77"), titulo="Nome que nao ajuda")
    assert custo is None and via == ""


def test_titulo_desempata_precos_iguais(custos_xlsx, tmp_path):
    from openpyxl import load_workbook

    wb = load_workbook(custos_xlsx)
    wb["Mercado Livre"].append(["BANCO CARO", "", 999, 10, 11.5, 11.5, 30, 0, 777.77])
    destino = tmp_path / "desempate.xlsx"
    wb.save(destino)

    tabela = carregar_custos(destino)
    custo, via = tabela.buscar(preco_atual=Decimal("777.77"), titulo="Banco Caro De Madeira")
    assert custo.titulo == "BANCO CARO"
    assert via == "preco + titulo"


def test_metodos_desabilitados_sao_respeitados(custos_xlsx):
    tabela = carregar_custos(custos_xlsx)
    custo, _ = tabela.buscar(preco_atual=Decimal("777.77"), metodos=("mlb", "sku"))
    assert custo is None


def test_encargos_por_anuncio_sobrescrevem_as_regras_globais(custos_xlsx):
    """Classico (11,5%) e Premium (16,5%) convivem na mesma rodada."""
    tabela = carregar_custos(custos_xlsx)
    regras = Regras()
    classico, _ = tabela.buscar(id_anuncio="4000000001")
    premium, _ = tabela.buscar(id_anuncio="4000000002")
    assert classico.encargos(regras).comissao_pct == Decimal("0.115")
    assert premium.encargos(regras).comissao_pct == Decimal("0.165")
    assert premium.encargos(regras).frete == Decimal("50")


def test_arquivo_sem_coluna_de_custo_falha_com_mensagem_util(tmp_path):
    caminho = tmp_path / "ruim.csv"
    caminho.write_text("produto;preco\nmesa;10\n", encoding="utf-8")
    with pytest.raises(ValueError, match="coluna de custo"):
        carregar_custos(caminho)
