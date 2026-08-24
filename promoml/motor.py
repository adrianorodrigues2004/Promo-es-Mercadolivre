"""Motor de decisao: percorre a planilha de promocoes e resolve anuncio a anuncio.

A pergunta e sempre a mesma: existe um preco que a campanha aceita e que ainda
respeita o piso de margem? Se existe, o anuncio entra com esse preco; se nao
existe, fica de fora com o motivo registrado.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from decimal import Decimal
from pathlib import Path

from .custos import METODOS_PADRAO, TabelaDeCustos
from .dinheiro import ZERO, centavos, para_decimal
from .perfis import Capacidade, PerfilGenerico, escolher_perfil, pct_desconto
from .planilha import Tabela, abrir
from .precificacao import Resultado, avaliar, piso_de_preco
from .regras import Regras

COLUNAS_DIAGNOSTICO = (
    ("participar", "PROMO Participar"),
    ("preco", "PROMO Preco final"),
    ("desconto", "PROMO Desconto %"),
    ("piso", "PROMO Piso R$"),
    ("lucro", "PROMO Lucro R$"),
    ("margem", "PROMO Margem %"),
    ("encargos", "PROMO Comissao+Frete"),
    ("ajuda", "PROMO Ajuda do ML"),
    ("custo_via", "PROMO Custo de"),
    ("motivo", "PROMO Motivo"),
)

# Motivos, em texto curto o bastante para caber na planilha.
SEM_CUSTO = "sem custo cadastrado"
SEM_PRECO = "sem preco na planilha"
SEM_MARGEM = "sem margem: desconto exigido derruba o lucro"
SEM_MARGEM_FIXO = "sem margem e a campanha nao deixa mudar o preco"
INVIAVEL = "imposto + comissao passam do preco: nenhum valor da margem"
ACEITO = "proposta do ML aceita"
CONTRAPROPOSTA = "contraproposta: desconto reduzido para caber na margem"
APROFUNDADO = "desconto ampliado ate o piso de margem"


@dataclass
class Decisao:
    """O que o motor decidiu para uma linha da planilha."""

    linha: int
    id: str = ""
    sku: str = ""
    titulo: str = ""
    campanha: str = ""
    participar: bool = False
    motivo: str = ""
    preco_atual: Decimal | None = None
    preco_proposto: Decimal | None = None
    preco_aplicado: Decimal | None = None
    desconto_proposto_pct: Decimal | None = None
    desconto_aplicado_pct: Decimal | None = None
    piso: Decimal | None = None
    custo: Decimal | None = None
    custo_via: str = ""
    encargos_usados: Decimal | None = None
    ajuda_ml: Decimal = ZERO
    preco_editavel: bool = True
    resultado: Resultado | None = None

    @property
    def lucro(self) -> Decimal | None:
        return self.resultado.lucro if self.resultado else None

    @property
    def margem_pct(self) -> Decimal | None:
        return self.resultado.margem_pct if self.resultado else None

    @property
    def houve_contraproposta(self) -> bool:
        return (
            self.participar
            and self.preco_proposto is not None
            and self.preco_aplicado is not None
            and self.preco_aplicado != self.preco_proposto
        )

    @property
    def pendente_de_custo(self) -> bool:
        return self.motivo == SEM_CUSTO


@dataclass
class Resumo:
    """Contagem final da rodada."""

    total: int = 0
    participando: int = 0
    recusados: int = 0
    sem_custo: int = 0
    contrapropostas: int = 0
    motivos: dict[str, int] = field(default_factory=dict)
    faturamento_previsto: Decimal = ZERO
    lucro_previsto: Decimal = ZERO

    def registrar(self, decisao: Decisao) -> None:
        self.total += 1
        if decisao.participar:
            self.participando += 1
            if decisao.houve_contraproposta:
                self.contrapropostas += 1
            if decisao.resultado:
                self.faturamento_previsto += decisao.resultado.preco_efetivo
                self.lucro_previsto += decisao.resultado.lucro
        else:
            self.recusados += 1
            if decisao.pendente_de_custo:
                self.sem_custo += 1
        self.motivos[decisao.motivo] = self.motivos.get(decisao.motivo, 0) + 1

    @property
    def margem_media_pct(self) -> Decimal:
        if self.faturamento_previsto <= ZERO:
            return ZERO
        return self.lucro_previsto / self.faturamento_previsto


@dataclass
class Rodada:
    """Resultado completo de processar uma planilha."""

    decisoes: list[Decisao]
    resumo: Resumo
    perfil: PerfilGenerico
    tabela: Tabela
    avisos: list[str]
    regras: Regras

    def salvar(self, destino: str | Path) -> Path:
        return self.tabela.salvar(destino)

    @property
    def pendencias(self) -> list[Decisao]:
        """Anuncios que so ficaram de fora por falta de custo cadastrado."""
        return [d for d in self.decisoes if d.pendente_de_custo]


def processar(
    caminho: str | Path,
    custos: TabelaDeCustos,
    regras: Regras | None = None,
    aba: str | None = None,
    diagnostico: bool = True,
) -> Rodada:
    """Le a planilha de promocoes, decide linha a linha e preenche a copia."""
    regras = regras or Regras()
    regras.validar()

    tabela = abrir(caminho, aba)
    if not tabela.linhas:
        raise ValueError(f"{caminho}: planilha vazia")

    perfil = escolher_perfil(tabela, regras)
    avisos = _validar(perfil, caminho)
    colunas_diag = (
        {
            chave: tabela.acrescentar_coluna(titulo, perfil.mapa.linha_cabecalho)
            for chave, titulo in COLUNAS_DIAGNOSTICO
        }
        if diagnostico
        else {}
    )

    decisoes: list[Decisao] = []
    resumo = Resumo()
    for numero in range(perfil.primeira_linha, len(tabela.linhas)):
        if _linha_vazia(tabela.linhas[numero]):
            continue
        decisao = _decidir(perfil, numero, custos, regras)
        decisoes.append(decisao)
        resumo.registrar(decisao)
        perfil.escrever(numero, decisao, regras)
        _gravar_diagnostico(tabela, numero, colunas_diag, decisao, perfil.capacidade(numero))

    return Rodada(
        decisoes=decisoes, resumo=resumo, perfil=perfil, tabela=tabela, avisos=avisos, regras=regras
    )


def _validar(perfil: PerfilGenerico, caminho: str | Path) -> list[str]:
    """Confere se da para trabalhar com as colunas encontradas."""
    campos = set(perfil.mapa.indices)
    lidos = [c for c in perfil.mapa.cabecalhos if str(c).strip()]
    if not {"id", "sku", "titulo"} & campos:
        raise ValueError(
            f"{caminho}: nao encontrei coluna de MLB, SKU ou titulo para identificar os "
            f"anuncios. Cabecalhos lidos: {lidos}"
        )
    if not {"preco_atual", "preco_sugerido"} & campos:
        raise ValueError(f"{caminho}: nao encontrei nenhuma coluna de preco. Cabecalhos lidos: {lidos}")

    avisos: list[str] = []
    if "participar" not in campos:
        avisos.append(
            "planilha sem coluna de participacao: os anuncios recusados ficam com o preco em branco"
        )
    if "id" not in campos:
        avisos.append("planilha sem coluna de MLB: os custos serao casados por SKU, preco ou titulo")
    return avisos


def _linha_vazia(linha: list[object]) -> bool:
    return all(c is None or str(c).strip() == "" for c in linha)


def _texto(valor: object) -> str:
    if valor is None:
        return ""
    texto = str(valor).strip()
    return texto[:-2] if texto.endswith(".0") and texto[:-2].isdigit() else texto


def _decidir(perfil: PerfilGenerico, numero: int, custos: TabelaDeCustos, regras: Regras) -> Decisao:
    """Identifica o anuncio, precifica e devolve o veredito da linha."""
    decisao = Decisao(
        linha=numero + 1,
        id=_texto(perfil.ler(numero, "id")),
        sku=_texto(perfil.ler(numero, "sku")),
        titulo=_texto(perfil.ler(numero, "titulo")),
        campanha=_texto(perfil.ler(numero, "campanha")),
        preco_atual=para_decimal(perfil.ler(numero, "preco_atual")),
        preco_proposto=para_decimal(perfil.ler(numero, "preco_sugerido")),
        desconto_proposto_pct=para_decimal(perfil.ler(numero, "desconto_sugerido")),
    )
    capacidade = perfil.capacidade(numero)
    decisao.preco_editavel = capacidade.pode_alterar_preco

    custo = _buscar_custo(perfil, numero, decisao, custos, regras)
    if decisao.preco_atual is None and custo is not None:
        decisao.preco_atual = custo.preco_atual
    if decisao.preco_atual is None and decisao.preco_proposto is None:
        decisao.motivo = SEM_PRECO
        return decisao
    if custo is None:
        decisao.motivo = SEM_CUSTO
        return decisao

    decisao.custo = custo.custo
    regras_linha = custo.regras_aplicadas(regras)

    # Dois conjuntos de encargos para o mesmo anuncio: a ajuda que o Mercado
    # Livre oferece so existe no preco que ele propos. Em qualquer outro preco
    # ela vale zero, entao a contraproposta e decidida sem contar com ela.
    encargos = perfil.encargos(numero, custo, regras)
    ajuda = perfil.ajuda_na_proposta(numero, regras)
    encargos_proposta = replace(encargos, rebate=encargos.rebate + ajuda) if ajuda else encargos
    decisao.ajuda_ml = ajuda

    referencia = decisao.preco_proposto or decisao.preco_atual or ZERO
    decisao.encargos_usados = centavos(
        encargos.comissao_pct * referencia + encargos.frete + encargos.taxa_fixa
    )

    piso_campanha = para_decimal(perfil.ler(numero, "preco_min")) or ZERO
    piso = piso_de_preco(encargos_proposta, regras_linha)
    if piso is None:
        decisao.motivo = INVIAVEL
        return decisao
    decisao.piso = max(piso, piso_campanha)

    proposta_serve = (
        decisao.preco_proposto is not None and decisao.preco_proposto >= decisao.piso
    )
    if proposta_serve and regras.estrategia != "maior_desconto":
        return _aceitar(
            decisao,
            decisao.preco_proposto,
            decisao.desconto_proposto_pct,
            ACEITO,
            encargos_proposta,
            regras_linha,
        )
    if regras.estrategia == "so_proposta" or not capacidade.pode_alterar_preco:
        decisao.motivo = SEM_MARGEM if capacidade.pode_alterar_preco else SEM_MARGEM_FIXO
        return decisao

    # Fora da proposta do ML o piso sobe: nao ha mais a ajuda dele bancando parte.
    piso_proprio = piso_de_preco(encargos, regras_linha)
    if piso_proprio is None:
        decisao.motivo = INVIAVEL
        return decisao
    decisao.piso = max(piso_proprio, piso_campanha)

    alternativa = perfil.contraproposta(numero, decisao.piso, regras)
    if alternativa is None:
        decisao.motivo = SEM_MARGEM
        return decisao
    decisao.ajuda_ml = ZERO   # preco mudou: a ajuda do ML nao vale mais
    motivo = APROFUNDADO if proposta_serve else CONTRAPROPOSTA
    desconto = alternativa.desconto_pct
    if desconto is None:
        desconto = pct_desconto(decisao.preco_atual, alternativa.preco)
    return _aceitar(decisao, alternativa.preco, desconto, motivo, encargos, regras_linha)


def _buscar_custo(perfil, numero: int, decisao: Decisao, custos: TabelaDeCustos, regras: Regras):
    """Procura o custo do anuncio e anota na decisao por qual chave ele veio."""
    custo, via = custos.buscar(
        id_anuncio=decisao.id,
        sku=decisao.sku,
        variacao=_texto(perfil.ler(numero, "variacao")),
        titulo=decisao.titulo,
        preco_atual=decisao.preco_atual,
        metodos=tuple(regras.metodos_casamento or METODOS_PADRAO),
    )
    decisao.custo_via = via
    return custo


def _aceitar(decisao: Decisao, preco, desconto, motivo: str, encargos, regras: Regras) -> Decisao:
    """Fecha a participacao - e confere a conta uma ultima vez antes de aceitar.

    Rede de seguranca: qualquer caminho que chegue aqui com um preco que nao
    cumpre a regra e recusado, em vez de virar promocao no prejuizo.
    """
    resultado = avaliar(preco, encargos)
    if not _cumpre_a_regra(resultado, regras):
        decisao.motivo = SEM_MARGEM
        decisao.participar = False
        decisao.preco_aplicado = None
        return decisao
    decisao.participar = True
    decisao.preco_aplicado = centavos(preco)
    decisao.desconto_aplicado_pct = desconto
    decisao.motivo = motivo
    decisao.resultado = resultado
    return decisao


def _cumpre_a_regra(resultado: Resultado, regras: Regras) -> bool:
    """As duas regras de margem, conferidas no preco que sera praticado."""
    if resultado.margem_pct < regras.margem_min_pct:
        return False
    if resultado.preco_efetivo < regras.limiar_preco_baixo:
        return resultado.lucro >= regras.lucro_min_abaixo_limiar
    return resultado.lucro >= regras.lucro_min_acima_limiar


def _gravar_diagnostico(
    tabela: Tabela,
    numero: int,
    colunas: dict[str, int],
    decisao: Decisao,
    capacidade: Capacidade,
) -> None:
    """Escreve as colunas PROMO no fim da planilha, para auditoria."""
    if not colunas:
        return
    valores = {
        "participar": capacidade.texto_sim if decisao.participar else capacidade.texto_nao,
        "preco": decisao.preco_aplicado,
        "desconto": decisao.desconto_aplicado_pct,
        "piso": decisao.piso,
        "lucro": decisao.lucro,
        "margem": centavos(decisao.margem_pct * 100) if decisao.margem_pct is not None else None,
        "encargos": decisao.encargos_usados,
        "ajuda": decisao.ajuda_ml if decisao.ajuda_ml > ZERO else None,
        "custo_via": decisao.custo_via,
        "motivo": decisao.motivo,
    }
    for chave, idx in colunas.items():
        tabela.escrever(numero, idx, valores.get(chave))
