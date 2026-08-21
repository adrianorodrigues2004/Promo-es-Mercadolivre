"""Reconhecimento de cabecalhos, que muda de nome a cada export."""

import pytest

from promoml.colunas import detectar_cabecalho, mapear, normalizar, pontuar


def test_normalizar_tira_acento_e_pontuacao():
    assert normalizar("Preço com Desconto (R$)") == "preco com desconto r"
    assert normalizar(None) == ""


@pytest.mark.parametrize(
    "cabecalhos, esperado",
    [
        (
            ["Código do anúncio", "Variação", "Título do anúncio", "Preço sem desconto",
             "Preço com desconto sugerido", "Desconto sugerido (%)", "Preço mínimo",
             "Participar da promoção?"],
            {"id": 0, "variacao": 1, "titulo": 2, "preco_atual": 3, "preco_sugerido": 4,
             "desconto_sugerido": 5, "preco_min": 6, "participar": 7},
        ),
        (
            ["MLB", "Título", "Preço (R$)", "Preço promocional", "Desconto mínimo", "Aceitar"],
            {"id": 0, "titulo": 1, "preco_atual": 2, "preco_sugerido": 3, "desconto_min": 4,
             "participar": 5},
        ),
        (
            ["Item ID", "SKU", "Nome do produto", "Preço atual", "Novo preço",
             "Preço mínimo permitido", "Custo unitário", "Comissão ML"],
            {"id": 0, "sku": 1, "titulo": 2, "preco_atual": 3, "preco_sugerido": 4,
             "preco_min": 5, "custo": 6, "comissao": 7},
        ),
    ],
)
def test_mapear_reconhece_variacoes_de_nome(cabecalhos, esperado):
    mapa = mapear(cabecalhos, 0)
    for campo, indice in esperado.items():
        assert mapa.get(campo) == indice, f"{campo} deveria ser {cabecalhos[indice]!r}"


def test_coluna_de_preco_nao_vira_coluna_de_desconto():
    """"Preço com desconto sugerido" guarda um preco, nao um percentual."""
    pontos = pontuar("Preço com desconto sugerido")
    assert "preco_sugerido" in pontos
    assert "desconto_sugerido" not in pontos


def test_uma_coluna_nao_atende_a_dois_campos():
    cabecalhos = ["Preço com desconto sugerido", "Desconto sugerido (%)"]
    mapa = mapear(cabecalhos, 0)
    assert mapa.get("preco_sugerido") == 0
    assert mapa.get("desconto_sugerido") == 1


def test_mapeamento_forcado_vence_a_deteccao():
    cabecalhos = ["Preço atual", "Outra coisa qualquer"]
    mapa = mapear(cabecalhos, 0, forcado={"preco_sugerido": "Outra coisa qualquer"})
    assert mapa.get("preco_sugerido") == 1
    assert mapa.get("preco_atual") == 0


def test_mapeamento_forcado_aceita_letra_de_coluna():
    mapa = mapear(["A", "B", "C"], 0, forcado={"titulo": "C"})
    assert mapa.get("titulo") == 2


def test_mapeamento_forcado_reclama_de_coluna_inexistente():
    with pytest.raises(ValueError, match="nao existe"):
        mapear(["Preço"], 0, forcado={"titulo": "Coluna Fantasma"})


def test_detectar_cabecalho_pula_titulo_e_instrucoes():
    linhas = [
        ["Planilha de promoções - Mercado Livre"],
        ["Não altere as colunas bloqueadas"],
        [],
        ["Código do anúncio", "Título", "Preço sem desconto", "Preço com desconto"],
        ["MLB123", "Fone", 99.9, 79.9],
    ]
    assert detectar_cabecalho(linhas) == 3
