"""Tabela de custos: quanto voce paga em cada produto, e ajustes por anuncio.

Le a planilha de precificacao (a mesma que ja alimenta a coluna "Anunciar"),
usando MLB/SKU como chave. Cada linha pode trazer encargos proprios - frete,
comissao, imposto, rebate - que valem so naquele anuncio e sobrescrevem as
regras globais. E o que permite tratar Classico (11,5%) e Premium (16,5%) na
mesma rodada.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from .colunas import detectar_cabecalho, mapear, normalizar
from .dinheiro import ZERO, para_decimal, para_percentual
from .precificacao import Encargos
from .regras import Regras

# Detectar margem/lucro exige a palavra "minim*": "Margem Desejada" e "Lucro
# Liquido" sao outra coisa e nao podem virar regra de corte sem querer.
PADROES_CUSTOS: dict[str, list[tuple[str, int]]] = {
    "id": [
        (r"^mlb", 100),
        (r"(codigo|cod|id)\D{0,12}(anuncio|item|produto|publicacao)", 98),
        (r"^codigo", 90),
        (r"^(id|item[_ ]?id)$", 70),
    ],
    "sku": [(r"\bsku\b", 100), (r"codigo.{0,10}(vendedor|interno|proprio)", 95)],
    "variacao": [(r"varia(cao|tion)", 90)],
    "custo": [
        (r"^custo", 100),
        (r"(preco|valor).{0,10}(de)?.{0,6}custo", 98),
        (r"valor.{0,10}(pago|de compra)", 95),
        (r"custo.{0,10}(unitario|do produto)", 92),
    ],
    "comissao_pct": [
        (r"comissao", 100),
        (r"tarifa", 95),
        (r"taxa.{0,6}(de)?.{0,6}(venda|marketplace|ml|mercado)", 92),
        (r"^taxa\b", 80),
    ],
    "imposto_pct": [(r"^imposto", 100), (r"imposto", 95), (r"\btributo", 90)],
    "frete": [(r"^frete", 100), (r"frete", 95), (r"custo.{0,6}(de)?.{0,6}envio", 85)],
    "taxa_fixa": [(r"taxa.{0,6}fixa", 100), (r"custo.{0,6}fixo", 90)],
    "rebate": [(r"rib?ai?t", 100), (r"rebate", 100), (r"bonifica", 90), (r"subsidio", 90)],
    "cupom_pct": [(r"cupom.{0,8}(%|pct|percent)", 100), (r"^cupom$", 70)],
    "preco_atual": [(r"preco.{0,10}(atual|original|cheio|de lista)", 100)],
    "margem_min_pct": [(r"margem.{0,12}(minima|minimo|min\b)", 100)],
    "lucro_min": [(r"lucro.{0,12}(minimo|min\b)", 100)],
    "titulo": [(r"^(titulo|nome|produto|descricao)", 60)],
}

# Nomes de aba preferidos quando o arquivo de custos tem varias.
_ABAS_PREFERIDAS = (r"mercado.?l[ií]vre", r"^ml$", r"^meli$")

_SOBRESCRITAS_PCT = ("comissao_pct", "imposto_pct", "margem_min_pct")
_SOBRESCRITAS_VAL = ("frete", "taxa_fixa")
# Encargos que descrevem o anuncio e viajam direto para ``Encargos``.
_ENCARGOS_DIRETOS = ("rebate", "cupom_pct")

# Ordem de confianca. "titulo" fica de fora do padrao: nomes parecidos de
# produtos diferentes ja causaram casamento errado nos testes com dados reais.
METODOS_PADRAO = ("mlb", "sku", "preco")
METODOS_VALIDOS = ("mlb", "sku", "preco", "titulo")


@dataclass(frozen=True)
class Custo:
    """Uma linha da tabela de custos."""

    custo: Decimal
    id: str = ""
    sku: str = ""
    variacao: str = ""
    titulo: str = ""
    preco_atual: Decimal | None = None
    origem_linha: int = 0
    sobrescritas: dict[str, Decimal] = field(default_factory=dict)

    def regras_aplicadas(self, regras: Regras) -> Regras:
        """Regras globais com as sobrescritas desta linha por cima."""
        ajustes = {k: v for k, v in self.sobrescritas.items() if k not in _ENCARGOS_DIRETOS}
        lucro_min = ajustes.pop("lucro_min", None)
        if lucro_min is not None:
            ajustes["lucro_min_abaixo_limiar"] = lucro_min
            ajustes["lucro_min_acima_limiar"] = lucro_min
        return regras.com_ajustes(**ajustes) if ajustes else regras

    def encargos(self, regras: Regras) -> Encargos:
        """Encargos deste anuncio, ja com as sobrescritas aplicadas."""
        efetivas = self.regras_aplicadas(regras)
        extras = {c: self.sobrescritas[c] for c in _ENCARGOS_DIRETOS if c in self.sobrescritas}
        return Encargos.de_regras(self.custo, efetivas, **extras)


class TabelaDeCustos:
    """Indice de custos consultavel por MLB, SKU, variacao e titulo."""

    def __init__(self, itens: list[Custo], avisos: list[str] | None = None, campos: dict | None = None):
        self.itens = itens
        self.avisos = avisos or []
        self.campos = campos or {}
        self._por_id_variacao: dict[tuple[str, str], Custo] = {}
        self._por_id: dict[str, Custo] = {}
        self._por_digitos: dict[str, Custo] = {}
        self._por_sku: dict[str, Custo] = {}
        self._por_titulo: dict[str, Custo] = {}
        self._titulos_ambiguos: set[str] = set()
        self._por_preco: dict[Decimal, list[Custo]] = {}
        for item in itens:
            if item.id and item.variacao:
                self._por_id_variacao.setdefault((chave(item.id), chave(item.variacao)), item)
            if item.id:
                self._por_id.setdefault(chave(item.id), item)
                digitos = so_digitos(item.id)
                if digitos:
                    self._por_digitos.setdefault(digitos, item)
            if item.sku:
                self._por_sku.setdefault(chave(item.sku), item)
            if item.preco_atual and item.preco_atual > ZERO:
                self._por_preco.setdefault(_preco_chave(item.preco_atual), []).append(item)
            if item.titulo:
                alvo = normalizar(item.titulo)
                # Um titulo que aparece com custos diferentes nao serve de chave.
                if alvo in self._por_titulo and self._por_titulo[alvo].custo != item.custo:
                    self._titulos_ambiguos.add(alvo)
                self._por_titulo.setdefault(alvo, item)

    def __len__(self) -> int:
        return len(self.itens)

    def buscar(
        self,
        id_anuncio: str = "",
        sku: str = "",
        variacao: str = "",
        titulo: str = "",
        preco_atual: Decimal | None = None,
        metodos: tuple[str, ...] = METODOS_PADRAO,
    ) -> tuple[Custo | None, str]:
        """Procura o custo do anuncio, do metodo mais confiavel ao menos.

        ``mlb`` e ``sku`` sao identidade e nao erram. ``preco`` casa pelo preco
        atual do anuncio - forte porque a tabela de precificacao acompanha o
        preco de cada anuncio - e recusa candidatos empatados com custos
        diferentes em vez de chutar. ``titulo`` so aceita nome identico.

        Devolve o custo e o metodo, para o relatorio dizer de onde veio.
        """
        cid, csku, cvar = chave(id_anuncio), chave(sku), chave(variacao)
        if "mlb" in metodos and cid:
            if cvar:
                achado = self._por_id_variacao.get((cid, cvar))
                if achado:
                    return achado, "MLB+variacao"
            if cid in self._por_id:
                return self._por_id[cid], "MLB"
            digitos = so_digitos(cid)
            if digitos and digitos in self._por_digitos:
                return self._por_digitos[digitos], "MLB (numero)"
        if "sku" in metodos and csku and csku in self._por_sku:
            return self._por_sku[csku], "SKU"
        if "preco" in metodos and preco_atual:
            achado, via = self._buscar_por_preco(preco_atual, titulo)
            if achado:
                return achado, via
        if "titulo" in metodos and titulo:
            alvo = normalizar(titulo)
            if alvo and alvo not in self._titulos_ambiguos and alvo in self._por_titulo:
                return self._por_titulo[alvo], "titulo identico"
        return None, ""

    def _buscar_por_preco(
        self, preco_atual: Decimal, titulo: str
    ) -> tuple[Custo | None, str]:
        """Casa pelo preco atual, usando o titulo so para desempatar.

        Candidatos com o mesmo preco mas custos diferentes sao ambiguos: em vez
        de escolher um, devolve nada e o anuncio vai para as pendencias. Errar o
        custo aqui vale mais caro que deixar de participar de uma promocao.
        """
        candidatos = self._por_preco.get(_preco_chave(preco_atual), [])
        if not candidatos:
            return None, ""
        if len({c.custo for c in candidatos}) == 1:
            return candidatos[0], "preco atual"

        alvo = _palavras(titulo)
        if not alvo:
            return None, ""
        pontuados = []
        for candidato in candidatos:
            palavras = _palavras(candidato.titulo)
            # So desempata quem tem o nome inteiro contido no titulo do anuncio.
            if palavras and palavras <= alvo:
                pontuados.append((len(palavras), candidato))
        if not pontuados:
            return None, ""
        melhor = max(n for n, _ in pontuados)
        finalistas = [c for n, c in pontuados if n == melhor]
        if len({c.custo for c in finalistas}) > 1:
            return None, ""
        return finalistas[0], "preco + titulo"


def chave(valor: object) -> str:
    """Normaliza identificador: ``"mlb-123 456"`` e ``"MLB123456"`` viram o mesmo."""
    texto = str(valor or "").strip()
    if texto.endswith(".0") and texto[:-2].isdigit():
        texto = texto[:-2]
    return "".join(c for c in texto.upper() if c.isalnum())


def so_digitos(valor: object) -> str:
    """Parte numerica do identificador - ``MLB4090546705`` -> ``4090546705``."""
    return "".join(c for c in str(valor or "") if c.isdigit())


def escolher_aba(caminho: Path, aba: str | None) -> str | None:
    """Preferir a aba do Mercado Livre quando o arquivo tem varias."""
    if aba:
        return aba
    from .planilha import abas

    disponiveis = abas(caminho)
    for padrao in _ABAS_PREFERIDAS:
        for nome in disponiveis:
            if re.search(padrao, normalizar(nome)):
                return nome
    return None


def carregar_custos(
    caminhos: str | Path | Sequence[str | Path],
    regras: Regras | None = None,
    aba: str | None = None,
) -> TabelaDeCustos:
    """Le uma ou varias tabelas de custo e devolve o indice pronto para consulta.

    Com mais de um arquivo, os ultimos tem prioridade: e assim que o arquivo de
    pendencias preenchido **completa** a planilha de precificacao em vez de
    substituir ela, e que uma correcao pontual vence o valor antigo.
    """
    lista = [caminhos] if isinstance(caminhos, (str, Path)) else list(caminhos)
    if not lista:
        raise ValueError("nenhuma tabela de custos informada")

    tabelas = [_carregar_uma(Path(c), regras, aba) for c in lista]
    if len(tabelas) == 1:
        return tabelas[0]

    # Ultimo arquivo primeiro: o indice guarda a primeira ocorrencia de cada chave.
    itens, avisos, campos = [], [], {}
    for tabela in reversed(tabelas):
        itens.extend(tabela.itens)
    for tabela in tabelas:
        avisos.extend(tabela.avisos)
        campos.update(tabela.campos)
    return TabelaDeCustos(itens, avisos, campos)


def _carregar_uma(caminho: Path, regras: Regras | None, aba: str | None) -> TabelaDeCustos:
    from .planilha import abrir

    caminho = Path(caminho)
    if not caminho.exists():
        raise FileNotFoundError(f"tabela de custos nao encontrada: {caminho}")

    linhas = abrir(caminho, escolher_aba(caminho, aba)).linhas
    if not linhas:
        raise ValueError(f"{caminho}: arquivo de custos vazio")

    idx_cabecalho = detectar_cabecalho(linhas, tabela=PADROES_CUSTOS)
    cabecalhos = [str(c) if c is not None else "" for c in linhas[idx_cabecalho]]
    forcado = (regras.colunas or {}).get("custos") if regras else None
    mapa = mapear(
        cabecalhos,
        idx_cabecalho,
        forcado=forcado if isinstance(forcado, dict) else None,
        tabela=PADROES_CUSTOS,
    )

    lidos = [c for c in cabecalhos if str(c).strip()]
    if "custo" not in mapa.indices:
        raise ValueError(f"{caminho}: nao encontrei a coluna de custo. Cabecalhos lidos: {lidos}")
    if not {"id", "sku"} & set(mapa.indices):
        raise ValueError(
            f"{caminho}: preciso de uma coluna de MLB ou de SKU para casar com a planilha "
            f"de promocoes. Cabecalhos lidos: {lidos}"
        )

    avisos: list[str] = []
    itens: list[Custo] = []
    vistos: set[tuple[str, str, str]] = set()
    sem_identificador = 0

    for numero, linha in enumerate(linhas[idx_cabecalho + 1 :], start=idx_cabecalho + 2):
        celula = lambda campo: _celula(linha, mapa.get(campo))  # noqa: E731
        custo = para_decimal(celula("custo"))
        id_anuncio, sku = _texto(celula("id")), _texto(celula("sku"))
        titulo = _texto(celula("titulo"))
        if custo is None or custo <= ZERO:
            if custo is not None and custo < ZERO:
                avisos.append(f"linha {numero}: custo negativo em '{titulo or id_anuncio}' - ignorada")
            continue
        if not (id_anuncio or sku):
            sem_identificador += 1

        sobrescritas: dict[str, Decimal] = {}
        for campo in (*_SOBRESCRITAS_PCT, "cupom_pct"):
            valor = para_percentual(celula(campo))
            if valor is not None:
                sobrescritas[campo] = valor
        for campo in (*_SOBRESCRITAS_VAL, "rebate", "lucro_min"):
            valor = para_decimal(celula(campo))
            if valor is not None:
                sobrescritas[campo] = valor

        chave_linha = (chave(id_anuncio), chave(sku), chave(celula("variacao")))
        if any(chave_linha) and chave_linha in vistos:
            avisos.append(
                f"linha {numero}: '{id_anuncio or sku}' repetido - vale a primeira ocorrencia"
            )
        vistos.add(chave_linha)

        itens.append(
            Custo(
                custo=custo,
                id=id_anuncio,
                sku=sku,
                variacao=_texto(celula("variacao")),
                titulo=titulo,
                preco_atual=para_decimal(celula("preco_atual")),
                origem_linha=numero,
                sobrescritas=sobrescritas,
            )
        )

    if not itens:
        raise ValueError(f"{caminho}: nenhuma linha de custo valida encontrada")
    if sem_identificador:
        avisos.append(
            f"{sem_identificador} linha(s) de custo sem MLB/SKU - so serao usadas se o titulo "
            "for identico ao da planilha de promocoes"
        )
    campos = {campo: mapa.nome(campo) for campo in mapa.indices}
    return TabelaDeCustos(itens, avisos, campos)


def _preco_chave(preco: Decimal) -> Decimal:
    return Decimal(preco).quantize(Decimal("0.01"))


_IRRELEVANTES = frozenset(
    "de da do das dos com sem para por em um uma cor tipo modelo moveis movel".split()
)


def _palavras(texto: str) -> frozenset[str]:
    """Palavras significativas de um nome de produto, para desempate."""
    return frozenset(
        p for p in normalizar(texto).replace(",", ".").split()
        if len(p) > 2 and p not in _IRRELEVANTES
    )


def _celula(linha: list[object], idx: int | None) -> object:
    if idx is None or idx >= len(linha):
        return None
    return linha[idx]


def _texto(valor: object) -> str:
    if valor is None:
        return ""
    texto = str(valor).strip()
    if texto.endswith(".0") and texto[:-2].isdigit():
        texto = texto[:-2]
    return texto
