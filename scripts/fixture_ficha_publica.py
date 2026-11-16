"""Servidor efêmero do smoke visual EPREL: renderizador e rotas reais, registros fictícios.

Não cria engine, não consulta banco ou Release e só escuta em loopback. O portão em memória
permite conferir o que o navegador mostra quando o aceite é retirado; autorização e SQL
continuam cobertos pelos testes de integração com PostGIS.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import socket
from unittest.mock import patch

import uvicorn
from fastapi import FastAPI

from raiz import publico, publico_versoes


def _versao(rodada: int, corte: dt.date, area: float) -> publico_versoes.VersaoPublica:
    basico = {
        "codigo": "AB23CD",
        "rodada_id": rodada,
        "data_corte": corte.isoformat(),
        "municipio": "Parauapebas",
        "uf": "PA",
        "area_car_ha": area,
        "situacao_basica": "apto",
        "fonte": publico_versoes.FONTE,
    }
    assinatura = hashlib.sha256(
        json.dumps(basico, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()
    return publico_versoes.VersaoPublica(
        **{**basico, "data_corte": corte},
        sha256=assinatura,
        registrada_em=dt.datetime(2026, 11, 12, 12, tzinfo=dt.UTC),
    )


def main() -> None:
    antiga = _versao(1, dt.date(2026, 1, 10), 123.5)
    atual = _versao(2, dt.date(2026, 2, 10), 300.25)
    consentimento = {"aceito": True}
    engine_ficticia = object()

    def obter(engine, codigo, identificador):
        assert engine is engine_ficticia, "O smoke não usa banco."
        if not consentimento["aceito"] or codigo != antiga.codigo:
            return None
        if identificador == antiga.identificador:
            return antiga, atual
        return (atual, None) if identificador == atual.identificador else None

    app = FastAPI()
    app.include_router(publico.roteador(lambda _: engine_ficticia))

    @app.post("/__teste/aceite/{estado}")
    def aceite(estado: str):
        consentimento["aceito"] = estado == "aceito"
        return {"aceito": consentimento["aceito"]}

    with socket.socket() as escuta:
        escuta.bind(("127.0.0.1", 0))
        escuta.listen(8)
        servidor = uvicorn.Server(uvicorn.Config(app, log_level="critical"))
        manifesto = {
            "cenario": "Ficha básica inteiramente fictícia para teste visual; sem banco ou Release.",
            "origem": f"http://127.0.0.1:{escuta.getsockname()[1]}",
            "antiga": antiga.caminho,
            "atual": atual.caminho,
        }
        print(json.dumps(manifesto), flush=True)
        with patch.object(publico_versoes, "obter", obter):
            servidor.run(sockets=[escuta])


if __name__ == "__main__":
    main()
