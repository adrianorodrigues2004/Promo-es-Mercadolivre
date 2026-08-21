"""Deteccao do cabecalho e das colunas da planilha de promocoes.

O export do Mercado Livre muda de nome conforme o tipo de campanha, e costuma
trazer linhas de instrucao antes do cabecalho de verdade. Em vez de fixar uma
posicao, cada coluna e escolhida por pontuacao sobre o texto do cabecalho, e
tudo pode ser sobreposto no ``regras.yml`` quando a heuristica errar.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# Campos que o motor sabe usar. Cada padrao ganha um peso: quanto mais
# especifico o texto, maior a pontuacao, para "preco com desconto" vencer
# "desconto" na mesma celula.
PADROES: dict[str, list[tuple[str, int]]] = {
    "id": [
        (r"^mlb\b", 100),
        (r"(codigo|cod|id|numero)\D{0,12}(anuncio|item|publicacao|produto)", 95),
        (r"^(id|item[_ ]?id|item)$", 70),
        (r"anuncio.*(codigo|id)", 80),
    ],
    "variacao": [
        (r"(id|codigo).{0,10}varia", 95),
        (r"^varia(cao|coes|nt|tion)", 80),
        (r"varia(cao|tion)", 60),
    ],
    "sku": [(r"\bsku\b", 100), (r"codigo.{0,10}(vendedor|interno|proprio)", 80)],
    "titulo": [
        (r"^titulo", 100),
        (r"titulo.*(anuncio|publicacao)", 95),
        (r"nome.{0,6}(do)?.{0,6}(anuncio|produto|item)", 85),
        (r"^(anuncio|produto|descricao)$", 55),
    ],
    "preco_atual": [
        (r"preco.{0,16}sem.{0,6}desconto", 100),
        (r"preco.{0,10}(atual|original|cheio|de lista|de tabela|normal)", 98),
        (r"(valor|preco).{0,10}(de)?.{0,6}venda(?!.*promo)", 85),
        (r"preco.{0,10}(do)?.{0,6}(anuncio|item|produto)", 80),
        (r"^preco( unitario)?( r)?$", 70),
    ],
    "preco_sugerido": [
        (r"preco.{0,16}com.{0,6}desconto", 100),
        (r"preco.{0,16}(promocional|da promocao|de campanha|na promocao)", 98),
        (r"preco.{0,16}sugerido", 96),
        (r"(novo|nova).{0,6}preco", 88),
        (r"preco.{0,16}final.{0,20}(comprador|cliente)", 86),
        (r"preco.{0,16}(com|apos).{0,10}promocao", 84),
        (r"valor.{0,10}promocional", 82),
    ],
    "preco_min": [
        (r"preco.{0,16}minimo", 100),
        (r"(minimo|piso).{0,16}preco", 90),
        (r"preco.{0,16}(limite|teto).{0,10}inferior", 85),
    ],
    "preco_max": [(r"preco.{0,16}maximo", 100), (r"(maximo|teto).{0,16}preco", 90)],
    "desconto_sugerido": [
        (r"desconto.{0,16}sugerido", 100),
        (r"(percentual|%|pct).{0,16}desconto", 80),
        (r"^desconto( \(?%?\)?)?( sugerido)?$", 75),
        (r"desconto", 40),
    ],
    "desconto_min": [(r"desconto.{0,16}minimo", 100), (r"minimo.{0,16}desconto", 90)],
    "desconto_max": [(r"desconto.{0,16}maximo", 100), (r"maximo.{0,16}desconto", 90)],
    "participar": [
        (r"partici(par|pa|pacao)", 100),
        (r"(aceitar|aderir|adesao|incluir|aplicar).{0,20}(promocao|campanha|oferta)?", 90),
        (r"^(sim|nao).{0,4}(sim|nao)?$", 60),
    ],
    "campanha": [
        (r"(nome|tipo).{0,10}(da)?.{0,6}(campanha|promocao)", 100),
        (r"^(campanha|promocao|oferta)$", 85),
    ],
    "custo": [
        (r"(preco|valor|custo).{0,10}(de)?.{0,6}custo", 100),
        (r"custo.{0,10}(unitario|do produto|de compra)", 98),
        (r"valor.{0,10}pago", 90),
        (r"^custo", 85),
    ],
    "comissao": [
        (r"(comissao|tarifa).{0,16}(mercado|ml|venda|classico|premium)?", 100),
        (r"taxa.{0,10}(de)?.{0,6}venda", 90),
    ],
}

# Colunas em que o motor escreve o resultado, quando existirem na planilha.
CAMPOS_DE_SAIDA = ("participar", "preco_sugerido")

# Vetos: quando o cabecalho casa com um destes, o campo e descartado. Serve
# para "Preco com desconto sugerido" nao ser lido como coluna de percentual de
# desconto - ali o que esta escrito e um preco.
ANTIPADROES: dict[str, str] = {
    "desconto_sugerido": r"\b(preco|valor)\b",
    "desconto_min": r"\b(preco|valor)\b",
    "desconto_max": r"\b(preco|valor)\b",
    "preco_atual": r"\bcusto\b",
}

_NAO_ALNUM = re.compile(r"[^a-z0-9%]+")


def normalizar(texto: object) -> str:
    """``"Preço com Desconto (R$)"`` -> ``"preco com desconto r"``."""
    if texto is None:
        return ""
    sem_acento = unicodedata.normalize("NFKD", str(texto))
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    return _NAO_ALNUM.sub(" ", sem_acento.lower()).strip()


def pontuar(cabecalho: str, tabela: dict[str, list[tuple[str, int]]] | None = None) -> dict[str, int]:
    """Pontuacao de um texto de cabecalho para cada campo conhecido."""
    alvo = normalizar(cabecalho)
    if not alvo:
        return {}
    pontos: dict[str, int] = {}
    for campo, padroes in (tabela or PADROES).items():
        veto = ANTIPADROES.get(campo)
        if veto and re.search(veto, alvo):
            continue
        melhor = max((peso for padrao, peso in padroes if re.search(padrao, alvo)), default=0)
        if melhor:
            pontos[campo] = melhor
    return pontos


@dataclass
class Mapa:
    """Resultado da deteccao: qual indice de coluna guarda cada campo."""

    linha_cabecalho: int
    indices: dict[str, int]
    cabecalhos: list[str]
    confianca: dict[str, int]

    def get(self, campo: str) -> int | None:
        return self.indices.get(campo)

    def nome(self, campo: str) -> str | None:
        idx = self.indices.get(campo)
        return self.cabecalhos[idx] if idx is not None else None

    def faltando(self, obrigatorios: tuple[str, ...]) -> list[str]:
        return [c for c in obrigatorios if c not in self.indices]


def mapear(
    cabecalhos: list[str],
    linha_cabecalho: int,
    forcado: dict[str, str] | None = None,
    tabela: dict[str, list[tuple[str, int]]] | None = None,
) -> Mapa:
    """Escolhe a melhor coluna para cada campo, sem repetir colunas.

    Resolve conflitos de forma gulosa pela maior pontuacao global: se duas
    colunas disputam ``preco_sugerido``, quem pontuou mais fica com o campo e a
    outra concorre pelo proximo campo da sua lista.
    """
    candidatos: list[tuple[int, str, int]] = []
    for idx, texto in enumerate(cabecalhos):
        for campo, peso in pontuar(texto, tabela).items():
            candidatos.append((peso, campo, idx))
    candidatos.sort(key=lambda item: (-item[0], item[1], item[2]))

    indices: dict[str, int] = {}
    confianca: dict[str, int] = {}
    usados: set[int] = set()
    for peso, campo, idx in candidatos:
        if campo in indices or idx in usados:
            continue
        indices[campo] = idx
        confianca[campo] = peso
        usados.add(idx)

    for campo, nome in (forcado or {}).items():
        idx = _resolver_forcado(nome, cabecalhos)
        if idx is None:
            raise ValueError(
                f"coluna '{nome}' (mapeada para '{campo}' em regras.yml) nao existe na planilha"
            )
        anterior = indices.get(campo)
        if anterior is not None and anterior != idx:
            usados.discard(anterior)
        # Se a coluna forcada estava com outro campo, aquele campo fica sem ela.
        for outro, outro_idx in list(indices.items()):
            if outro_idx == idx and outro != campo:
                del indices[outro]
                confianca.pop(outro, None)
        indices[campo] = idx
        confianca[campo] = 999
        usados.add(idx)

    return Mapa(linha_cabecalho=linha_cabecalho, indices=indices, cabecalhos=cabecalhos, confianca=confianca)


def _resolver_forcado(nome: str, cabecalhos: list[str]) -> int | None:
    """Aceita nome exato, nome normalizado, letra da coluna (``H``) ou indice."""
    texto = str(nome).strip()
    if texto.isdigit():
        idx = int(texto)
        return idx if 0 <= idx < len(cabecalhos) else None
    if re.fullmatch(r"[A-Za-z]{1,3}", texto) and normalizar(texto) not in [
        normalizar(c) for c in cabecalhos
    ]:
        idx = 0
        for char in texto.upper():
            idx = idx * 26 + (ord(char) - 64)
        return idx - 1 if idx - 1 < len(cabecalhos) else None
    alvo = normalizar(texto)
    for idx, cabecalho in enumerate(cabecalhos):
        if normalizar(cabecalho) == alvo:
            return idx
    return None


def detectar_cabecalho(
    linhas: list[list[object]],
    limite: int = 30,
    tabela: dict[str, list[tuple[str, int]]] | None = None,
) -> int:
    """Descobre em que linha esta o cabecalho real (0-based).

    Os exports do Mercado Livre trazem titulo e instrucoes antes da tabela,
    entao vence a linha que mais parece um cabecalho: muitos campos conhecidos,
    muitas celulas preenchidas e nenhum numero solto.
    """
    melhor_linha, melhor_nota = 0, -1.0
    for numero, linha in enumerate(linhas[:limite]):
        preenchidas = [c for c in linha if c is not None and str(c).strip() != ""]
        if len(preenchidas) < 2:
            continue
        campos = set()
        for celula in linha:
            campos.update(pontuar(celula, tabela))
        numericos = sum(1 for c in preenchidas if isinstance(c, (int, float)))
        nota = len(campos) * 3 + len(preenchidas) * 0.2 - numericos * 1.5
        if nota > melhor_nota:
            melhor_linha, melhor_nota = numero, nota
    return melhor_linha
