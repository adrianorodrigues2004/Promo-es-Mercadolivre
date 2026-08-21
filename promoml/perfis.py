"""Perfis de planilha: como ler, calibrar e preencher cada formato conhecido.

O motor faz sempre a mesma pergunta - "cabe no meu piso de margem?" - mas
planilhas diferentes respondem de formas diferentes. O perfil isola isso:

* ``PerfilML``       - o export nativo de campanhas do Mercado Livre, que traz
  a conta pronta ("Você recebe") e diz, celula a celula, o que pode ser
  alterado e com que palavras;
* ``PerfilGenerico`` - qualquer outra planilha, com as colunas descobertas por
  aproximacao de nome.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from decimal import Decimal

from .colunas import Mapa, detectar_cabecalho, mapear
from .custos import Custo
from .dinheiro import ZERO, centavos, centavos_abaixo, para_decimal, para_percentual
from .planilha import Tabela
from .precificacao import Encargos
from .regras import Regras

# Assinatura do export do Mercado Livre: nomes tecnicos na primeira linha.
COLUNAS_ML = {
    "TITLE": "titulo",
    "ITEM_ID": "id",
    "SKU": "sku",
    "PROMO_NAME": "campanha",
    "ORIGINAL_PRICE": "preco_atual",
    "SELLER_AMOUNT": "desconto_vendedor",
    "MELI_AMOUNT": "rebate_ml",
    "DISCOUNT_PERCENTAGE": "desconto_sugerido",
    "FINAL_PRICE": "preco_sugerido",
    "NEW_RECEIVES": "recebe",
    "STATUS": "status",
    "ACTION": "participar",
    "TARGET_TYPE": "alvo",
    "PROMO_SUB_TYPE": "subtipo",
    "SALE_FEE": "reducao_tarifa",
}
OBRIGATORIAS_ML = ("ITEM_ID", "ORIGINAL_PRICE", "FINAL_PRICE", "ACTION")

# Celula azul-claro = desconto editavel; cinza = proposta fechada.
COR_EDITAVEL = "FFCADDF8"
ALVO_EDITAVEL = "OPTINEABLE"

_MOEDA = re.compile(r"(\d[\d.,]*)")


@dataclass(frozen=True)
class Capacidade:
    """O que a planilha permite fazer nesta linha."""

    pode_alterar_preco: bool
    texto_sim: str
    texto_nao: str


@dataclass(frozen=True)
class Contraproposta:
    """Preco alternativo que o perfil consegue gravar quando a proposta nao cabe."""

    preco: Decimal
    desconto_pct: Decimal | None = None


class PerfilGenerico:
    """Planilha desconhecida: colunas por aproximacao, sem calibragem extra."""

    nome = "generico"

    def __init__(self, tabela: Tabela, regras: Regras):
        linhas = tabela.linhas
        idx = regras.linha_cabecalho - 1 if regras.linha_cabecalho else detectar_cabecalho(linhas)
        cabecalhos = [str(c) if c is not None else "" for c in linhas[idx]]
        forcado = {k: v for k, v in (regras.colunas or {}).items() if isinstance(v, str)}
        self.tabela = tabela
        self.regras = regras
        self.mapa = mapear(cabecalhos, idx, forcado=forcado)
        self.primeira_linha = idx + 1

    def ler(self, numero: int, campo: str) -> object:
        return self.tabela.valor(numero, self.mapa.get(campo))

    def capacidade(self, numero: int) -> Capacidade:
        return Capacidade(True, self.regras.texto_sim, self.regras.texto_nao)

    def encargos(self, numero: int, custo: Custo, regras: Regras) -> Encargos:
        """Encargos do custo, com a comissao da planilha tendo prioridade."""
        encargos = custo.encargos(regras)
        comissao = para_percentual(self.ler(numero, "comissao"))
        if comissao is not None and ZERO <= comissao < 1:
            encargos = replace(encargos, comissao_pct=comissao)
        return encargos

    def contraproposta(self, numero: int, piso: Decimal, regras: Regras) -> Contraproposta | None:
        """Maior desconto possivel numa planilha comum, limitado pelo preco atual."""
        base = para_decimal(self.ler(numero, "preco_atual")) or para_decimal(
            self.ler(numero, "preco_sugerido")
        )
        if base is None or base <= ZERO:
            return None

        teto = base
        desconto_min = para_percentual(self.ler(numero, "desconto_min"))
        if desconto_min is None or desconto_min <= ZERO:
            desconto_min = regras.desconto_min_padrao_pct
        if desconto_min and desconto_min > ZERO:
            if desconto_min >= 1:
                return None
            teto = min(teto, base * (Decimal(1) - desconto_min))
        preco_max = para_decimal(self.ler(numero, "preco_max"))
        if preco_max is not None and preco_max > ZERO:
            teto = min(teto, preco_max)

        teto = centavos_abaixo(teto)
        if piso > teto:
            return None
        preco = min(regras.arredondar(piso), teto)
        if preco < piso:
            return None
        return Contraproposta(preco=centavos(preco), desconto_pct=pct_desconto(base, preco))

    def escrever(self, numero: int, decisao, regras: Regras) -> None:
        """Preenche participacao e preco nas colunas nativas da planilha."""
        cap = self.capacidade(numero)
        idx_participar = self.mapa.get("participar")
        if idx_participar is not None:
            self.tabela.escrever(
                numero, idx_participar, cap.texto_sim if decisao.participar else cap.texto_nao
            )
        idx_preco = self.mapa.get("preco_sugerido")
        if idx_preco is None:
            return
        if decisao.participar:
            self.tabela.escrever(numero, idx_preco, decisao.preco_aplicado)
        elif idx_participar is None:
            # Sem coluna de participacao, preco em branco e o "nao participar".
            self.tabela.escrever(numero, idx_preco, None)


class PerfilML(PerfilGenerico):
    """Export nativo de campanhas do Mercado Livre.

    Duas coisas so existem aqui e mudam a qualidade da decisao:

    1. **"Você recebe"** ja e o liquido do anuncio depois da comissao, do frete
       e da reducao de tarifa. Com ele o motor calibra os encargos reais do
       anuncio em vez de confiar em frete e comissao anotados a mao.
    2. **A cor da celula e a lista suspensa** dizem, por linha, se o desconto
       pode ser renegociado e com que palavras responder - "Aplicar proposta"
       numa linha, "Participar" na outra.
    """

    nome = "mercado_livre"

    def __init__(self, tabela: Tabela, regras: Regras, idx_cabecalho: int, indices: dict[str, int]):
        self.tabela = tabela
        self.regras = regras
        cabecalhos = [str(c) if c is not None else "" for c in tabela.linhas[idx_cabecalho]]
        self.mapa = Mapa(
            linha_cabecalho=idx_cabecalho,
            indices=indices,
            cabecalhos=cabecalhos,
            confianca={campo: 1000 for campo in indices},
        )
        self.primeira_linha = self._primeira_linha_de_dados(idx_cabecalho)

    @classmethod
    def detectar(cls, tabela: Tabela, regras: Regras) -> "PerfilML | None":
        """Reconhece o export pelos nomes tecnicos da primeira linha."""
        for idx, linha in enumerate(tabela.linhas[:5]):
            nomes = {str(c).strip().upper(): j for j, c in enumerate(linha) if c is not None}
            if all(col in nomes for col in OBRIGATORIAS_ML):
                indices = {campo: nomes[col] for col, campo in COLUNAS_ML.items() if col in nomes}
                return cls(tabela, regras, idx, indices)
        return None

    def _primeira_linha_de_dados(self, idx_cabecalho: int) -> int:
        """Pula as linhas de titulo e instrucao ate achar o primeiro MLB."""
        coluna_id = self.mapa.get("id")
        for numero in range(idx_cabecalho + 1, len(self.tabela.linhas)):
            valor = str(self.tabela.valor(numero, coluna_id) or "").strip()
            if re.fullmatch(r"[A-Z]{2,4}\d{6,}", valor.upper()):
                return numero
        return idx_cabecalho + 1

    def capacidade(self, numero: int) -> Capacidade:
        """Le da propria celula o que o Mercado Livre permite nesta linha."""
        opcoes = self.tabela.opcoes_validacao(numero, self.mapa.get("participar"))
        sim, nao = (opcoes[0], opcoes[1]) if opcoes and len(opcoes) >= 2 else ("Participar", "Não participar")

        idx_desconto = self.mapa.get("desconto_sugerido")
        cor = self.tabela.cor_de_fundo(numero, idx_desconto) if idx_desconto is not None else None
        if cor:
            editavel = cor.upper() == COR_EDITAVEL
        else:
            alvo = str(self.ler(numero, "alvo") or "").strip().upper()
            editavel = alvo == ALVO_EDITAVEL
        return Capacidade(editavel, sim, nao)

    def encargos(self, numero: int, custo: Custo, regras: Regras) -> Encargos:
        """Encargos calibrados pelo "Você recebe" do proprio Mercado Livre.

        No preco proposto vale a identidade::

            recebe = preco - comissao - frete + reducao_de_tarifa

        Dai sai ``comissao + frete`` de verdade. A comissao percentual vem da
        tabela de custos (Classico ou Premium) e o resto vira frete implicito -
        que e o que o ML realmente cobra, sem depender de anotacao manual.

        A contrapartida do ML encolhe junto com o desconto: ao propor um preco
        maior o motor assume que a ajuda diminui na mesma proporcao, o que
        mantem a conta pessimista em vez de otimista.
        """
        base = custo.encargos(regras)
        preco_proposto = para_decimal(self.ler(numero, "preco_sugerido"))
        recebe = _valor_monetario(self.ler(numero, "recebe"))
        if preco_proposto is None or recebe is None or preco_proposto <= ZERO:
            return base

        rebate = para_decimal(self.ler(numero, "rebate_ml")) or ZERO
        encargos_reais = preco_proposto + rebate - recebe
        if encargos_reais < ZERO:
            return base

        comissao = base.comissao_pct
        frete = encargos_reais - comissao * preco_proposto
        if frete < ZERO:
            # Comissao anotada maior que a real: o ML manda, frete zera.
            comissao = encargos_reais / preco_proposto
            frete = ZERO

        preco_original = para_decimal(self.ler(numero, "preco_atual"))
        inclinacao, credito = self._rebate_proporcional(rebate, preco_original, preco_proposto)
        return replace(
            base,
            comissao_pct=comissao + inclinacao,
            frete=frete,
            taxa_fixa=ZERO,
            rebate=credito,
        )

    @staticmethod
    def _rebate_proporcional(
        rebate: Decimal, preco_original: Decimal | None, preco_proposto: Decimal
    ) -> tuple[Decimal, Decimal]:
        """Transforma o rebate variavel em (inclinacao, credito fixo).

        Se a ajuda do ML cai junto com o desconto, ela vale
        ``k * (preco_original - preco)``. Isso e linear no preco, entao entra no
        modelo como um percentual a mais (``k``) e um credito fixo
        (``k * preco_original``), sem precisar de calculo iterativo.
        """
        if rebate <= ZERO or preco_original is None:
            return ZERO, rebate
        desconto = preco_original - preco_proposto
        if desconto <= ZERO:
            return ZERO, rebate
        inclinacao = rebate / desconto
        return inclinacao, inclinacao * preco_original

    def contraproposta(self, numero: int, piso: Decimal, regras: Regras) -> Contraproposta | None:
        """Maior desconto inteiro cujo preco final ainda fica acima do piso.

        O preco sai do proprio percentual escolhido, e nao de um arredondamento
        por fora: a planilha exige que os dois numeros se correspondam.
        """
        base = para_decimal(self.ler(numero, "preco_atual"))
        if base is None or base <= ZERO or piso > base:
            return None

        folga_pp = (Decimal(1) - piso / base) * 100
        passo = regras.passo_desconto_pp
        desconto = passo * int(folga_pp / passo)
        if desconto <= ZERO or desconto < regras.desconto_min_padrao_pct * 100:
            return None

        preco = centavos(base * (Decimal(1) - desconto / 100))
        return Contraproposta(preco=preco, desconto_pct=desconto) if preco >= piso else None

    def escrever(self, numero: int, decisao, regras: Regras) -> None:
        """Grava a acao e, quando permitido, o novo desconto e preco final.

        O ML exige que preco final e percentual de desconto se correspondam,
        entao os dois saem do mesmo numero: o desconto inteiro escolhido.
        """
        cap = self.capacidade(numero)
        idx_participar = self.mapa.get("participar")
        if idx_participar is not None:
            self.tabela.escrever(
                numero, idx_participar, cap.texto_sim if decisao.participar else cap.texto_nao
            )
        if not decisao.participar or not cap.pode_alterar_preco:
            return
        if decisao.desconto_aplicado_pct is None or decisao.preco_aplicado is None:
            return

        idx_desconto = self.mapa.get("desconto_sugerido")
        if idx_desconto is not None:
            self.tabela.escrever(numero, idx_desconto, float(decisao.desconto_aplicado_pct))
        idx_preco = self.mapa.get("preco_sugerido")
        if idx_preco is not None:
            self.tabela.escrever(numero, idx_preco, decisao.preco_aplicado)


def pct_desconto(base: Decimal | None, preco: Decimal) -> Decimal | None:
    """Desconto em pontos percentuais entre o preco cheio e o praticado."""
    if base is None or base <= ZERO:
        return None
    return centavos((base - preco) / base * 100)


def _valor_monetario(valor: object) -> Decimal | None:
    """Extrai o numero de ``"$\xa0116.98\\n(Inclui uma redução...)"``."""
    if valor is None:
        return None
    if isinstance(valor, (int, float, Decimal)):
        return para_decimal(valor)
    texto = str(valor).replace("\xa0", " ")
    encontrado = _MOEDA.search(texto)
    return para_decimal(encontrado.group(1)) if encontrado else None


def escolher_perfil(tabela: Tabela, regras: Regras) -> PerfilGenerico:
    """Perfil do Mercado Livre quando reconhecido; generico caso contrario."""
    return PerfilML.detectar(tabela, regras) or PerfilGenerico(tabela, regras)

