# Exemplos

Esta pasta guarda planilhas para testar a ferramenta. Ela esta no `.gitignore`
porque custo de produto e preco de compra sao dados do negocio e nao devem ir
para o controle de versao.

Para gerar uma planilha de promocoes ficticia a partir da sua tabela de custos:

```bash
python3 scripts/gerar_planilha_exemplo.py --custos config/custos.xlsx
```

Os testes automatizados nao dependem desta pasta: eles montam as planilhas de
que precisam em `tests/conftest.py`.
