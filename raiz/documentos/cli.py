"""Linha de comando: python -m raiz.documentos <assunto> <ação> ...

  certidao ler ARQ.pdf [--imovel COD] [--municipio COD]   lê, confere com o motor e grava
  certidao lote PASTA [--municipio COD]                    lê todos os PDF da pasta
  certidao reconferir LEITURA_ID                           refaz a conferência (motor ou regra nova), sem nova leitura
  certidao saida MUNICIPIO [...]                           grava matricula_<mun>.csv e matricula_conferencia_<mun>.csv
  busca semanal [--sem-firecrawl] [--fontes sfb,dou]       registros e editais novos da semana
  gerar folha COD_IMOVEL [--pdf]                           folha de 3 páginas para o dono
  gerar lote --municipio COD (--grupo ID | --imoveis A,B | --frente carbono) [--pdf]
  gerar edital FONTE [lote como acima] [--pdf]             lê o edital (PDF, página ou --leitura ID) e monta o checklist
  aprendizado marcar LEITURA_ID --fonte F (--confirma | --real SITUACAO) [--campo area_ha=290 ...]
  aprendizado fila | placar | exportar PASTA [--banco]
  modelos                                                  reconstrói os .docx de modelo

Nada de nome ou CPF sai na tela: arquivos aparecem pelo sha256, e os textos já vêm mascarados.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from raiz.documentos.privacidade import configurar_log

log = logging.getLogger("raiz.documentos")


def _leitor(a):
    from raiz.documentos.claude import LeitorClaude

    return LeitorClaude(modelo=a.modelo, esforco=a.esforco)


def _manual(caminho: str | None) -> dict | None:
    return json.loads(Path(caminho).read_text(encoding="utf-8")) if caminho else None


def _mostrar_certidao(r, rotulo: str) -> None:
    lt = r.leitura
    if r.erro:
        print(f"{rotulo}: leitura {lt.id} falhou: {r.erro}")
        return
    print(f"{rotulo}: leitura {lt.id} ({lt.modelo}, {lt.prompt_versao}) chave {lt.chave}")
    for c in r.conferencias:
        alvo = c.cod_imovel or "sem imóvel no motor"
        conf = " (pede confirmação)" if c.precisa_confirmar else ""
        print(f"  {alvo}: {c.situacao.upper()}{conf}")
        if c.resumo():
            print(f"    {c.resumo()}")


def cmd_certidao(a) -> int:
    from raiz.documentos.certidao import leitor, saida

    if a.acao == "ler":
        r = leitor.ler_certidao(
            a.arquivo, cod_imovel=a.imovel, cod_municipio=a.municipio, leitor=_leitor(a), json_manual=_manual(a.manual)
        )
        _mostrar_certidao(r, f"arquivo {r.leitura.arquivo_sha256[:12]}")
        return 1 if r.erro else 0
    if a.acao == "lote":
        pdfs = sorted(Path(a.arquivo).glob("*.pdf"))
        erros = 0
        for i, p in enumerate(pdfs, 1):
            r = leitor.ler_certidao(p, cod_municipio=a.municipio, leitor=_leitor(a))
            _mostrar_certidao(r, f"[{i}/{len(pdfs)}] arquivo {r.leitura.arquivo_sha256[:12]}")
            erros += bool(r.erro)
        if a.municipio:
            print("saída:", *saida.gravar_municipio(a.municipio))
        return 1 if erros else 0
    if a.acao == "reconferir":
        r = leitor.reconferir(int(a.arquivo), cod_imovel=a.imovel, cod_municipio=a.municipio)
        _mostrar_certidao(r, "reconferência")
        return 0
    if a.acao == "saida":
        for m in [a.arquivo, *a.mais]:
            print(*saida.gravar_municipio(int(m)))
        return 0
    return 2


def cmd_busca(a) -> int:
    from raiz.documentos.busca import semanal

    so = a.fontes.split(",") if a.fontes else None
    rel = semanal.rodar(usar_firecrawl=not a.sem_firecrawl, so=so)
    for f in rel.fontes:
        estado = f"erro: {f.erro}" if f.erro and not f.itens else f"{len(f.itens)} itens ({f.via})"
        print(f"{f.fonte}: {estado}")
    print(f"{len(rel.novidades)} novidades. Lista: {rel.arquivo_md}")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
            f.write(f"arquivo_md={rel.arquivo_md}\narquivo_csv={rel.arquivo_csv}\n")
            f.write(f"tem_novidade={1 if rel.tem_novidade else 0}\n")
    return 0


def _lote(a) -> list[str]:
    from raiz.documentos.gerados import dados

    if a.imoveis:
        return [c.strip() for c in a.imoveis.split(",") if c.strip()]
    if not a.municipio:
        raise SystemExit("diga o município (--municipio) junto com --grupo ou --frente")
    if a.grupo:
        return dados.imoveis_do_grupo(a.grupo, a.municipio)
    return dados.imoveis_do_municipio(a.municipio, a.frente.split(",") if a.frente else None)


def _pdf(caminho: Path, pedir: bool) -> None:
    print("docx:", caminho)
    if pedir:
        from raiz.documentos.gerados.conversao import para_pdf

        print("pdf:", para_pdf(caminho))


def cmd_gerar(a) -> int:
    from raiz.documentos.gerados import checklist_edital, edital, folha_dono, relatorio_lote

    if a.tipo == "folha":
        _pdf(folha_dono.gerar(a.alvo, cod_municipio=a.municipio), a.pdf)
        return 0
    if a.tipo == "lote":
        cods = _lote(a)
        nome = a.nome or a.grupo or (f"{a.municipio}_{a.frente}" if a.frente else str(a.municipio or "lote"))
        _pdf(relatorio_lote.gerar(cods, nome, cod_municipio=a.municipio, rho=a.rho), a.pdf)
        return 0
    if a.tipo == "edital":
        from raiz.documentos.armazem import Armazem

        if a.leitura:
            lt = Armazem().leitura(a.leitura)
        else:
            lt = edital.ler_edital(a.alvo, leitor=_leitor(a), json_manual=_manual(a.manual))
        if lt is None or lt.erro:
            print("leitura do edital falhou:", lt.erro if lt else "não existe")
            return 1
        cods = _lote(a) if (a.imoveis or a.grupo or a.frente) else None
        _pdf(checklist_edital.gerar(lt, cods, cod_municipio=a.municipio), a.pdf)
        return 0
    return 2


def cmd_aprendizado(a) -> int:
    from raiz.documentos import aprendizado

    if a.acao == "marcar":
        campos = dict(c.split("=", 1) for c in a.campo or [])
        g = aprendizado.marcar(
            int(a.alvo),
            fonte=a.fonte,
            confirma=True if a.confirma else None,
            situacao_real=a.real,
            campos=campos,
            observado_em=a.data,
            nota=a.nota,
        )
        print(json.dumps(g, ensure_ascii=False, indent=2, default=str))
        return 0
    if a.acao == "fila":
        for f in aprendizado.fila_revisao():
            print(json.dumps(f, ensure_ascii=False))
        return 0
    if a.acao == "placar":
        print(json.dumps(aprendizado.placar(), ensure_ascii=False, indent=2))
        return 0
    if a.acao == "exportar":
        if a.banco:
            print(aprendizado.enviar_ao_banco())
        else:
            print(*aprendizado.exportar(Path(a.alvo or ".")))
        return 0
    return 2


def principal(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m raiz.documentos", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("-v", "--detalhe", action="store_true", help="mostra o log de cada passo")
    sub = p.add_subparsers(dest="assunto", required=True)

    def modelo(sp):
        sp.add_argument("--modelo", help="modelo da Anthropic (padrão: RAIZ_MODELO_DOCUMENTO ou claude-opus-5-5)")
        sp.add_argument("--esforco", choices=["low", "medium", "high", "xhigh", "max"])

    def lote(sp):
        sp.add_argument("--municipio", type=int, help="código IBGE do município")
        sp.add_argument("--imoveis", help="códigos do CAR separados por vírgula")
        sp.add_argument("--grupo", help="grupo_id do desenvolvedor_<mun>.csv")
        sp.add_argument("--frente", help="frentes do motor, separadas por vírgula (ex.: carbono)")

    c = sub.add_parser("certidao", help="certidão de matrícula")
    c.add_argument("acao", choices=["ler", "lote", "reconferir", "saida"])
    c.add_argument("arquivo", help="PDF, pasta, id da leitura ou município")
    c.add_argument("mais", nargs="*", help="outros municípios (saida)")
    c.add_argument("--imovel", help="código do CAR do imóvel")
    c.add_argument("--municipio", type=int)
    c.add_argument("--manual", help="JSON da leitura feita por gente (vira modelo 'humano')")
    modelo(c)
    c.set_defaults(func=cmd_certidao)

    b = sub.add_parser("busca", help="registros e editais novos")
    b.add_argument("acao", choices=["semanal"])
    b.add_argument("--sem-firecrawl", action="store_true")
    b.add_argument("--fontes", help="só estas fontes (verra,sfb,ideflor_bio,dou)")
    b.set_defaults(func=cmd_busca)

    g = sub.add_parser("gerar", help="documentos .docx")
    g.add_argument("tipo", choices=["folha", "lote", "edital"])
    g.add_argument("alvo", nargs="?", help="código do CAR (folha) ou edital: PDF ou endereço (edital)")
    lote(g)
    g.add_argument("--nome", help="nome do lote")
    g.add_argument(
        "--rho",
        type=float,
        default=None,
        help="parte comum do erro entre imóveis na carteira (padrão: a do lote, restauracao.yaml)",
    )
    g.add_argument("--leitura", type=int, help="usa uma leitura de edital já gravada")
    g.add_argument("--manual", help="JSON da leitura do edital feita por gente")
    g.add_argument("--pdf", action="store_true", help="também gera o PDF (LibreOffice)")
    modelo(g)
    g.set_defaults(func=cmd_gerar)

    ap = sub.add_parser("aprendizado", help="gabarito, fila de revisão, placar e exportação")
    ap.add_argument("acao", choices=["marcar", "fila", "placar", "exportar"])
    ap.add_argument("alvo", nargs="?", help="id da leitura (marcar) ou pasta (exportar)")
    ap.add_argument("--fonte", default="conferencia_humana", help="quem conferiu: cartorio, onr, conferencia_humana")
    ap.add_argument("--confirma", action="store_true", help="a certidão real confirma a leitura")
    ap.add_argument("--real", choices=["conferida", "divergente", "cancelada", "revisar"], help="situação real")
    ap.add_argument("--campo", action="append", help="campo conferido, ex.: area_ha=290 (repete)")
    ap.add_argument("--data", help="quando foi conferido (AAAA-MM-DD)")
    ap.add_argument("--nota")
    ap.add_argument("--banco", action="store_true", help="registra no banco do back-end em vez de CSV")
    ap.set_defaults(func=cmd_aprendizado)

    m = sub.add_parser("modelos", help="reconstrói os .docx de modelo")
    m.set_defaults(
        func=lambda a: (
            print(
                *__import__("raiz.documentos.gerados.construir_modelos", fromlist=["construir"]).construir(), sep="\n"
            )
            or 0
        )
    )

    a = p.parse_args(argv)
    configurar_log(logging.INFO if a.detalhe else logging.WARNING)
    if a.assunto == "gerar" and a.tipo in ("folha", "edital") and not (a.alvo or getattr(a, "leitura", None)):
        p.error("diga o imóvel (folha) ou o edital")
    return a.func(a) or 0


if __name__ == "__main__":
    sys.exit(principal())
