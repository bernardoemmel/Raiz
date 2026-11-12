"""API real e banco descartável para o Playwright; nunca usar como servidor do produto.

Só aceita banco local cujo nome termina em _e2e. O link de entrada é entregue a
uma caixa postal temporária, sem SMTP, e o Pix permanece no modo local de teste.
"""

import argparse
import base64
import datetime as dt
import json
import os
import secrets
from pathlib import Path

import uvicorn
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from raiz import RAIZ_REPO
from raiz import salvaguardas as SG
from raiz.banco import desfazer, migrar
from raiz.carga import carregar_pasta
from raiz.pedidos import servico
from raiz.pessoal import gerar_chave


def banco():
    url = os.environ["RAIZ_BANCO_URL_TESTE"]
    destino = make_url(url)
    if destino.host not in {"localhost", "127.0.0.1"} or not (destino.database or "").endswith("_e2e"):
        raise RuntimeError("O Playwright precisa de banco local descartável com nome terminado em _e2e")
    return url


def responder_interesses(pedido_id: str) -> None:
    """Substitui somente as respostas externas dos donos, usando o serviço real."""
    engine = create_engine(banco())
    try:
        for cod in servico.contatados_do_pedido(engine, pedido_id):
            servico.registrar_resposta(
                engine, cod, "interessado", "teste", None, "termo-e2e", pedido_id, avancar_pedidos=False
            )
        if servico.avancar(engine, pedido_id) != "grupo_pronto":
            raise RuntimeError("A oferta da amostra não fechou o grupo de um milhão de créditos")
    finally:
        engine.dispose()


def evidencias_sinteticas(engine) -> None:
    """A amostra não tem documentos/limites reais; esta geometria só vale no banco descartável."""
    hoje = dt.datetime.now(dt.UTC).date()
    ev = SG.Evidencia(sha256="e" * 64, data=hoje)
    with engine.begin() as con:
        # Polígono arbitrário e idêntico para o fixture, nunca publicável como limite cadastral.
        con.execute(
            text("""update funil.imovel set geom=ST_Multi(ST_GeomFromText(
        'POLYGON((-47 -1,-46.99 -1,-46.99 -0.99,-47 -0.99,-47 -1))',4674)) where uf='PA'""")
        )
        cods = list(con.execute(text("select cod_imovel from funil.imovel where uf='PA'")).scalars())
    if not cods:
        raise RuntimeError("A amostra do E2E precisa de imóveis do Pará")
    SG.registrar_cobertura(engine, SG.Cobertura(uf="PA", evidencia=ev, valida_ate=hoje))
    for cod in cods:
        SG.registrar_verificacao(engine, cod, SG.Verificacao(verificacao=ev, territorio_tradicional=False))
    # Imóveis da amostra já marcados como tradicionais continuam impedidos sem CLPI;
    # a reserva valida somente o grupo elegível que o motor de fato selecionou.


def servir() -> None:
    if os.environ.get("RAIZ_ABACATEPAY_CHAVE") or os.environ.get("RAIZ_ABACATEPAY_WEBHOOK_SEGREDO"):
        raise RuntimeError("O E2E não aceita credenciais de pagamento")
    url = banco()
    os.environ["RAIZ_CHAVE_PESSOAL"] = gerar_chave()
    os.environ["RAIZ_RECIBO_CHAVE"] = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()
    os.environ["RAIZ_API_ORIGENS"] = "http://127.0.0.1:4173"
    os.environ["RAIZ_FRONT_URL"] = "http://127.0.0.1:4173"
    os.environ["RAIZ_API_PUBLICA_URL"] = "http://127.0.0.1:8765"
    from raiz.config import config

    config.cache_clear()
    desfazer(url)
    migrar(url)
    engine = create_engine(url)
    carregar_pasta(engine, RAIZ_REPO / "dados" / "amostra", dt.date(2026, 11, 12))
    evidencias_sinteticas(engine)

    pasta = Path(os.environ["RAIZ_E2E_ESTADO"])
    pasta.mkdir(mode=0o700, parents=True, exist_ok=True)

    def entregar(email: str, link: str) -> None:
        # Não imprimir nem anexar tokens nos relatórios do Playwright/CI.
        arquivo = pasta / "entrada.json"
        arquivo.write_text(json.dumps({"email": email, "link": link}), encoding="utf-8")
        arquivo.chmod(0o600)

    from raiz.api import criar_app

    app = criar_app(engine=engine, grafo=object(), deps=object(), whatsapp=False)
    servico.ENVIO_LINK = entregar
    (pasta / "pronto").touch()
    try:
        uvicorn.run(app, host="127.0.0.1", port=8765, access_log=False)
    finally:
        engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interesses", metavar="PEDIDO_ID")
    args = parser.parse_args()
    if args.interesses:
        responder_interesses(args.interesses)
    else:
        servir()
