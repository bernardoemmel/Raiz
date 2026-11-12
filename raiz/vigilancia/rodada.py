"""Rodada diária da vigilância (GitHub Actions, .github/workflows/vigilancia.yml).

1. Baixa o estado publicado no Release `vigilancia` (só o que mudou) e junta as marcações e eventos da API.
2. Lê cada fonte; fonte que falha não derruba as outras (fica registrada como erro e a rodada termina com erro).
3. Cruza com os imóveis do Release `dados` e com as áreas dos projetos e guarda os alertas novos com a versão da regra.
4. Marca sozinha o que imagem nova ou fonte oficial já resolveu.
5. Recalcula os eventos de perda de cada projeto (número fixo, prazo, rascunho do relatório, KML e avisos).
6. Publica: parte pública aberta e parte privada cifrada; manifesto por último.
"""

from __future__ import annotations

import datetime as dt
import logging
import time

import geopandas as gpd
import pandas as pd

from raiz.vigilancia import aprendizado, aviso, aviso_verra, cruzamento, projetos, publicacao, relatorio
from raiz.vigilancia import regras as regras_mod
from raiz.vigilancia.armazem import Armazem
from raiz.vigilancia.config import Config, config
from raiz.vigilancia.fontes import NOMES, Contexto, Leitura, firms, ibama, inpe, mapbiomas_alerta
from raiz.vigilancia.poligonos import Poligonos
from raiz.vigilancia.rede import limpo
from raiz.vigilancia.servico import Vigilancia, hoje_brasil

log = logging.getLogger(__name__)


def _ufs_e_caixas(pol: Poligonos, areas: dict[str, gpd.GeoDataFrame]) -> tuple[list[str], list[tuple]]:
    ufs, caixas = set(pol.ufs()), []
    for uf in pol.ufs():
        ind = pol.indice(uf)
        if ind:
            xs = list(ind.values())
            caixas.append((min(c[0] for c in xs), min(c[1] for c in xs), max(c[2] for c in xs), max(c[3] for c in xs)))
    for a in areas.values():
        if a is None or not len(a):
            continue
        x0, y0, x1, y1 = a.to_crs(4674).total_bounds
        caixas.append((x0 - 0.05, y0 - 0.05, x1 + 0.05, y1 + 0.05))
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        for uf in pol.ufs():
            if any(c[0] <= cx <= c[2] and c[1] <= cy <= c[3] for c in pol.indice(uf).values()):
                ufs.add(uf)
                break
    return sorted(ufs), caixas


def _ler(nome: str, ctx: Contexto, estado: dict, arm: Armazem, refazer_ibama: bool) -> Leitura:
    if nome == "firms":
        return firms.ler(ctx, estado)
    if nome == "deter":
        return inpe.ler_deter(ctx, estado)
    if nome == "prodes":
        return inpe.ler_prodes(ctx, estado)
    if nome == "mapbiomas_alerta":
        return mapbiomas_alerta.ler(ctx, estado)
    if nome == "ibama_embargo":
        return ibama.ler(ctx, estado, arm.espelho_ibama(), refazer=refazer_ibama)
    raise ValueError(f"fonte desconhecida: {nome}")


def rodar(
    cfg: Config | None = None,
    hoje: dt.date | None = None,
    fontes: list[str] | None = None,
    baixar: bool = False,
    publicar: bool = False,
    ufs: list[str] | None = None,
    lista_projetos: list | None = None,
    poligonos: Poligonos | None = None,
) -> dict:
    cfg = cfg or config()
    hoje = hoje or hoje_brasil()
    inicio = dt.datetime.now(dt.UTC)
    regras = regras_mod.carregar()
    arm = Armazem(cfg.estado)
    rel = publicacao.Release(cfg)
    res: dict = {"inicio": inicio.isoformat(timespec="seconds"), "hoje": hoje.isoformat(), "regra": regras.versao}

    if baixar:
        try:
            res["baixar"] = publicacao.baixar_estado(arm, rel, cfg.chave)
        except Exception as ex:  # noqa: BLE001 (sem estado anterior, a rodada recomeça e não publica por cima)
            res["baixar"] = {"erro": limpo(str(ex))}
            publicar = False
            log.error("não consegui baixar o estado publicado: %s; a rodada não vai publicar", limpo(str(ex)))
    res["entradas"] = arm.incorporar_entradas()

    lista = lista_projetos if lista_projetos is not None else projetos.carregar()
    pol = poligonos or Poligonos(cfg, ufs)
    areas: dict[str, gpd.GeoDataFrame] = {}
    for p in lista:
        try:
            areas[p.id] = projetos.areas(p, cfg, pol.geometria_imoveis)
        except Exception as ex:  # noqa: BLE001
            log.error("projeto %s sem área: %s", p.id, limpo(str(ex)))
    ufs_vig, caixas = _ufs_e_caixas(pol, areas)
    ctx = Contexto(regras=regras, cfg=cfg, hoje=hoje, ufs=ufs_vig, caixas=caixas)
    area_proj = pd.concat(list(areas.values()), ignore_index=True) if areas else None
    if area_proj is not None:
        area_proj = gpd.GeoDataFrame(area_proj, geometry="geometry", crs=5880)

    estado = arm.fontes()
    versoes = pol.versoes()
    refazer_ibama = estado.get("_poligonos") != versoes
    contagem = aprendizado.contagem(arm.alertas(), arm.marcacoes())
    leituras: dict[str, Leitura] = {}
    por_fonte: dict[str, dict] = {}
    for nome in fontes or list(NOMES):
        t0 = time.monotonic()
        anterior = estado.get(nome, {})
        try:
            leitura = _ler(nome, ctx, anterior, arm, refazer_ibama)
            oc = leitura.ocorrencias.reset_index(drop=True)
            pares = [cruzamento.cruzar_imoveis(oc, pol)]
            if area_proj is not None:
                pares.append(cruzamento.cruzar_projetos(oc, area_proj))
            pares = [x for x in pares if x is not None and len(x)]
            todos = pd.concat(pares, ignore_index=True) if pares else pd.DataFrame()
            alertas = cruzamento.montar_alertas(oc, todos, regras, hoje, contagem)
            novos = arm.gravar_alertas(alertas)
            if nome == "ibama_embargo" and "espelho" in leitura.extras:
                arm.gravar_espelho_ibama(leitura.extras["espelho"])
            leituras[nome] = leitura
            im = novos[novos["alvo_tipo"] == "imovel"] if len(novos) else novos
            por_fonte[nome] = {
                "situacao": "ok",
                "ocorrencias": int(len(oc)),
                "alertas_novos_imovel": int(len(im)),
                "imoveis_com_alerta_novo": int(im["alvo_id"].nunique()) if len(im) else 0,
                "alertas_novos_projeto": int(len(novos) - len(im)),
                "nota": leitura.nota,
            }
            estado[nome] = {
                "ultima_leitura": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
                "primeira_leitura": anterior.get("primeira_leitura") or hoje.isoformat(),
                "ok": True,
                "situacao": "ok",
                "erro": None,
                "cursor": leitura.cursor,
                "nota": leitura.nota,
            }
        except mapbiomas_alerta.SemCredencial as ex:
            por_fonte[nome] = {"situacao": "sem_credencial", "nota": str(ex)}
            estado[nome] = {**anterior, "ok": False, "situacao": "sem_credencial", "erro": str(ex)}
        except Exception as ex:  # noqa: BLE001 (uma fonte fora do ar não para as outras)
            msg = limpo(f"{type(ex).__name__}: {ex}")[:500]
            log.exception("fonte %s falhou", nome)
            por_fonte[nome] = {"situacao": "erro", "erro": msg}
            estado[nome] = {**anterior, "ok": False, "situacao": "erro", "erro": msg, "falhou_em": hoje.isoformat()}
        por_fonte[nome]["segundos"] = round(time.monotonic() - t0, 1)
    if "ibama_embargo" not in por_fonte or por_fonte["ibama_embargo"]["situacao"] == "ok":
        estado["_poligonos"] = versoes
    arm.gravar_fontes(estado)
    res["fontes"] = por_fonte

    # marcação automática (imagem nova e fonte oficial)
    mb = leituras.get("mapbiomas_alerta")
    status_mb = {}
    if mb is not None and len(mb.ocorrencias):
        status_mb = {
            str(c): (a or {}).get("status")
            for c, a in zip(mb.ocorrencias["chave"], mb.ocorrencias["atributos"], strict=True)
        }
    ib = leituras.get("ibama_embargo")
    cancelados = ib.extras.get("cancelados") if ib is not None else None
    prodes_lidos = (estado.get("prodes", {}).get("cursor") or {}).get("anos_lidos")
    novas = aprendizado.marcar_automatico(
        arm.alertas(), arm.marcacoes(), regras, hoje, prodes_lidos, cancelados, status_mb
    )
    res["marcacoes_automaticas"] = arm.gravar_marcacoes(novas)

    # eventos de perda dos projetos: número fixo, rascunhos, KML e avisos
    vig = Vigilancia(cfg, arm, regras, lista, pol)
    vig._areas.update(areas)
    registro = arm.registro_perdas()
    criados = arm.ler_privado_json("avisos_criados.json", {}) or {}
    pasta_rel = arm.privado / "relatorios"
    pasta_rel.mkdir(parents=True, exist_ok=True)
    resumo_proj = {}
    for p in lista:
        try:
            lista_perdas, registro = perdas_do_projeto(vig, p, registro, hoje)
            arm.gravar_registro_perdas(registro)
            ev = vig.eventos()
            avs = []
            for pe in lista_perdas:
                for idioma in ("pt", "en"):
                    (pasta_rel / f"{pe['perda_id']}_{idioma}.md").write_text(
                        relatorio.rascunho(p, pe, regras, hoje, idioma), encoding="utf-8"
                    )
                (pasta_rel / f"{pe['perda_id']}.kml").write_text(relatorio.kml_da_perda(p, pe), encoding="utf-8")
                (pasta_rel / f"{pe['perda_id']}_aviso_verra.eml").write_text(
                    aviso_verra.eml(aviso_verra.preparar(p, pe["perda_id"], regras, hoje, perda=pe)), encoding="utf-8"
                )
                avs += aviso.avisos(pe, p, regras, ev, criados, hoje)
            resumo_proj[p.id] = {
                "perdas_abertas": sum(1 for x in lista_perdas if x["estado"] in ("suspeita", "confirmada")),
                "avisos_aguardando": sum(1 for a in avs if a["estado"] == "aguardando_aprovacao"),
            }
        except Exception as ex:  # noqa: BLE001
            log.exception("perdas do projeto %s falharam", p.id)
            resumo_proj[p.id] = {"erro": limpo(str(ex))[:300]}
    arm.gravar_privado_json("avisos_criados.json", criados)
    arm.gravar_privado_json("acerto.json", aprendizado.acerto(arm.alertas(), arm.marcacoes()))
    res["projetos"] = resumo_proj  # fica fora do público: vai só no log local e na parte cifrada

    fim = dt.datetime.now(dt.UTC)
    publico = {
        "inicio": res["inicio"],
        "fim": fim.isoformat(timespec="seconds"),
        "hoje": hoje.isoformat(),
        "regra": regras.versao,
        "fontes": por_fonte,
        "marcacoes_automaticas": res["marcacoes_automaticas"],
        "ufs": ufs_vig,
        "poligonos": versoes,
    }
    arm.registrar_rodada(publico)
    res["fim"] = publico["fim"]
    if publicar:
        try:
            res["publicar"] = publicacao.publicar(
                arm, rel, cfg.chave, resumo=publico, entradas_lidas=(res.get("baixar") or {}).get("entradas")
            )
        except Exception as ex:  # noqa: BLE001
            res["publicar"] = {"erro": limpo(str(ex))}
            log.exception("publicação falhou")
    res["publico"] = publico
    res["sem_chave"] = not cfg.chave
    return res


def perdas_do_projeto(vig: Vigilancia, p, registro: pd.DataFrame, hoje: dt.date):
    from raiz.vigilancia import perdas

    return perdas.calcular(
        p,
        vig.arm.alertas("projeto", p.id),
        vig.marcacoes(),
        vig.eventos(),
        registro,
        vig.regras,
        hoje,
        areas=vig._areas.get(p.id),
        alertas_imoveis=vig.arm.alertas("imovel"),
    )


def resumo_markdown(res: dict) -> str:
    """Resumo da rodada para o GITHUB_STEP_SUMMARY (público: só contagens, nada de projeto ou cliente)."""
    linhas = [f"## Vigilância de {res['hoje']}", "", f"Regra `{res['regra']}`.", ""]
    linhas += [
        "| Fonte | Situação | Ocorrências | Alertas novos em imóveis | Imóveis | Segundos |",
        "|---|---|---|---|---|---|",
    ]
    for nome, f in res.get("fontes", {}).items():
        linhas.append(
            f"| {nome} | {f.get('situacao')} | {f.get('ocorrencias', '')} | {f.get('alertas_novos_imovel', '')} | "
            f"{f.get('imoveis_com_alerta_novo', '')} | {f.get('segundos', '')} |"
        )
    linhas.append("")
    linhas.append(f"Marcações automáticas: {res.get('marcacoes_automaticas', 0)}.")
    erros = {n: f.get("erro") or f.get("nota") for n, f in res.get("fontes", {}).items() if f.get("situacao") != "ok"}
    for n, e in erros.items():
        linhas.append(f"- {n}: {e}")
    if res.get("sem_chave"):
        linhas.append("- Sem RAIZ_VIGILANCIA_CHAVE: a parte privada (projetos, perdas, marcações) não foi guardada.")
    pub = res.get("publicar") or {}
    if pub.get("erro"):
        linhas.append(f"- Publicação falhou: {pub['erro']}")
    elif pub:
        linhas.append(f"Publicado no Release: {len(pub.get('subidos', []))} arquivos.")
    return "\n".join(linhas) + "\n"
