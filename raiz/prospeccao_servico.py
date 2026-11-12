"""Um contrato de consulta para HTTP e adaptadores de ferramentas.

O chamador autentica o token com ``autenticar``; os identificadores de cliente
nunca vêm dos argumentos enviados pelo consumidor. A autorização da ficha e os
limites de leitura ficam aqui, independentemente do transporte.
"""

from __future__ import annotations

from sqlalchemy import Engine

from raiz import front_api, imovel_dados
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
    return imovel_dados.ficha_prospeccao(linha, front_api.versao(engine, codigo), front_api.do_banco(engine, codigo))


def consultar_ficha(engine: Engine, cliente_id: int, codigo_car: str, *, desbloquear: bool = False) -> dict:
    """Só devolve o contrato fechado; leitura já paga nunca debita novamente.

    A montagem precede o débito para não cobrar uma ficha cuja leitura falhou.
    O serviço de acesso verifica vigência, exclusividade e carteira na transação.
    """
    acesso.limitar(engine, f"cliente:{cliente_id}", "fichas", 30)
    if desbloquear:
        acesso.limitar(engine, f"cliente:{cliente_id}", "desbloqueios", 100, 86400)
        dado = _montar(engine, codigo_car)
        acesso.desbloquear(engine, cliente_id, codigo_car)
        return dado
    canonico = acesso.exigir_desbloqueio(engine, cliente_id, codigo_car)
    return _montar(engine, canonico)


def comparar_fichas(engine: Engine, cliente_id: int, codigos_car: list[str]) -> dict:
    """Compara de duas a cinco fichas liberadas; nunca compra acesso implicitamente."""
    if not isinstance(codigos_car, list) or not 2 <= len(codigos_car) <= 5:
        raise acesso.ErroAcesso(422, "Escolha de duas a cinco fazendas para comparar.")
    if any(not isinstance(car, str) or not 3 <= len(car) <= 80 for car in codigos_car):
        raise acesso.ErroAcesso(422, "Informe códigos do CAR válidos.")
    if len({normalizar_codigo(car) for car in codigos_car}) != len(codigos_car):
        raise acesso.ErroAcesso(422, "Escolha fazendas diferentes para comparar.")
    acesso.limitar(engine, f"cliente:{cliente_id}", "comparacoes", 10)
    # Autoriza todas antes de montar a primeira: uma ficha vedada não gera saída parcial.
    canonicos = [acesso.exigir_desbloqueio(engine, cliente_id, car) for car in codigos_car]
    return {"fichas": [consultar_ficha(engine, cliente_id, car) for car in canonicos]}


def exportar_ficha_pdf(engine: Engine, cliente_id: int, codigo_car: str) -> bytes:
    from raiz.prospeccao_pdf import gerar_pdf

    acesso.limitar(engine, f"cliente:{cliente_id}", "exportacoes", 5)
    return gerar_pdf(consultar_ficha(engine, cliente_id, codigo_car))
