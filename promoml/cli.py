"""Linha de comando do promoml.

    python -m promoml aplicar planilha.xlsx
    python -m promoml conferir planilha.xlsx
    python -m promoml web
"""

from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

from . import __version__
from .custos import carregar_custos
from .dinheiro import formatar
from .motor import processar
from .planilha import FormatoNaoSuportado
from .regras import Regras, carregar_regras, regras_de_dict
from .relatorio import escrever_decisoes, escrever_html, escrever_pendencias, resumo_texto

CUSTOS_PADRAO = Path("config/custos.xlsx")
REGRAS_PADRAO = Path("config/regras.yml")


def montar_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="promoml",
        description="Aplica promocoes do Mercado Livre so onde sobra margem.",
    )
    p.add_argument("--version", action="version", version=f"promoml {__version__}")
    sub = p.add_subparsers(dest="comando", required=True)

    aplicar = sub.add_parser("aplicar", help="decide a planilha e grava a copia preenchida")
    aplicar.add_argument("planilha", type=Path, help="export de promocoes do Mercado Livre")
    aplicar.add_argument(
        "--custos",
        type=Path,
        nargs="+",
        help=f"uma ou mais tabelas de custo, as ultimas tem prioridade (padrao: {CUSTOS_PADRAO})",
    )
    aplicar.add_argument("--regras", type=Path, help=f"arquivo de regras (padrao: {REGRAS_PADRAO})")
    aplicar.add_argument("--saida", type=Path, default=Path("saida"), help="pasta de saida")
    aplicar.add_argument("--aba", help="aba da planilha de promocoes")
    aplicar.add_argument("--aba-custos", help="aba da tabela de custos")
    aplicar.add_argument("--margem", help="margem minima, ex.: 5%% ou 0.05")
    aplicar.add_argument("--lucro-minimo", help="lucro minimo em reais abaixo do limiar")
    aplicar.add_argument("--limiar", help="preco abaixo do qual vale o lucro minimo em reais")
    aplicar.add_argument("--imposto", help="aliquota de imposto, ex.: 11.5%%")
    aplicar.add_argument("--estrategia", choices=("sugerido", "maior_desconto", "so_proposta"))
    aplicar.add_argument(
        "--sem-diagnostico",
        action="store_true",
        help="nao acrescenta as colunas PROMO no fim da planilha",
    )

    conferir = sub.add_parser(
        "conferir", help="mostra colunas detectadas sem decidir nada (use antes da primeira rodada)"
    )
    conferir.add_argument("planilha", type=Path)
    conferir.add_argument("--custos", type=Path, nargs="+")
    conferir.add_argument("--regras", type=Path)
    conferir.add_argument("--aba")
    conferir.add_argument("--aba-custos")

    web = sub.add_parser("web", help="sobe a pagina para arrastar a planilha e baixar o resultado")
    web.add_argument("--porta", type=int, default=8000)
    web.add_argument("--custos", type=Path)
    web.add_argument("--regras", type=Path)
    return p


def _regras_do_argv(args) -> Regras:
    caminho = args.regras or (REGRAS_PADRAO if REGRAS_PADRAO.exists() else None)
    regras = carregar_regras(caminho)
    ajustes = {
        "margem_min_pct": getattr(args, "margem", None),
        "lucro_min_abaixo_limiar": getattr(args, "lucro_minimo", None),
        "limiar_preco_baixo": getattr(args, "limiar", None),
        "imposto_pct": getattr(args, "imposto", None),
        "estrategia": getattr(args, "estrategia", None),
    }
    return regras_de_dict({k: v for k, v in ajustes.items() if v is not None}, base=regras)


def _caminhos_custos(args) -> list[Path]:
    """Tabelas de custo a usar; as ultimas completam e corrigem as primeiras."""
    caminhos = args.custos or [CUSTOS_PADRAO]
    if isinstance(caminhos, (str, Path)):
        caminhos = [caminhos]
    for caminho in caminhos:
        if not Path(caminho).exists():
            raise FileNotFoundError(
                f"tabela de custos nao encontrada em '{caminho}'. "
                "Informe com --custos ou salve o arquivo em config/custos.xlsx"
            )
    return [Path(c) for c in caminhos]


def comando_aplicar(args) -> int:
    regras = _regras_do_argv(args)
    custos = carregar_custos(_caminhos_custos(args), regras, aba=args.aba_custos)
    for aviso in custos.avisos[:10]:
        print(f"  custos: {aviso}", file=sys.stderr)

    rodada = processar(
        args.planilha, custos, regras, aba=args.aba, diagnostico=not args.sem_diagnostico
    )

    destino = args.saida
    base = Path(args.planilha).stem
    planilha = rodada.salvar(destino / f"{base}-aplicado.xlsx")
    decisoes = escrever_decisoes(rodada, destino / f"{base}-decisoes.csv")
    html = escrever_html(rodada, destino / f"{base}-relatorio.html")

    print(resumo_texto(rodada))
    print(f"\n  planilha para reenviar ao ML .. {planilha}")
    print(f"  relatorio visual .............. {html}")
    print(f"  decisoes linha a linha ........ {decisoes}")
    if rodada.pendencias:
        pendencias = escrever_pendencias(rodada, destino / f"{base}-pendencias.csv")
        print(f"  custos a completar ............ {pendencias}")
    return 0


def comando_conferir(args) -> int:
    """Mostra o que o programa entendeu de cada arquivo, sem decidir nada."""
    from .perfis import escolher_perfil
    from .planilha import abrir

    regras = _regras_do_argv(args)
    tabela = abrir(args.planilha, args.aba)
    perfil = escolher_perfil(tabela, regras)
    print(f"planilha de promocoes: {args.planilha}")
    print(f"  perfil detectado ....... {perfil.nome}")
    print(f"  aba .................... {getattr(tabela, 'aba', '(arquivo de texto)')}")
    print(f"  cabecalho na linha ..... {perfil.mapa.linha_cabecalho + 1}")
    print(f"  dados a partir da linha  {perfil.primeira_linha + 1}")
    print("  colunas reconhecidas:")
    for campo in sorted(perfil.mapa.indices):
        print(f"     {campo:20} -> {perfil.mapa.nome(campo)!r}")
    nao_usadas = [
        c for i, c in enumerate(perfil.mapa.cabecalhos)
        if str(c).strip() and i not in set(perfil.mapa.indices.values())
    ]
    if nao_usadas:
        print(f"  colunas ignoradas: {nao_usadas}")

    caminhos = args.custos or [CUSTOS_PADRAO]
    if all(Path(c).exists() for c in caminhos):
        custos = carregar_custos(caminhos, regras, aba=args.aba_custos)
        print(f"\ntabela de custos: {', '.join(str(c) for c in caminhos)}")
        print(f"  linhas com custo ....... {len(custos)}")
        print("  colunas reconhecidas:")
        for campo, nome in sorted(custos.campos.items()):
            print(f"     {campo:20} -> {nome!r}")
        for aviso in custos.avisos[:10]:
            print(f"  aviso: {aviso}")
    else:
        faltando = [str(c) for c in caminhos if not Path(c).exists()]
        print(f"\ntabela de custos nao encontrada em: {', '.join(faltando)}")

    print(f"\nregras em uso:")
    print(f"  imposto ................ {formatar(regras.imposto_pct * 100)}%")
    print(f"  margem minima .......... {formatar(regras.margem_min_pct * 100)}%")
    print(
        f"  lucro minimo ........... R$ {formatar(regras.lucro_min_abaixo_limiar)} "
        f"abaixo de R$ {formatar(regras.limiar_preco_baixo)}"
    )
    print(f"  estrategia ............. {regras.estrategia}")
    print(f"  casamento de custos .... {', '.join(regras.metodos_casamento)}")
    return 0


def comando_web(args) -> int:
    from .web import servir

    regras = _regras_do_argv(args)
    servir(porta=args.porta, custos=args.custos or CUSTOS_PADRAO, regras=regras)
    return 0


def main(argv: list[str] | None = None) -> int:
    warnings.filterwarnings("ignore", module="openpyxl")
    args = montar_parser().parse_args(argv)
    comandos = {"aplicar": comando_aplicar, "conferir": comando_conferir, "web": comando_web}
    try:
        return comandos[args.comando](args)
    except (FileNotFoundError, ValueError, FormatoNaoSuportado) as erro:
        print(f"erro: {erro}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
