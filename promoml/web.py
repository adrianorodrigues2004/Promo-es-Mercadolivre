"""Pagina local para arrastar a planilha e baixar o resultado.

E o modo "so subir e rodar": nada de linha de comando, nada de configurar.
Roda na propria maquina, os arquivos nao saem dela e ficam numa pasta temporaria
que e limpa quando o programa termina.
"""

from __future__ import annotations

import atexit
import shutil
import tempfile
import uuid
from pathlib import Path

from flask import Flask, abort, redirect, render_template_string, request, send_file, url_for

from . import __version__
from .custos import PASTA_EXTRAS, carregar_custos, descobrir_tabelas
from .motor import processar
from .planilha import EXTENSOES_EXCEL, EXTENSOES_TEXTO, FormatoNaoSuportado
from .regras import Regras
from .relatorio import escrever_decisoes, escrever_html, escrever_pendencias, montar_html

TAMANHO_MAXIMO = 32 * 1024 * 1024
EXTENSOES_ACEITAS = EXTENSOES_EXCEL | EXTENSOES_TEXTO


def criar_app(custos_padrao: Path, regras: Regras) -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = TAMANHO_MAXIMO
    trabalho = Path(tempfile.mkdtemp(prefix="promoml-"))
    atexit.register(shutil.rmtree, trabalho, True)

    @app.get("/")
    def inicio():
        return render_template_string(PAGINA_ENVIO, **_contexto())

    def _contexto(**extra):
        guardados = [c.name for c in descobrir_tabelas(custos_padrao)[1:]]
        return {
            "custos": custos_padrao,
            "tem_custos": Path(custos_padrao).exists(),
            "regras": regras,
            "pasta_extras": PASTA_EXTRAS,
            "guardados": guardados,
            "versao": __version__,
            **extra,
        }

    @app.post("/aplicar")
    def aplicar():
        enviado = request.files.get("planilha")
        if not enviado or not enviado.filename:
            return _erro("Escolha a planilha de promocoes exportada do Mercado Livre.")

        pasta = trabalho / uuid.uuid4().hex
        pasta.mkdir(parents=True)
        try:
            planilha = _guardar(enviado, pasta)

            enviado_custos = request.files.get("custos")
            if enviado_custos and enviado_custos.filename:
                tabelas = [_guardar(enviado_custos, pasta)]
            elif Path(custos_padrao).exists():
                # A tabela principal ja vem acompanhada do que estiver guardado
                # em config/custos-extras/.
                tabelas = descobrir_tabelas(custos_padrao)
            else:
                return _erro(
                    "Nenhuma tabela de custos disponivel: envie uma ou salve em "
                    f"'{custos_padrao}'."
                )

            # Os complementos entram depois: completam a tabela principal e,
            # em caso de repeticao, o valor mais novo prevalece.
            for complemento in request.files.getlist("complementos"):
                if complemento and complemento.filename:
                    tabelas.append(_guardar(complemento, pasta))

            custos = carregar_custos(tabelas, regras)
            rodada = processar(planilha, custos, regras)
        except (FileNotFoundError, ValueError, FormatoNaoSuportado) as erro:
            return _erro(str(erro))

        base = planilha.stem
        rodada.salvar(pasta / f"{base}-aplicado.xlsx")
        escrever_decisoes(rodada, pasta / f"{base}-decisoes.csv")
        escrever_html(rodada, pasta / f"{base}-relatorio.html")
        if rodada.pendencias:
            escrever_pendencias(rodada, pasta / f"{base}-pendencias.csv")

        return render_template_string(
            PAGINA_RESULTADO,
            pasta=pasta.name,
            base=base,
            resumo=rodada.resumo,
            tem_pendencias=bool(rodada.pendencias),
            avisos=rodada.avisos,
            relatorio=montar_html(rodada),
        )

    @app.get("/baixar/<pasta>/<nome>")
    def baixar(pasta: str, nome: str):
        # Nomes vem de links gerados aqui, mas a checagem impede subir de pasta.
        alvo = (trabalho / pasta / nome).resolve()
        if not alvo.is_file() or trabalho.resolve() not in alvo.parents:
            abort(404)
        return send_file(alvo, as_attachment=True)

    def _erro(mensagem: str):
        return render_template_string(PAGINA_ENVIO, **_contexto(erro=mensagem)), 400

    return app


def _guardar(enviado, pasta: Path) -> Path:
    """Salva o upload com nome seguro e extensao conhecida."""
    nome = Path(enviado.filename).name
    if Path(nome).suffix.lower() not in EXTENSOES_ACEITAS:
        raise FormatoNaoSuportado(
            f"'{nome}': envie um arquivo {', '.join(sorted(EXTENSOES_ACEITAS))}"
        )
    destino = pasta / nome
    enviado.save(destino)
    return destino


def servir(porta: int, custos: Path, regras: Regras) -> None:
    app = criar_app(Path(custos), regras)
    print(f"\n  promoml no ar: http://127.0.0.1:{porta}\n  (ctrl+c para parar)\n")
    app.run(host="127.0.0.1", port=porta)


_ESTILO = """
:root{--fundo:#f6f7f9;--carta:#fff;--borda:#e3e6ea;--texto:#1c2024;--suave:#666e78;
--acao:#1f6feb;--ok:#137a3f;--nao:#a8331f;--alerta:#8a6100}
*{box-sizing:border-box}
body{margin:0;padding:32px 20px;background:var(--fundo);color:var(--texto);
font:15px/1.55 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
.caixa{max-width:840px;margin:0 auto}
h1{font-size:24px;margin:0 0 6px}
p.sub{color:var(--suave);margin:0 0 24px}
.carta{background:var(--carta);border:1px solid var(--borda);border-radius:12px;padding:22px;margin-bottom:18px}
label{display:block;font-weight:600;margin-bottom:6px}
input[type=file]{width:100%;padding:14px;border:1.5px dashed var(--borda);border-radius:10px;background:#fafbfc}
.dica{color:var(--suave);font-size:13px;margin:6px 0 18px}
button{background:var(--acao);color:#fff;border:0;border-radius:9px;padding:12px 22px;
font-size:15px;font-weight:600;cursor:pointer}
button:hover{filter:brightness(1.08)}
.erro{background:#fdecea;border:1px solid #f5c2bc;color:#8f2418;padding:12px 14px;border-radius:9px;margin-bottom:18px}
.regras{font-size:13px;color:var(--suave);margin-top:20px;line-height:1.6;
border-top:1px solid var(--borda);padding-top:16px}
.titulo-regras{font-weight:600;color:var(--texto);margin-bottom:8px}
.tabela-regras{border-collapse:collapse;margin-bottom:10px}
.tabela-regras td{padding:3px 0;vertical-align:top}
.tabela-regras td:first-child{white-space:nowrap;padding-right:14px;color:var(--texto);font-weight:600}
.tabela-regras strong{color:var(--texto)}
.cartoes{display:flex;flex-wrap:wrap;gap:12px;margin:0 0 18px}
.cartao{background:var(--carta);border:1px solid var(--borda);border-radius:10px;padding:12px 16px;min-width:150px}
.cartao span{display:block;color:var(--suave);font-size:12px}
.cartao strong{font-size:20px}
.ok strong{color:var(--ok)} .nao strong{color:var(--nao)} .alerta strong{color:var(--alerta)}
a.botao{display:inline-block;margin:0 8px 8px 0;padding:10px 16px;border-radius:9px;
border:1px solid var(--borda);background:var(--carta);text-decoration:none;color:var(--texto);font-weight:600}
a.botao.destaque{background:var(--acao);color:#fff;border-color:var(--acao)}
a.voltar{color:var(--acao)}
details{margin-top:18px}
summary{cursor:pointer;font-weight:600;margin-bottom:10px}
iframe{width:100%;height:520px;border:1px solid var(--borda);border-radius:10px;background:#fff}
"""

PAGINA_ENVIO = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Promocoes Mercado Livre</title><style>""" + _ESTILO + """</style></head><body>
<div class="caixa">
<h1>Aplicar promocoes com margem</h1>
<p class="sub">Suba a planilha exportada do Mercado Livre. O programa decide anuncio a
anuncio e devolve a planilha pronta para reenviar.</p>
{% if erro %}<div class="erro">{{ erro }}</div>{% endif %}
<form class="carta" method="post" action="/aplicar" enctype="multipart/form-data">
  <label for="planilha">Planilha de promocoes</label>
  <input id="planilha" type="file" name="planilha" accept=".xlsx,.xlsm,.csv,.tsv,.txt" required>
  <p class="dica">O export de campanhas do Mercado Livre, em .xlsx ou .csv.</p>

  <label for="custos">Tabela de custos {% if tem_custos %}(opcional){% endif %}</label>
  <input id="custos" type="file" name="custos" accept=".xlsx,.xlsm,.csv,.tsv,.txt">
  <p class="dica">
  {% if tem_custos %}Sem enviar nada, uso <code>{{ custos }}</code>.
  {% else %}Nenhuma tabela salva ainda - envie a sua planilha de precificacao.{% endif %}</p>

  <label for="complementos">Custos que faltavam (opcional)</label>
  <input id="complementos" type="file" name="complementos" multiple
         accept=".xlsx,.xlsm,.csv,.tsv,.txt">
  <p class="dica">
  {% if guardados %}
    Ja entram sozinhos em toda rodada, de <code>{{ pasta_extras }}</code>:
    <strong>{{ guardados|join(', ') }}</strong>.
    Use este campo so para um arquivo avulso.
  {% else %}
    Aqui entra o arquivo de <strong>pendencias</strong> depois de preenchido - ele
    completa a tabela acima, nao substitui.
    <br><strong>Para nao precisar reenviar toda vez:</strong> guarde o arquivo em
    <code>{{ pasta_extras }}</code> e ele passa a entrar sozinho.
  {% endif %}</p>

  <button type="submit">Aplicar promocoes</button>
  <div class="regras">
    <div class="titulo-regras">Com o que estou contando</div>
    <table class="tabela-regras">
      <tr><td>Margem mínima</td>
          <td><strong>{{ '%.2f'|format(regras.margem_min_pct * 100) }}%</strong>, e pelo menos
          R$ {{ '%.2f'|format(regras.lucro_min_abaixo_limiar) }} de lucro abaixo de
          R$ {{ '%.2f'|format(regras.limiar_preco_baixo) }}</td></tr>
      <tr><td>Imposto</td><td>{{ '%.2f'|format(regras.imposto_pct * 100) }}% sobre a venda</td></tr>
      <tr><td>Comissão do ML</td>
          <td>{{ '%.2f'|format(regras.comissao_pct * 100) }}% quando sua planilha não disser qual é
          (a coluna <code>Taxa</code> tem prioridade)</td></tr>
      <tr><td>Comissão + frete</td>
          <td>{% if regras.fonte_encargos == 'mais_conservadora' %}o maior valor entre a sua planilha
          e a conta do Mercado Livre{% elif regras.fonte_encargos == 'planilha' %}sempre as colunas
          Taxa e Frete da sua planilha{% else %}sempre a conta do “Você recebe”{% endif %}</td></tr>
      <tr><td>Ajuda do ML</td>
          <td>{% if regras.ajuda_do_ml == 'nunca' %}ignorada{% else %}conta só no preço que o ML
          propôs; se eu mudar o preço, vale zero{% endif %}</td></tr>
    </table>
    Para mudar, edite <code>config/regras.yml</code>. &middot; versão {{ versao }}
  </div>
</form>
</div></body></html>"""

PAGINA_RESULTADO = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Resultado</title><style>""" + _ESTILO + """</style></head><body>
<div class="caixa">
<h1>Pronto</h1>
<p class="sub"><a class="voltar" href="/">&larr; processar outra planilha</a></p>
<div class="cartoes">
  <div class="cartao"><span>Analisados</span><strong>{{ resumo.total }}</strong></div>
  <div class="cartao ok"><span>Entram na promocao</span><strong>{{ resumo.participando }}</strong></div>
  <div class="cartao nao"><span>Ficam de fora</span><strong>{{ resumo.recusados }}</strong></div>
  <div class="cartao alerta"><span>Sem custo</span><strong>{{ resumo.sem_custo }}</strong></div>
  <div class="cartao ok"><span>Lucro previsto</span><strong>R$ {{ '%.2f'|format(resumo.lucro_previsto) }}</strong></div>
  <div class="cartao"><span>Margem media</span><strong>{{ '%.2f'|format(resumo.margem_media_pct * 100) }}%</strong></div>
</div>
<div class="carta">
  <a class="botao destaque" href="{{ url_for('baixar', pasta=pasta, nome=base ~ '-aplicado.xlsx') }}">Baixar planilha para o ML</a>
  <a class="botao" href="{{ url_for('baixar', pasta=pasta, nome=base ~ '-decisoes.csv') }}">Decisoes (CSV)</a>
  <a class="botao" href="{{ url_for('baixar', pasta=pasta, nome=base ~ '-relatorio.html') }}">Relatorio</a>
  {% if tem_pendencias %}
  <a class="botao" href="{{ url_for('baixar', pasta=pasta, nome=base ~ '-pendencias.csv') }}">Custos a completar</a>
  {% endif %}
  {% if resumo.sem_custo %}
  <p class="dica">{{ resumo.sem_custo }} anuncio(s) ficaram de fora so por falta de custo.
  Preencha a coluna <code>custo</code> no arquivo de pendencias e rode de novo.</p>
  {% endif %}
  {% for aviso in avisos %}<p class="dica">aviso: {{ aviso }}</p>{% endfor %}
</div>
<details open><summary>Ver decisao de cada anuncio</summary>
<iframe srcdoc="{{ relatorio|e }}"></iframe></details>
</div></body></html>"""
