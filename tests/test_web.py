"""A pagina local de upload."""

import re

import pytest

from promoml.regras import Regras
from promoml.web import criar_app


@pytest.fixture
def cliente(custos_xlsx):
    app = criar_app(custos_xlsx, Regras())
    app.config["TESTING"] = True
    return app.test_client()


def test_pagina_inicial_mostra_as_regras_em_uso(cliente):
    corpo = cliente.get("/").get_data(as_text=True)
    assert "Aplicar promocoes com margem" in corpo
    assert "5.00%" in corpo and "R$ 10.00" in corpo


def test_pagina_mostra_as_premissas_que_ja_causaram_prejuizo(cliente):
    """Comissao, fonte dos encargos e ajuda do ML tem de estar visiveis.

    Foi justamente o que ficou escondido quando o programa aprovou desconto
    sem margem: nada na tela dizia que a comissao estava zerada.
    """
    from promoml import __version__

    corpo = cliente.get("/").get_data(as_text=True)
    assert "16.50%" in corpo                    # comissao suposta
    assert "Comissão + frete" in corpo
    assert "Ajuda do ML" in corpo
    assert __version__ in corpo                 # da para saber se a copia esta velha


def test_upload_processa_e_oferece_os_downloads(cliente, promo_ml_xlsx):
    with promo_ml_xlsx.open("rb") as arquivo:
        resposta = cliente.post(
            "/aplicar",
            data={"planilha": (arquivo, "promocoes.xlsx")},
            content_type="multipart/form-data",
        )
    assert resposta.status_code == 200
    corpo = resposta.get_data(as_text=True)
    assert "Baixar planilha para o ML" in corpo

    link = re.search(r'href="(/baixar/[^"]+-aplicado\.xlsx)"', corpo).group(1)
    baixado = cliente.get(link)
    assert baixado.status_code == 200
    assert baixado.data[:2] == b"PK"      # xlsx e um zip


def test_upload_sem_arquivo_explica_o_que_falta(cliente):
    resposta = cliente.post("/aplicar", data={}, content_type="multipart/form-data")
    assert resposta.status_code == 400
    assert "Escolha a planilha" in resposta.get_data(as_text=True)


def test_extensao_desconhecida_e_recusada(cliente, tmp_path):
    ruim = tmp_path / "planilha.exe"
    ruim.write_bytes(b"nao importa")
    with ruim.open("rb") as arquivo:
        resposta = cliente.post(
            "/aplicar",
            data={"planilha": (arquivo, "planilha.exe")},
            content_type="multipart/form-data",
        )
    assert resposta.status_code == 400
    assert "envie um arquivo" in resposta.get_data(as_text=True)


@pytest.mark.parametrize(
    "caminho",
    ["/baixar/qualquer/../../etc/passwd", "/baixar/x/..%2f..%2fetc%2fpasswd", "/baixar/x/y.xlsx"],
)
def test_download_nao_sai_da_pasta_de_trabalho(cliente, caminho):
    assert cliente.get(caminho).status_code == 404
