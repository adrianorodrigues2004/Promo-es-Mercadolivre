"""Matematica de margem: quanto sobra, e qual o menor preco que ainda cabe.

O modelo espelha exatamente a formula usada na planilha de precificacao::

    preco_efetivo = preco * (1 - cupom)
    lucro  = preco_efetivo
             - (custo + frete + taxa_fixa)
             - preco_efetivo * imposto
             - preco_efetivo * comissao
             + rebate
    margem = lucro / preco_efetivo

O rebate (a coluna "Ribait" da planilha) e o valor que o Mercado Livre paga ao
vendedor para bancar parte do desconto: entra somando.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .dinheiro import ZERO, centavos, centavos_acima
from .regras import Regras


@dataclass(frozen=True)
class Encargos:
    """Tudo que e descontado (ou somado) ao preco de venda de um anuncio."""

    custo: Decimal
    imposto_pct: Decimal = ZERO
    comissao_pct: Decimal = ZERO
    taxa_fixa: Decimal = ZERO
    frete: Decimal = ZERO
    rebate: Decimal = ZERO
    cupom_pct: Decimal = ZERO

    @classmethod
    def de_regras(cls, custo: Decimal, regras: Regras, **extras) -> "Encargos":
        return cls(
            custo=custo,
            imposto_pct=regras.imposto_pct,
            comissao_pct=regras.comissao_pct,
            taxa_fixa=regras.taxa_fixa,
            frete=regras.frete,
            **extras,
        )

    @property
    def fracao_percentual(self) -> Decimal:
        """Parcela do preco efetivo que evapora em imposto + comissao."""
        return self.imposto_pct + self.comissao_pct

    @property
    def custos_fixos(self) -> Decimal:
        """Parcela que nao depende do preco, ja liquida do rebate."""
        return self.custo + self.taxa_fixa + self.frete - self.rebate

    @property
    def fator_cupom(self) -> Decimal:
        """Fracao do preco anunciado que o comprador realmente paga."""
        return Decimal(1) - self.cupom_pct


@dataclass(frozen=True)
class Resultado:
    """Decomposicao do resultado de anunciar a ``preco``."""

    preco: Decimal
    preco_efetivo: Decimal
    imposto: Decimal
    comissao: Decimal
    taxa_fixa: Decimal
    frete: Decimal
    custo: Decimal
    rebate: Decimal
    lucro: Decimal
    margem_pct: Decimal


def avaliar(preco: Decimal, enc: Encargos) -> Resultado:
    """Quebra o preco em cada encargo e devolve lucro e margem."""
    efetivo = preco * enc.fator_cupom
    imposto = efetivo * enc.imposto_pct
    comissao = efetivo * enc.comissao_pct
    # O lucro sai dos valores cheios e so entao e arredondado: arredondar cada
    # parcela antes de somar desloca o resultado em ate um centavo por encargo.
    lucro = centavos(
        efetivo - imposto - comissao - enc.taxa_fixa - enc.frete - enc.custo + enc.rebate
    )
    margem = (lucro / efetivo) if efetivo > ZERO else ZERO
    return Resultado(
        preco=centavos(preco),
        preco_efetivo=centavos(efetivo),
        imposto=centavos(imposto),
        comissao=centavos(comissao),
        taxa_fixa=centavos(enc.taxa_fixa),
        frete=centavos(enc.frete),
        custo=centavos(enc.custo),
        rebate=centavos(enc.rebate),
        lucro=lucro,
        margem_pct=margem,
    )


def _anunciado(preco_efetivo: Decimal, enc: Encargos) -> Decimal | None:
    """Converte um piso calculado no preco efetivo para o preco a anunciar."""
    if enc.fator_cupom <= ZERO:
        return None
    return centavos_acima(preco_efetivo / enc.fator_cupom)


def piso_por_margem(enc: Encargos, margem_min: Decimal) -> Decimal | None:
    """Menor preco cujo lucro atinge ``margem_min`` do preco efetivo.

    ``efetivo * (1 - imposto - comissao - margem) >= custos_fixos``

    Devolve ``None`` quando imposto + comissao + margem consomem 100% ou mais
    do preco: nesse caso nenhum preco resolve.
    """
    sobra = Decimal(1) - enc.fracao_percentual - margem_min
    if sobra <= ZERO:
        return None
    if enc.custos_fixos <= ZERO:
        # Rebate cobre todo o custo: qualquer preco positivo ja da a margem.
        return centavos_acima(Decimal("0.01"))
    return _anunciado(enc.custos_fixos / sobra, enc)


def piso_por_lucro(enc: Encargos, lucro_min: Decimal) -> Decimal | None:
    """Menor preco que deixa ``lucro_min`` reais no bolso."""
    sobra = Decimal(1) - enc.fracao_percentual
    if sobra <= ZERO:
        return None
    alvo = (enc.custos_fixos + lucro_min) / sobra
    if alvo <= ZERO:
        return centavos_acima(Decimal("0.01"))
    return _anunciado(alvo, enc)


def piso_de_preco(enc: Encargos, regras: Regras) -> Decimal | None:
    """Menor preco de venda que satisfaz TODAS as regras de rentabilidade.

    A regra do lucro minimo em reais so vale abaixo do limiar (R$ 150 por
    padrao), entao o piso e resolvido em dois ramos e vence o menor viavel:

    * abaixo do limiar   -> exige margem percentual E lucro minimo em reais;
    * a partir do limiar -> exige margem percentual (e o lucro minimo alto,
      quando configurado).

    Sem esse cuidado um produto de custo intermediario seria recusado a R$ 148
    por causa da regra dos R$ 10 mesmo podendo ser vendido a R$ 150 dentro da
    regra dos 5%.
    """
    p_margem = piso_por_margem(enc, regras.margem_min_pct)
    if p_margem is None:
        return None

    limiar = regras.limiar_preco_baixo

    # Ramo A - preco abaixo do limiar: vale tambem o lucro minimo em reais.
    p_lucro_baixo = piso_por_lucro(enc, regras.lucro_min_abaixo_limiar)
    candidato_a = max(p_margem, p_lucro_baixo) if p_lucro_baixo is not None else p_margem
    if candidato_a < limiar:
        return candidato_a

    # Ramo B - preco a partir do limiar.
    candidato_b = max(p_margem, limiar)
    p_lucro_alto = piso_por_lucro(enc, regras.lucro_min_acima_limiar)
    if p_lucro_alto is not None:
        candidato_b = max(candidato_b, p_lucro_alto)
    return candidato_b
