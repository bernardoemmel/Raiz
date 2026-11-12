"""Linha de comando da vigilância.

    python -m raiz.vigilancia rodar [--baixar] [--publicar] [--fontes firms,deter] [--ufs PA,TO] [--hoje AAAA-MM-DD]
                                    [--resumo ARQUIVO] [--detalhe]
    python -m raiz.vigilancia imovel PA-1507300-...
    python -m raiz.vigilancia projeto URTX
    python -m raiz.vigilancia relatorio URTX URTX_LE1 [--idioma en] [--kml]
    python -m raiz.vigilancia marcar <alerta_id> verdadeiro|falso --fonte campo --quem fundador [--evidencia ...]
    python -m raiz.vigilancia evento perda|aviso <id> <tipo> --quem fundador [--data AAAA-MM-DD] [--nota ...]
    python -m raiz.vigilancia avisos [--estado aguardando_aprovacao]
    python -m raiz.vigilancia acerto
    python -m raiz.vigilancia baixar                 traz o estado publicado (com a chave, também a parte privada)
    python -m raiz.vigilancia exportar-aprendizado PASTA   previsões e gabaritos no formato de raiz/aprendizado
    python -m raiz.vigilancia chave                  gera uma chave nova para RAIZ_VIGILANCIA_CHAVE
    python -m raiz.vigilancia servir [--porta 8010]

Saída em JSON. `rodar` termina com código 1 se alguma fonte deu erro (o GitHub avisa o fundador), depois de publicar
o que deu certo; fonte sem credencial só avisa.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import sys
from pathlib import Path


class _LogSeguro(logging.Formatter):
    def format(self, record):
        from raiz.logs_seguros import sanitizar_log

        return sanitizar_log(super().format(record))


def _log() -> None:
    h = logging.StreamHandler()
    h.setFormatter(_LogSeguro("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[h], force=True)


def _imprimir(dado) -> None:
    print(json.dumps(dado, ensure_ascii=False, indent=1, default=str))


def _data(s: str | None) -> dt.date | None:
    return dt.date.fromisoformat(s) if s else None


def main(argv: list[str] | None = None) -> int:
    _log()
    ap = argparse.ArgumentParser(prog="python -m raiz.vigilancia", description="Vigilância das fazendas e projetos")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("rodar", help="rodada diária")
    r.add_argument("--baixar", action="store_true", help="baixar antes o estado publicado no Release")
    r.add_argument("--publicar", action="store_true", help="publicar no Release no fim")
    r.add_argument("--fontes", help="só estas fontes, separadas por vírgula")
    r.add_argument("--ufs", help="só estas UFs do Release dados, separadas por vírgula")
    r.add_argument("--hoje", help="data da rodada (AAAA-MM-DD); padrão: hoje em Brasília")
    r.add_argument("--resumo", help="arquivo onde acrescentar o resumo em Markdown (ex.: $GITHUB_STEP_SUMMARY)")
    r.add_argument("--detalhe", action="store_true", help="mostrar também os projetos (não usar em log público)")

    i = sub.add_parser("imovel")
    i.add_argument("cod")
    i.add_argument("--desde")
    i.add_argument("--fonte")
    i.add_argument("--limite", type=int, default=50)

    p = sub.add_parser("projeto")
    p.add_argument("id")

    rel = sub.add_parser("relatorio")
    rel.add_argument("projeto")
    rel.add_argument("perda")
    rel.add_argument("--idioma", default="pt", choices=["pt", "en"])
    rel.add_argument("--kml", action="store_true", help="mostrar o KML da área afetada no lugar do relatório")

    m = sub.add_parser("marcar")
    m.add_argument("alerta_id")
    m.add_argument("resultado", choices=["verdadeiro", "falso"])
    m.add_argument("--fonte", required=True, choices=["campo", "cliente", "imagem_nova", "fonte_oficial"])
    m.add_argument("--quem", required=True, help="papel de quem marca (fundador, cliente, campo), nunca nome")
    m.add_argument("--evidencia", default="")
    m.add_argument("--observado-em")

    e = sub.add_parser("evento")
    e.add_argument("alvo", choices=["perda", "aviso"])
    e.add_argument("id")
    e.add_argument("tipo")
    e.add_argument("--quem", required=True)
    e.add_argument("--data")
    e.add_argument("--nota", default="")

    a = sub.add_parser("avisos")
    a.add_argument("--estado")

    sub.add_parser("acerto")
    sub.add_parser("baixar")
    x = sub.add_parser("exportar-aprendizado")
    x.add_argument("pasta")
    sub.add_parser("chave")
    sv = sub.add_parser("servir")
    sv.add_argument("--porta", type=int, default=8010)
    sv.add_argument("--host", default="127.0.0.1")

    args = ap.parse_args(argv)

    if args.cmd == "chave":
        from raiz.vigilancia.publicacao import gerar_chave

        print(gerar_chave())
        return 0

    if args.cmd == "servir":
        import uvicorn

        from raiz.vigilancia.servidor import criar_app

        uvicorn.run(criar_app(), host=args.host, port=args.porta, log_config=None, access_log=False)
        return 0

    if args.cmd == "rodar":
        from raiz.vigilancia.rodada import resumo_markdown, rodar

        res = rodar(
            hoje=_data(args.hoje),
            fontes=[f.strip() for f in args.fontes.split(",")] if args.fontes else None,
            baixar=args.baixar,
            publicar=args.publicar,
            ufs=[u.strip().upper() for u in args.ufs.split(",")] if args.ufs else None,
        )
        _imprimir(res if args.detalhe else {k: res[k] for k in ("publico", "entradas") if k in res})
        if args.resumo:
            with open(args.resumo, "a", encoding="utf-8") as f:
                f.write(resumo_markdown(res))
        erro = any(f.get("situacao") == "erro" for f in res.get("fontes", {}).values())
        erro = erro or bool((res.get("publicar") or {}).get("erro")) or bool((res.get("baixar") or {}).get("erro"))
        return 1 if erro else 0

    from raiz.vigilancia.servico import Vigilancia

    v = Vigilancia()
    if args.cmd == "imovel":
        from raiz.vigilancia.api import normalizar_cod

        d = v.imovel(normalizar_cod(args.cod), desde=_data(args.desde), fonte=args.fonte, limite=args.limite)
        _imprimir(d if d is not None else {"erro": "imóvel sem polígono no Release dados e sem alerta"})
        return 0 if d is not None else 2
    if args.cmd == "projeto":
        d = v.projeto(args.id)
        _imprimir(d if d is not None else {"erro": "projeto não cadastrado"})
        return 0 if d is not None else 2
    if args.cmd == "relatorio":
        t = v.kml(args.projeto, args.perda) if args.kml else v.relatorio(args.projeto, args.perda, args.idioma)
        if t is None:
            _imprimir({"erro": "evento de perda não encontrado"})
            return 2
        print(t)
        return 0
    if args.cmd == "marcar":
        _imprimir(
            v.marcar(
                args.alerta_id,
                args.resultado == "verdadeiro",
                args.fonte,
                args.quem,
                args.evidencia,
                _data(args.observado_em),
            )
        )
        return 0
    if args.cmd == "evento":
        _imprimir(v.evento(args.alvo, args.id, args.tipo, _data(args.data), args.quem, args.nota))
        return 0
    if args.cmd == "avisos":
        _imprimir(v.avisos(args.estado))
        return 0
    if args.cmd == "acerto":
        _imprimir(v.acerto())
        return 0
    if args.cmd == "baixar":
        from raiz.vigilancia import publicacao

        _imprimir(publicacao.baixar_estado(v.arm, publicacao.Release(v.cfg), v.cfg.chave))
        return 0
    if args.cmd == "exportar-aprendizado":
        import pandas as pd

        from raiz.vigilancia import aprendizado

        prev, gab = aprendizado.exportar(v.arm.alertas(), v.marcacoes())
        pasta = Path(args.pasta)
        pasta.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(prev).to_csv(pasta / "vigilancia_previsoes.csv", index=False)
        pd.DataFrame(gab).to_csv(pasta / "vigilancia_gabaritos.csv", index=False)
        _imprimir({"previsoes": len(prev), "gabaritos": len(gab), "pasta": str(pasta)})
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
