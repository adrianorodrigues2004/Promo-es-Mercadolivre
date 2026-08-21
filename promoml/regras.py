"""Regras de negocio: encargos, margem minima e estrategia de desconto."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from decimal import Decimal
from pathlib import Path

from .dinheiro import ARREDONDAMENTOS, ZERO, para_decimal, para_percentual

# sugerido      - aceita a proposta do ML quando ela cabe no piso; se nao
#                 couber, contrapropoe o maior desconto que ainda cabe.
# maior_desconto - ignora a proposta e sempre desce ate o piso de margem.
# so_proposta    - nunca mexe no preco: so marca ou desmarca a participacao.
ESTRATEGIAS = ("sugerido", "maior_desconto", "so_proposta")


@dataclass(frozen=True)
class Regras:
    """Parametros que decidem se um anuncio entra ou nao na promocao."""

    # --- Encargos padrao (podem ser sobrescritos por produto na tabela de custos)
    imposto_pct: Decimal = Decimal("0.115")
    comissao_pct: Decimal = ZERO
    taxa_fixa: Decimal = ZERO
    frete: Decimal = ZERO

    # --- Piso de rentabilidade
    margem_min_pct: Decimal = Decimal("0.05")
    limiar_preco_baixo: Decimal = Decimal("150")
    lucro_min_abaixo_limiar: Decimal = Decimal("10")
    lucro_min_acima_limiar: Decimal = ZERO

    # --- Comportamento
    estrategia: str = "sugerido"
    # Menor desconto que vale a pena contrapropor. O padrao acompanha o piso
    # que o proprio Mercado Livre usa nas campanhas (3%): abaixo disso a oferta
    # tende a ser recusada e so suja o reenvio.
    desconto_min_padrao_pct: Decimal = Decimal("0.03")
    desconto_max_pct: Decimal | None = None
    passo_desconto_pp: Decimal = Decimal("1")
    metodos_casamento: tuple[str, ...] = ("mlb", "sku", "preco")
    arredondamento: str = "centavo_acima"
    participar_sem_custo: bool = False
    texto_sim: str = "SIM"
    texto_nao: str = "NAO"

    # --- Mapeamento manual de colunas (sobrepoe a deteccao automatica)
    colunas: dict[str, str] = field(default_factory=dict)
    linha_cabecalho: int | None = None

    @property
    def arredondar(self):
        return ARREDONDAMENTOS[self.arredondamento]

    def validar(self) -> None:
        if self.estrategia not in ESTRATEGIAS:
            raise ValueError(f"estrategia invalida: {self.estrategia!r} (use uma de {ESTRATEGIAS})")
        if self.arredondamento not in ARREDONDAMENTOS:
            raise ValueError(
                f"arredondamento invalido: {self.arredondamento!r} "
                f"(use uma de {tuple(ARREDONDAMENTOS)})"
            )
        for campo in ("imposto_pct", "comissao_pct", "margem_min_pct"):
            valor = getattr(self, campo)
            if not (ZERO <= valor < 1):
                raise ValueError(f"{campo} deve ficar entre 0 e 1 (recebido {valor})")
        for campo in ("taxa_fixa", "frete", "lucro_min_abaixo_limiar", "lucro_min_acima_limiar"):
            if getattr(self, campo) < ZERO:
                raise ValueError(f"{campo} nao pode ser negativo")
        if not (ZERO < self.passo_desconto_pp <= 50):
            raise ValueError("passo_desconto_pp deve ficar entre 0 e 50 pontos percentuais")
        from .custos import METODOS_VALIDOS

        invalidos = set(self.metodos_casamento) - set(METODOS_VALIDOS)
        if invalidos:
            raise ValueError(
                f"metodos_casamento invalidos: {sorted(invalidos)} (use {list(METODOS_VALIDOS)})"
            )

    def com_ajustes(self, **ajustes) -> "Regras":
        """Copia as regras trocando apenas os campos informados (nao-nulos)."""
        limpos = {k: v for k, v in ajustes.items() if v is not None}
        return replace(self, **limpos) if limpos else self


_PERCENTUAIS = {
    "imposto_pct",
    "comissao_pct",
    "margem_min_pct",
    "desconto_min_padrao_pct",
    "desconto_max_pct",
}
_MONETARIOS = {
    "passo_desconto_pp",
    "taxa_fixa",
    "frete",
    "limiar_preco_baixo",
    "lucro_min_abaixo_limiar",
    "lucro_min_acima_limiar",
}


def regras_de_dict(dados: dict, base: Regras | None = None) -> Regras:
    """Constroi ``Regras`` a partir de um dicionario (YAML/JSON/CLI)."""
    base = base or Regras()
    ajustes: dict[str, object] = {}
    for chave, valor in (dados or {}).items():
        if valor is None or not hasattr(base, chave):
            continue
        if chave in _PERCENTUAIS:
            ajustes[chave] = para_percentual(valor)
        elif chave in _MONETARIOS:
            ajustes[chave] = para_decimal(valor)
        elif chave in ("participar_sem_custo",):
            ajustes[chave] = bool(valor)
        elif chave == "linha_cabecalho":
            ajustes[chave] = int(valor)
        elif chave == "metodos_casamento":
            ajustes[chave] = tuple(str(v).strip().lower() for v in valor)
        elif chave == "colunas":
            ajustes[chave] = {str(k): str(v) for k, v in (valor or {}).items()}
        else:
            ajustes[chave] = str(valor)
    regras = replace(base, **ajustes)
    regras.validar()
    return regras


def carregar_regras(caminho: str | Path | None) -> Regras:
    """Le ``regras.yml`` (ou ``.json``). Sem arquivo, usa os padroes."""
    if caminho is None:
        return Regras()
    caminho = Path(caminho)
    if not caminho.exists():
        raise FileNotFoundError(f"arquivo de regras nao encontrado: {caminho}")
    texto = caminho.read_text(encoding="utf-8")
    if caminho.suffix.lower() in (".yml", ".yaml"):
        import yaml

        dados = yaml.safe_load(texto) or {}
    else:
        dados = json.loads(texto)
    if not isinstance(dados, dict):
        raise ValueError(f"{caminho}: esperava um mapa de chave/valor no topo do arquivo")
    return regras_de_dict(dados)
