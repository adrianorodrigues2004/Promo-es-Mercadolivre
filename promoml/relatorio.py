"""Relatorios da rodada: o que foi decidido, por que, e o que ficou faltando.

Sao tres saidas com publicos diferentes: o CSV de decisoes para conferir linha
a linha, o CSV de pendencias para completar a tabela de custos, e o resumo de
texto para ler no terminal logo depois de rodar.
"""

from __future__ import annotations

import csv
from decimal import Decimal
from pathlib import Path

from .dinheiro import ZERO, formatar
from .motor import Rodada

CABECALHO_DECISOES = [
    "linha",
    "mlb",
    "sku",
    "titulo",
    "campanha",
    "participar",
    "preco_atual",
    "preco_proposto_ml",
    "preco_aplicado",
    "desconto_aplicado_%",
    "piso_de_margem",
    "custo",
    "lucro",
    "margem_%",
    "comissao_frete",
    "ajuda_do_ml",
    "custo_casado_por",
    "preco_editavel",
    "motivo",
]

CABECALHO_PENDENCIAS = ["mlb", "sku", "titulo", "preco_atual", "preco_proposto_ml", "custo"]


def escrever_decisoes(rodada: Rodada, caminho: str | Path) -> Path:
    """CSV com uma linha por anuncio e a conta inteira aberta."""
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with caminho.open("w", encoding="utf-8-sig", newline="") as saida:
        escritor = csv.writer(saida, delimiter=";")
        escritor.writerow(CABECALHO_DECISOES)
        for d in rodada.decisoes:
            escritor.writerow(
                [
                    d.linha,
                    d.id,
                    d.sku,
                    d.titulo,
                    d.campanha,
                    "SIM" if d.participar else "NAO",
                    formatar(d.preco_atual),
                    formatar(d.preco_proposto),
                    formatar(d.preco_aplicado),
                    formatar(d.desconto_aplicado_pct),
                    formatar(d.piso),
                    formatar(d.custo),
                    formatar(d.lucro),
                    formatar(d.margem_pct * 100) if d.margem_pct is not None else "",
                    formatar(d.encargos_usados),
                    formatar(d.ajuda_ml),
                    d.custo_via,
                    "sim" if d.preco_editavel else "nao",
                    d.motivo,
                ]
            )
    return caminho


def escrever_pendencias(rodada: Rodada, caminho: str | Path) -> Path:
    """CSV dos anuncios sem custo, pronto para preencher e usar como custos.

    A coluna ``custo`` sai vazia de proposito: e o unico dado que falta. Depois
    de preenchida, o arquivo ja serve de entrada em ``--custos``, e esses
    anuncios passam a ser decididos na proxima rodada.
    """
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with caminho.open("w", encoding="utf-8-sig", newline="") as saida:
        escritor = csv.writer(saida, delimiter=";")
        escritor.writerow(CABECALHO_PENDENCIAS)
        for d in rodada.pendencias:
            escritor.writerow(
                [d.id, d.sku, d.titulo, formatar(d.preco_atual), formatar(d.preco_proposto), ""]
            )
    return caminho


def resumo_texto(rodada: Rodada, largura: int = 74) -> str:
    """Resumo para o terminal: numeros primeiro, alertas depois."""
    s = rodada.resumo
    linhas = [
        "=" * largura,
        f"  RESULTADO DA RODADA  ({rodada.perfil.nome})",
        "=" * largura,
        f"  anuncios analisados .......... {s.total}",
        f"  entram na promocao ........... {s.participando}",
        f"     com o preco proposto pelo ML  {s.participando - s.contrapropostas}",
        f"     com preco ajustado por voce   {s.contrapropostas}",
        f"  ficam de fora ................ {s.recusados}",
        f"     por falta de custo ........... {s.sem_custo}",
        f"     por nao caber na margem ...... {s.recusados - s.sem_custo}",
        "-" * largura,
        f"  faturamento previsto ......... R$ {formatar(s.faturamento_previsto)}",
        f"  lucro previsto ............... R$ {formatar(s.lucro_previsto)}",
        f"  margem media ................. {formatar(s.margem_media_pct * 100)}%",
        "-" * largura,
        "  motivos:",
    ]
    for motivo, quantidade in sorted(s.motivos.items(), key=lambda item: -item[1]):
        linhas.append(f"    {quantidade:5}  {motivo}")

    if s.sem_custo:
        linhas += [
            "-" * largura,
            f"  ATENCAO: {s.sem_custo} anuncio(s) ficaram de fora so por falta de custo.",
            "  Preencha a coluna 'custo' no arquivo de pendencias e rode de novo.",
        ]
    for aviso in rodada.avisos:
        linhas.append(f"  aviso: {aviso}")
    linhas.append("=" * largura)
    return "\n".join(linhas)


def escrever_html(rodada: Rodada, caminho: str | Path) -> Path:
    """Pagina unica com o resumo e a tabela completa de decisoes."""
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(montar_html(rodada), encoding="utf-8")
    return caminho


def montar_html(rodada: Rodada) -> str:
    s = rodada.resumo
    cartoes = [
        ("Analisados", str(s.total), ""),
        ("Entram na promocao", str(s.participando), "ok"),
        ("Ficam de fora", str(s.recusados), "fora"),
        ("Sem custo cadastrado", str(s.sem_custo), "alerta" if s.sem_custo else ""),
        ("Lucro previsto", f"R$ {formatar(s.lucro_previsto)}", "ok"),
        ("Margem media", f"{formatar(s.margem_media_pct * 100)}%", ""),
    ]
    html_cartoes = "".join(
        f'<div class="cartao {classe}"><span class="rotulo">{rotulo}</span>'
        f'<strong>{valor}</strong></div>'
        for rotulo, valor, classe in cartoes
    )

    corpo = []
    for d in rodada.decisoes:
        classe = "sim" if d.participar else ("pendente" if d.pendente_de_custo else "nao")
        corpo.append(
            "<tr class='{classe}'><td>{mlb}</td><td class='titulo'>{titulo}</td>"
            "<td class='num'>{atual}</td><td class='num'>{proposto}</td>"
            "<td class='num'>{aplicado}</td><td class='num'>{desconto}</td>"
            "<td class='num'>{piso}</td><td class='num'>{lucro}</td>"
            "<td class='num'>{margem}</td><td>{via}</td><td>{motivo}</td></tr>".format(
                classe=classe,
                mlb=_e(d.id),
                titulo=_e(d.titulo),
                atual=formatar(d.preco_atual),
                proposto=formatar(d.preco_proposto),
                aplicado=formatar(d.preco_aplicado),
                desconto=formatar(d.desconto_aplicado_pct),
                piso=formatar(d.piso),
                lucro=formatar(d.lucro),
                margem=formatar(d.margem_pct * 100) if d.margem_pct is not None else "",
                via=_e(d.custo_via),
                motivo=_e(d.motivo),
            )
        )

    return f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Promocoes - resultado da rodada</title>
<style>{_CSS}</style></head>
<body>
<h1>Resultado da rodada</h1>
<p class="sub">Perfil detectado: <strong>{_e(rodada.perfil.nome)}</strong> &middot;
regra de margem: minimo {formatar(rodada.regras.margem_min_pct * 100)}%, e pelo menos
R$ {formatar(rodada.regras.lucro_min_abaixo_limiar)} de lucro abaixo de
R$ {formatar(rodada.regras.limiar_preco_baixo)}.</p>
<div class="cartoes">{html_cartoes}</div>
<table>
<thead><tr><th>MLB</th><th>Titulo</th><th>Preco atual</th><th>Proposta ML</th>
<th>Preco aplicado</th><th>Desc. %</th><th>Piso</th><th>Lucro</th><th>Margem %</th>
<th>Custo de</th><th>Motivo</th></tr></thead>
<tbody>{''.join(corpo)}</tbody></table>
</body></html>"""


_CSS = """
:root{--fundo:#f6f7f9;--carta:#fff;--borda:#e3e6ea;--texto:#1c2024;--suave:#666e78;
--ok:#137a3f;--nao:#a8331f;--alerta:#8a6100}
*{box-sizing:border-box}
body{margin:0;padding:24px;background:var(--fundo);color:var(--texto);
font:14px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
h1{margin:0 0 4px;font-size:22px}
.sub{margin:0 0 20px;color:var(--suave)}
.cartoes{display:flex;flex-wrap:wrap;gap:12px;margin-bottom:22px}
.cartao{background:var(--carta);border:1px solid var(--borda);border-radius:10px;
padding:12px 16px;min-width:150px;display:flex;flex-direction:column;gap:2px}
.cartao .rotulo{color:var(--suave);font-size:12px}
.cartao strong{font-size:20px}
.cartao.ok strong{color:var(--ok)}
.cartao.fora strong{color:var(--nao)}
.cartao.alerta strong{color:var(--alerta)}
table{width:100%;border-collapse:collapse;background:var(--carta);
border:1px solid var(--borda);border-radius:10px;overflow:hidden;font-size:13px}
th,td{padding:7px 10px;text-align:left;border-bottom:1px solid var(--borda)}
th{background:#eef1f4;font-weight:600;position:sticky;top:0}
td.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
td.titulo{max-width:320px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
tr.sim td:first-child{box-shadow:inset 3px 0 var(--ok)}
tr.nao td:first-child{box-shadow:inset 3px 0 var(--nao)}
tr.pendente td:first-child{box-shadow:inset 3px 0 var(--alerta)}
tr:hover td{background:#f2f5f8}
"""


def _e(texto: object) -> str:
    return (
        str(texto or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
