"""A linha de comando: o caminho que o usuario roda de verdade."""

from pathlib import Path

import pytest

from promoml.cli import main


def test_aplicar_gera_planilha_relatorios_e_pendencias(
    promo_ml_xlsx, custos_xlsx, tmp_path, capsys
):
    saida = tmp_path / "saida"
    codigo = main(
        ["aplicar", str(promo_ml_xlsx), "--custos", str(custos_xlsx), "--saida", str(saida)]
    )
    assert codigo == 0

    base = promo_ml_xlsx.stem
    assert (saida / f"{base}-aplicado.xlsx").exists()
    assert (saida / f"{base}-decisoes.csv").exists()
    assert (saida / f"{base}-relatorio.html").exists()
    assert (saida / f"{base}-pendencias.csv").exists()

    texto = capsys.readouterr().out
    assert "entram na promocao" in texto
    assert "ATENCAO" in texto     # avisa sobre o anuncio sem custo


def test_pendencias_saem_prontas_para_virar_tabela_de_custos(
    promo_ml_xlsx, custos_xlsx, tmp_path
):
    saida = tmp_path / "saida"
    main(["aplicar", str(promo_ml_xlsx), "--custos", str(custos_xlsx), "--saida", str(saida)])
    linhas = (saida / f"{promo_ml_xlsx.stem}-pendencias.csv").read_text(
        encoding="utf-8-sig"
    ).splitlines()
    assert linhas[0].split(";") == ["mlb", "sku", "titulo", "preco_atual", "preco_proposto_ml", "custo"]
    assert linhas[1].startswith("MLB9999999999")
    assert linhas[1].endswith(";")   # coluna custo vazia, para preencher


def _participando(texto: str) -> int:
    linha = next(l for l in texto.splitlines() if "entram na promocao" in l)
    return int(linha.rsplit(" ", 1)[1])


def test_ajustes_da_linha_de_comando_valem_sobre_o_padrao(
    promo_ml_xlsx, custos_xlsx, tmp_path, capsys
):
    comum = ["aplicar", str(promo_ml_xlsx), "--custos", str(custos_xlsx), "--saida", str(tmp_path / "s")]
    main(comum)
    padrao = _participando(capsys.readouterr().out)

    main(comum + ["--margem", "60%", "--estrategia", "so_proposta"])
    exigente = _participando(capsys.readouterr().out)

    assert padrao > 0
    assert exigente < padrao


def test_conferir_mostra_as_colunas_reconhecidas(promo_ml_xlsx, custos_xlsx, capsys):
    assert main(["conferir", str(promo_ml_xlsx), "--custos", str(custos_xlsx)]) == 0
    texto = capsys.readouterr().out
    assert "perfil detectado ....... mercado_livre" in texto
    assert "'ITEM_ID'" in texto
    assert "'Custo'" in texto


def test_custos_ausentes_dao_erro_claro(promo_ml_xlsx, tmp_path, capsys):
    codigo = main(
        ["aplicar", str(promo_ml_xlsx), "--custos", str(tmp_path / "nao_existe.xlsx"),
         "--saida", str(tmp_path)]
    )
    assert codigo == 1
    assert "tabela de custos nao encontrada" in capsys.readouterr().err


def test_planilha_ausente_da_erro_claro(custos_xlsx, tmp_path, capsys):
    codigo = main(
        ["aplicar", str(tmp_path / "sumiu.xlsx"), "--custos", str(custos_xlsx),
         "--saida", str(tmp_path)]
    )
    assert codigo == 1
    assert "nao encontrada" in capsys.readouterr().err
