"""Um contrato de consulta para HTTP e adaptadores de ferramentas.

O chamador autentica o token com ``autenticar``; os identificadores de cliente
nunca vêm dos argumentos enviados pelo consumidor. A autorização da ficha e os
limites de leitura ficam aqui, independentemente do transporte.
"""

from __future__ import annotations

from sqlalchemy import Engine

from raiz import busca, front_api, imovel_dados, prospeccao_protecao, prospeccao_versoes, terra_comprometida
from raiz import prospeccao_acesso as acesso
from raiz.busca import normalizar_codigo
from raiz.pedidos import servico as pedidos


def autenticar(engine: Engine, token: str) -> int:
    if not isinstance(token, str) or not token.strip():
        raise acesso.ErroAcesso(401, "Entre na sua conta para consultar fazendas.")
    cliente_id = pedidos.cliente_da_sessao(engine, token.strip())
    if cliente_id is None:
        raise acesso.ErroAcesso(401, "Sua sessão expirou. Entre novamente.")
    limitar_consulta(engine, cliente_id)
    return cliente_id


def limitar_consulta(engine: Engine, cliente_id: int) -> None:
    """Mesmo contador na API da ficha e em hosts de ferramentas autenticados."""
    acesso.limitar(engine, f"cliente:{cliente_id}", "consultas", 60)


def _montar(engine: Engine, codigo_car: str) -> dict:
    linhas = front_api.imoveis_do_municipio(engine, cod_imovel=codigo_car)
    if not linhas:
        raise acesso.ErroAcesso(404, "Fazenda ainda não disponível na base da Raíz.")
    linha = linhas[0]
    codigo = linha["cod_imovel"]
    banco = front_api.do_banco(engine, codigo)
    with engine.connect() as con:
        banco["terra_comprometida"] = terra_comprometida.por_codigos(con, [codigo]).get(codigo)
    return imovel_dados.ficha_prospeccao(linha, front_api.versao(engine, codigo), banco)


def consultar_ficha(
    engine: Engine, cliente_id: int, codigo_car: str, *, desbloquear: bool = False, canal: str = "site"
) -> dict:
    """Só devolve o contrato fechado; leitura já paga nunca debita novamente.

    A montagem precede o débito para não cobrar uma ficha cuja leitura falhou.
    O serviço de acesso verifica vigência, exclusividade e carteira na transação.
    """
    with prospeccao_protecao.operacao_vigiada(
        engine, cliente_id, acao="ficha", canal=canal, codigos_car=[codigo_car]
    ) as concluir:
        acesso.limitar(engine, f"cliente:{cliente_id}", "fichas", 30)
        if desbloquear:
            acesso.limitar(engine, f"cliente:{cliente_id}", "desbloqueios", 100, 86400)
            dado = _montar(engine, codigo_car)
            acesso.desbloquear(engine, cliente_id, codigo_car)
        else:
            canonico = acesso.exigir_desbloqueio(engine, cliente_id, codigo_car)
            dado = _montar(engine, canonico)
        with prospeccao_versoes.consultas(engine, cliente_id, [dado]) as fichas:
            resposta = fichas[0]
            concluir(resposta)
        return resposta


def comparar_fichas(engine: Engine, cliente_id: int, codigos_car: list[str], *, canal: str = "site") -> dict:
    """Compara de duas a cinco fichas liberadas; nunca compra acesso implicitamente."""
    with prospeccao_protecao.operacao_vigiada(
        engine,
        cliente_id,
        acao="comparacao",
        canal=canal,
        codigos_car=codigos_car if isinstance(codigos_car, list) else (),
    ) as concluir:
        if not isinstance(codigos_car, list) or not 2 <= len(codigos_car) <= 5:
            raise acesso.ErroAcesso(422, "Escolha de duas a cinco fazendas para comparar.")
        if any(not isinstance(car, str) or not 3 <= len(car) <= 80 for car in codigos_car):
            raise acesso.ErroAcesso(422, "Informe códigos do CAR válidos.")
        if len({normalizar_codigo(car) for car in codigos_car}) != len(codigos_car):
            raise acesso.ErroAcesso(422, "Escolha fazendas diferentes para comparar.")
        acesso.limitar(engine, f"cliente:{cliente_id}", "comparacoes", 10)
        # Autoriza todas antes de montar a primeira; o histórico só avança quando o conjunto funciona.
        canonicos = [acesso.exigir_desbloqueio(engine, cliente_id, car) for car in codigos_car]
        dados = []
        for car in canonicos:
            acesso.limitar(engine, f"cliente:{cliente_id}", "fichas", 30)
            dados.append(_montar(engine, car))
        with prospeccao_versoes.consultas(engine, cliente_id, dados) as fichas:
            resposta = {"fichas": fichas}
            concluir(resposta)
        return resposta


def exportar_ficha_pdf(engine: Engine, cliente_id: int, codigo_car: str) -> bytes:
    return exportar_ficha(engine, cliente_id, codigo_car, formato="pdf")


def exportar_ficha(engine: Engine, cliente_id: int, codigo_car: str, *, formato: str = "json") -> bytes:
    """Exportação identificada por cliente; falha de renderização não avança a última consulta."""
    from raiz.prospeccao_pdf import gerar_pdf

    with prospeccao_protecao.operacao_vigiada(
        engine,
        cliente_id,
        acao=f"exportacao_{formato}" if formato in {"pdf", "json", "csv"} else "exportacao_json",
        codigos_car=[codigo_car],
    ) as concluir:
        if formato not in {"pdf", "json", "csv"}:
            raise acesso.ErroAcesso(422, "Escolha PDF, JSON ou CSV para exportar a ficha.")
        acesso.limitar(engine, f"cliente:{cliente_id}", "exportacoes", 5)
        acesso.limitar(engine, f"cliente:{cliente_id}", "fichas", 30)
        canonico = acesso.exigir_desbloqueio(engine, cliente_id, codigo_car)
        marca = prospeccao_protecao.registrar_marca(engine, cliente_id)
        dado = _montar(engine, canonico)
        with prospeccao_versoes.consultas(engine, cliente_id, [dado]) as fichas:
            if formato == "pdf":
                conteudo = gerar_pdf(fichas[0], marca=marca)
            elif formato == "json":
                conteudo = prospeccao_protecao.gerar_json(fichas[0], marca)
            else:
                conteudo = prospeccao_protecao.gerar_csv(fichas[0], marca)
            concluir(fichas[0])
        return conteudo


def historico_ficha(engine: Engine, cliente_id: int, codigo_car: str, *, limite: int = 20) -> dict:
    with prospeccao_protecao.operacao_vigiada(engine, cliente_id, acao="historico", codigos_car=[codigo_car]):
        acesso.limitar(engine, f"cliente:{cliente_id}", "historicos", 30)
        canonico = acesso.exigir_desbloqueio(engine, cliente_id, codigo_car)
        return prospeccao_versoes.historico(engine, cliente_id, canonico, limite=limite)


def buscar_fazendas(
    engine: Engine, cliente_id: int, filtros: busca.FiltrosProspeccao, *, pagina: int = 1, limite: int = 20
) -> dict:
    import hashlib
    import json

    consulta_hash = hashlib.sha256(
        json.dumps(filtros.model_dump(exclude_none=True), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    with prospeccao_protecao.operacao_vigiada(
        engine, cliente_id, acao="busca", pagina=pagina, consulta_hash=consulta_hash
    ) as concluir:
        acesso.limitar(engine, f"cliente:{cliente_id}", "busca", 30)
        resposta = busca.buscar_prospeccao(
            engine, filtros, cliente_id=cliente_id, pagina=pagina, limite=limite, incluir_imoveis=True
        )
        concluir(resposta)
        return resposta


def ler_visual(engine: Engine, cliente_id: int, codigo_car: str, leitor, *, acao: str):
    """As camadas visuais pagas também participam do controle de varredura."""
    with prospeccao_protecao.operacao_vigiada(engine, cliente_id, acao="visual", codigos_car=[codigo_car]):
        acesso.limitar(engine, f"cliente:{cliente_id}", "visuais", 30)
        canonico = acesso.exigir_desbloqueio(engine, cliente_id, codigo_car)
        return leitor(engine, canonico)
