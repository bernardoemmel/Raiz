"""Servidor MCP da Raíz sem banco: as ferramentas e os textos para o agente, o erro legível sem a chave e o servidor
local por stdio (`raiz mcp`), como o Claude Desktop e o Claude Code ligam. O teste com o banco, de ponta a ponta, está
em test_publica_banco.py."""

import shutil
import sys

import anyio
import pytest

from raiz.publica.api import sem_dado_pessoal
from raiz.publica.servidor_mcp import ApiRaiz, criar_servidor

FERRAMENTAS = {"buscar_base", "montar_lote", "ver_opcoes", "solicitar_interesse", "andamento_do_pedido",
               "explicar_fazenda", "pedir_reserva"}  # fmt: skip


def test_ferramentas_e_textos_para_o_agente():
    from mcp.client.client import Client

    async def ver():
        async with Client(criar_servidor(ApiRaiz(chave=""))) as cli:
            ts = {t.name: t for t in (await cli.list_tools()).tools}
            assert set(ts) == FERRAMENTAS
            assert "P10/P50/P90" in ts["buscar_base"].description or "P10" in ts["buscar_base"].description
            assert "não confirma nem paga" in ts["pedir_reserva"].description
            props = ts["montar_lote"].input_schema["properties"]
            assert {"meta_valor", "ufs", "cronograma", "terra", "metodos"} <= set(props)
            assert "pessoal" in (cli.instructions or "") or "CPF" in (cli.instructions or "")
            r = await cli.call_tool("buscar_base", {"meta_valor": 1000})
            assert r.is_error and "chave" in r.content[0].text  # sem a chave, o agente lê o que falta

    anyio.run(ver)


def test_nada_pessoal_sai_mesmo_se_vier():
    x = {"cod_imovel": "PA-1", "nome_proprietario": "Fulano", "cpf": "123", "itens": [{"cnpj_dono": "1", "ha": 2}],
         "contato": "x", "email": "a@b", "hectares": 10}  # fmt: skip
    assert sem_dado_pessoal(x) == {"cod_imovel": "PA-1", "itens": [{"ha": 2}], "hectares": 10}


@pytest.mark.skipif(shutil.which("raiz") is None and not sys.executable, reason="sem o comando raiz")
def test_servidor_local_por_stdio():
    from mcp.client.client import Client
    from mcp.client.stdio import StdioServerParameters

    cmd = shutil.which("raiz")
    if cmd:
        par = StdioServerParameters(command=cmd, args=["mcp"], env={"RAIZ_CHAVE_API": "raiz_teste"})
    else:
        par = StdioServerParameters(command=sys.executable, args=["-c", "from raiz.cli import app; app()", "mcp"])

    async def ver():
        with anyio.fail_after(60):
            async with Client(par) as cli:
                assert {t.name for t in (await cli.list_tools()).tools} == FERRAMENTAS
                assert cli.server_info.name == "raiz"

    anyio.run(ver)
