# Promoções Mercado Livre com controle de margem

Sobe a planilha de campanha exportada do Mercado Livre e devolve ela pronta
para reenviar: **participando só nos anúncios que deixam margem**, e fora dos
que dariam prejuízo.

A regra é a que você definiu:

> margem de pelo menos **5%**, e quando o preço final ficar **abaixo de
> R$ 150**, pelo menos **R$ 10 de lucro** por unidade — com **11,5% de
> imposto** sobre a venda.

---

## Como usar

### Preparar (uma vez só)

**1. Instale o Python** — [python.org/downloads](https://www.python.org/downloads/).
No Windows, marque **"Add Python to PATH"** na primeira tela do instalador.

**2. Baixe esta pasta** e descompacte num lugar fácil, por exemplo
`Documentos\promocoes`.

**3. Coloque sua tabela de custos** em `config/custos.xlsx`. É a mesma planilha
de precificação que você já usa (aba **Mercado Livre**, com as colunas
`Produto`, `Código`, `Custo`, `Frete`, `Imposto`, `Taxa`, `Ribait`,
`Preço Atual`). Não precisa reorganizar nada — o programa reconhece essas
colunas sozinho.

### Rodar (toda vez)

**Clique duas vezes em `iniciar.bat`** (Windows) ou **`iniciar.sh`** (Mac).
Ele instala o que falta na primeira vez e abre a página no navegador.

Na página: arraste a planilha exportada do Mercado Livre, clique em
**Aplicar promoções** e baixe o resultado. Deixe a janela preta aberta enquanto
usa; feche-a para encerrar.

O ciclo completo fica assim:

```
exporta do ML  →  arrasta na página  →  baixa a planilha pronta  →  reenvia ao ML
```

### Pelo terminal, se preferir

```bash
pip install -r requirements.txt
python3 -m promoml aplicar "1_O_melhor_de_todos_os_dias....xlsx"
```

### O que sai

Na pasta `saida/`:

| Arquivo | Para que serve |
|---|---|
| `...-aplicado.xlsx` | **a planilha para reenviar ao Mercado Livre** |
| `...-relatorio.html` | a decisão de cada anúncio, com a conta aberta |
| `...-decisoes.csv` | o mesmo em CSV, para abrir no Excel |
| `...-pendencias.csv` | anúncios que ficaram de fora só por falta de custo |

A planilha original **nunca é alterada** — o resultado sai sempre numa cópia.

---

## O que o programa faz com cada anúncio

1. **Acha o custo** do anúncio na sua tabela de precificação.
2. **Calcula o piso**: o menor preço que ainda respeita as duas regras de margem.
3. **Compara com a proposta do Mercado Livre**:

| Situação | O que o programa faz |
|---|---|
| A proposta do ML fica acima do piso | marca **Aplicar proposta / Participar**, sem mexer no preço |
| A proposta fica abaixo do piso, e a campanha deixa mudar o desconto | **contrapropõe**: reduz o desconto até o preço voltar ao piso |
| A proposta fica abaixo do piso, e o preço é fechado | marca **Não aplicar / Não participar** |
| O anúncio não tem custo cadastrado | fica de fora e entra no arquivo de pendências |

Duas particularidades do export do ML que o programa respeita:

- **Cada linha tem seu vocabulário.** As propostas novas aceitam
  `Aplicar proposta / Não aplicar`; as promoções já ativas aceitam
  `Participar / Não participar`. Escrever a palavra errada invalida o reenvio,
  então a resposta é lida da própria lista suspensa da célula.
- **Só as células azul-claro aceitam desconto novo.** Nas cinzas o preço é
  fechado, e a única escolha é entrar ou sair.

---

## A conta

Para cada anúncio, no preço final `P`:

```
lucro  = P − custo − frete − P × imposto − P × comissão + rebate
margem = lucro ÷ P
```

É exatamente a fórmula da sua planilha de precificação — conferida linha a
linha contra ela (504 de 505 lucros idênticos ao centavo; o único diferente é
arredondamento de meio centavo do Excel).

**Comissão e frete têm duas medidas, e elas discordam.** Sua planilha traz as
colunas `Taxa` e `Frete`; o Mercado Livre traz a coluna *"Você recebe"*, de onde
sai `comissão + frete` reais no preço proposto. Nos dados reais o ML apareceu
**mais barato que a planilha em 24 de 35 anúncios** conferidos. Ficar com o
menor dos dois é o caminho do prejuízo, então o padrão é o **maior**: o que
sobrar de margem, sobra de verdade. Trocável em `fonte_encargos`.

**A ajuda do ML só vale no preço que ele propôs.** A *"Redução nas suas tarifas
de venda"* é dinheiro real, mas some se o preço mudar. Quando o programa
contrapropõe, ele calcula a margem **sem contar com ela**. Para ignorá-la
sempre — e bater exatamente com a sua planilha — use `ajuda_do_ml: nunca`.

Cada anúncio sai no relatório com as colunas `PROMO Comissao+Frete` e
`PROMO Ajuda do ML`, para você conferir de onde veio cada número.

### Por que a regra dos R$ 10 tem esse cuidado

Um produto de custo intermediário poderia ser recusado a R$ 148 por não deixar
R$ 10 de lucro, mesmo podendo ser vendido a R$ 150 dentro da regra dos 5% — a
regra dos R$ 10 só vale abaixo de R$ 150. O programa testa as duas faixas e
fica com o menor preço viável, em vez de recusar o anúncio à toa.

---

## Antes da primeira rodada: confira a leitura

```bash
python3 -m promoml conferir "sua-planilha.xlsx"
```

Mostra o perfil detectado, quais colunas ele reconheceu de cada arquivo e as
regras em uso — sem decidir nada. Se alguma coluna estiver errada, corrija em
`config/regras.yml`, na seção `colunas`.

---

## Anúncios sem custo

Na primeira rodada é normal muitos anúncios caírem em pendências: sua tabela de
precificação e a campanha não usam sempre o mesmo MLB. O programa casa por
MLB, por SKU e pelo **preço atual do anúncio** (que se mostrou exato nos testes
com seus dados: 23 de 23 acertos). Quando dois produtos têm o mesmo preço e
custos diferentes, ele prefere **não casar** a arriscar o custo errado.

Para resolver, uma vez só por anúncio:

1. Abra `saida/...-pendencias.csv` e preencha a coluna `custo`.
2. **Salve o arquivo em `config/custos-extras/`.**

Pronto. A partir daí ele entra sozinho em toda rodada — você não precisa
reenviar nada pela página nunca mais. Pode acumular quantos arquivos quiser
nessa pasta.

Esses arquivos **somam** à sua tabela principal, não substituem: os anúncios
que já tinham custo continuam valendo. Se o mesmo anúncio aparecer em dois
arquivos, vale o último em ordem alfabética — por isso vale nomear por data:

```
config/custos-extras/
    2026-08-pendencias.csv
    2026-09-pendencias.csv     <- este corrige o anterior
```

O campo **"Custos que faltavam"** da página continua existindo, para um arquivo
avulso que você não quer guardar. E pelo terminal dá para listar vários em
`--custos`, os últimos com prioridade:

```bash
python3 -m promoml aplicar "sua-planilha.xlsx" \
    --custos config/custos.xlsx saida/...-pendencias.csv
```

Um arquivo ilegível nessa pasta vira aviso, não derruba a rodada.

Melhor ainda, para não repetir isso todo mês: preencha a coluna `Código` desses
anúncios na sua planilha de precificação — aí eles passam a casar por MLB para
sempre.

---

## Ajustes

Tudo fica em `config/regras.yml`. Os mais úteis:

```yaml
margem_min_pct: 5%            # sua margem mínima
lucro_min_abaixo_limiar: 10   # R$ mínimos abaixo do limiar
limiar_preco_baixo: 150       # onde a regra em reais para de valer
estrategia: sugerido          # ou: maior_desconto, so_proposta
```

`estrategia: so_proposta` é o modo mais conservador: não mexe em preço nenhum,
apenas desmarca o que dá prejuízo.

Dá para sobrepor pontualmente na linha de comando:

```bash
python3 -m promoml aplicar planilha.xlsx --margem 8% --estrategia so_proposta
```

---

## Testes

```bash
pip install -r requirements-dev.txt
python3 -m pytest
```

Os testes montam suas próprias planilhas — com linhas de instrução, os dois
vocabulários de ação e as células coloridas — e não dependem de nenhum arquivo
real.
