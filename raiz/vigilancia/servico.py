"""O que as rotas e a linha de comando mostram: situação de um imóvel, de um projeto (com os eventos de perda, prazos,
rascunho do relatório e avisos), marcação de alertas e eventos do fundador, acerto por versão da regra e saúde das
fontes. Lê o estado (armazem.py) e as marcações e eventos que chegaram pela API e ainda não entraram na rodada.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
from functools import cached_property
from zoneinfo import ZoneInfo

import pandas as pd
import shapely

from raiz.vigilancia import aprendizado, aviso, aviso_verra, perdas, projetos, publicacao, relatorio
from raiz.vigilancia import regras as regras_mod
from raiz.vigilancia.armazem import TIPOS_EVENTO, Armazem
from raiz.vigilancia.config import Config, config
from raiz.vigilancia.fontes import NOMES
from raiz.vigilancia.fontes import data as _data
from raiz.vigilancia.privacidade import limpar_registro, mascarar

log = logging.getLogger(__name__)
FUSO = ZoneInfo("America/Sao_Paulo")


def hoje_brasil() -> dt.date:
    return dt.datetime.now(FUSO).date()


def _json_ok(v):
    if isinstance(v, dt.date | dt.datetime):
        return v.isoformat()
    if isinstance(v, float) and v != v:
        return None
    if isinstance(v, bytes | bytearray):
        return None
    if hasattr(v, "item"):
        return v.item()
    return v


def limpo(d):
    """Pronto para JSON: datas em texto, NaN vira null, sem bytes, sem chave pessoal e CPF/CNPJ mascarado."""
    if isinstance(d, dict):
        return limpar_registro({k: limpo(v) for k, v in d.items() if k != "geometria"})
    if isinstance(d, list):
        return [limpo(x) for x in d]
    return mascarar(_json_ok(d)) if isinstance(_json_ok(d), str) else _json_ok(d)


class Vigilancia:
    def __init__(
        self, cfg: Config | None = None, arm: Armazem | None = None, regras=None, lista_projetos=None, poligonos=None
    ):
        self.cfg = cfg or config()
        self.arm = arm or Armazem(self.cfg.estado)
        self.regras = regras or regras_mod.carregar()
        self._projetos = lista_projetos
        self._poligonos = poligonos
        self._areas: dict[str, object] = {}

    # ------------------------------------------------------------------ apoio

    @cached_property
    def projetos(self) -> dict[str, projetos.Projeto]:
        lista = self._projetos if self._projetos is not None else projetos.carregar()
        return {p.id: p for p in lista}

    @property
    def poligonos(self):
        if self._poligonos is None:
            from raiz.vigilancia.poligonos import Poligonos

            self._poligonos = Poligonos(self.cfg)
        return self._poligonos

    def areas(self, pid: str):
        if pid not in self._areas:
            p = self.projetos[pid]
            self._areas[pid] = projetos.areas(p, self.cfg, self.poligonos.geometria_imoveis)
        return self._areas[pid]

    def marcacoes(self) -> pd.DataFrame:
        base = self.arm.marcacoes()
        pend = self.arm.pendentes("marcacao")
        if pend:
            base = pd.concat([base, pd.DataFrame(pend)], ignore_index=True) if len(base) else pd.DataFrame(pend)
        return base

    def eventos(self) -> pd.DataFrame:
        base = self.arm.eventos()
        pend = self.arm.pendentes("evento")
        if pend:
            base = pd.concat([base, pd.DataFrame(pend)], ignore_index=True) if len(base) else pd.DataFrame(pend)
        return base

    def _marcacao_de(self, vig: pd.DataFrame, alerta_id: str) -> dict | None:
        if alerta_id not in vig.index:
            return None
        m = vig.loc[alerta_id]
        return {
            "verdadeiro": bool(m["verdadeiro"]),
            "fonte": m["fonte"],
            "quem": m["quem"],
            "observado_em": m["observado_em"],
            "evidencia": m.get("evidencia"),
        }

    def _alerta_json(self, a: pd.Series, vig: pd.DataFrame, espelho: dict | None = None) -> dict:
        d = {
            k: a.get(k)
            for k in (
                "alerta_id",
                "fonte",
                "chave",
                "classe",
                "tipo",
                "data_evento",
                "publicado_em",
                "visto_em",
                "area_ocorrencia_ha",
                "area_sobreposta_ha",
                "fracao_alvo",
                "borda",
                "gravidade",
                "estrato",
                "confianca",
                "novo",
                "regra_versao",
                "link",
                "lon",
                "lat",
                "papel",
                "area_projeto_ha",
            )
        }
        d["atributos"] = json.loads(a["atributos"]) if isinstance(a.get("atributos"), str) else {}
        if isinstance(a.get("classes_ha"), str):
            d["classes_ha"] = json.loads(a["classes_ha"])
        d["marcacao"] = self._marcacao_de(vig, a["alerta_id"])
        if a["fonte"] == "ibama_embargo" and espelho is not None:
            d["ativo"] = bool(espelho.get(str(a["chave"]), True))
        return d

    def _espelho(self) -> dict:
        e = self.arm.espelho_ibama()
        return dict(zip(e["seq_tad"].astype(str), e["ativo"], strict=False)) if e is not None and len(e) else {}

    def _fontes(self) -> dict:
        f = self.arm.fontes()
        return {n: {k: f.get(n, {}).get(k) for k in ("ultima_leitura", "ok", "situacao", "erro")} for n in NOMES}

    # ------------------------------------------------------------------ imóvel

    def imovel(
        self,
        cod: str,
        desde: dt.date | None = None,
        fonte: str | None = None,
        limite: int = 200,
        geo: bool = False,
        hoje: dt.date | None = None,
    ) -> dict | None:
        hoje = hoje or hoje_brasil()
        cod = cod.strip()
        al = self.arm.alertas("imovel", cod)
        info = None
        try:
            info = self.poligonos.info_imovel(cod)
        except Exception as ex:  # noqa: BLE001 (sem o Release dados, a rota ainda mostra os alertas)
            log.warning("info do imóvel indisponível: %s", type(ex).__name__)
        if info is None and not len(al):
            return None
        vig = aprendizado.vigentes(self.marcacoes()).set_index("alerta_id")
        esp = self._espelho()
        falsos = set(vig.index[~vig["verdadeiro"].astype(bool)]) if len(vig) else set()
        valid = al[~al["alerta_id"].isin(falsos)]
        d30 = hoje - dt.timedelta(days=30)
        recentes = valid[valid["data_evento"].map(lambda d: d is not None and d >= d30)]
        ibama = valid[valid["fonte"] == "ibama_embargo"]
        embargo_ativo = any(esp.get(str(c), True) for c in ibama["chave"]) if len(ibama) else False
        if embargo_ativo or (len(recentes) and recentes["gravidade"].isin(["alta", "media"]).any()):
            situacao = "alerta"
        elif len(valid[valid["data_evento"].map(lambda d: d is not None and d >= hoje - dt.timedelta(days=365))]):
            situacao = "atencao"
        else:
            situacao = "sem_alerta"
        lista = al
        if desde:
            lista = lista[lista["data_evento"].map(lambda d: d is not None and d >= desde)]
        if fonte:
            lista = lista[lista["fonte"] == fonte]
        lista = lista.sort_values(["data_evento", "visto_em"], ascending=False, na_position="last")
        marcados = vig[vig.index.isin(al["alerta_id"])] if len(vig) else vig
        projs = [pid for pid, p in self.projetos.items() if cod in [str(x) for x in p.get("imoveis") or []]]
        out = {
            "cod_imovel": cod,
            **{k: v for k, v in (info or {}).items() if k != "cod_imovel"},
            "situacao": situacao,
            "resumo": {
                "alertas": int(len(al)),
                "alertas_30d": int(len(recentes)),
                "area_alertada_30d_ha": round(float(recentes["area_sobreposta_ha"].sum()), 4) if len(recentes) else 0.0,
                "por_fonte": {str(k): int(v) for k, v in al["fonte"].value_counts().items()},
                "por_tipo": {str(k): int(v) for k, v in valid["tipo"].value_counts().items()},
                "ultimo_alerta": max((d for d in valid["data_evento"] if d is not None), default=None),
                "embargo_ativo": embargo_ativo,
                "verdadeiros": int(marcados["verdadeiro"].astype(bool).sum()) if len(marcados) else 0,
                "falsos": int((~marcados["verdadeiro"].astype(bool)).sum()) if len(marcados) else 0,
                "sem_marcacao": int(len(al) - len(marcados)),
            },
            "projetos": projs,
            "alertas": [self._alerta_json(a, vig, esp) for _, a in lista.head(limite).iterrows()],
            "regra_versao": self.regras.versao,
            "fontes": self._fontes(),
            "atualizado_em": (self.arm.rodadas(1) or [{}])[-1].get("fim"),
        }
        if geo:
            out["geojson"] = _geojson(lista.head(limite))
        return limpo(out)

    # ------------------------------------------------------------------ projeto

    def perdas(self, pid: str, hoje: dt.date | None = None) -> tuple[list[dict], pd.DataFrame]:
        hoje = hoje or hoje_brasil()
        p = self.projetos[pid]
        alertas = self.arm.alertas("projeto", pid)
        areas = None
        if len(alertas):
            try:
                areas = self.areas(pid)
            except Exception as ex:  # noqa: BLE001
                log.warning("áreas do projeto %s indisponíveis: %s", pid, ex)
        return perdas.calcular(
            p,
            alertas,
            self.marcacoes(),
            self.eventos(),
            self.arm.registro_perdas(),
            self.regras,
            hoje,
            areas=areas,
            alertas_imoveis=self.arm.alertas("imovel"),
        )

    def projeto(self, pid: str, hoje: dt.date | None = None, geo: bool = False, limite: int = 200) -> dict | None:
        if pid not in self.projetos:
            return None
        hoje = hoje or hoje_brasil()
        p = self.projetos[pid]
        lista, _ = self.perdas(pid, hoje)
        criados = self.arm.ler_privado_json("avisos_criados.json", {}) or {}
        ev = self.eventos()
        for pe in lista:
            pe["avisos"] = aviso.avisos(pe, p, self.regras, ev, criados, hoje)
            pe["relatorio"] = {
                "pt": f"/vigilancia/projeto/{pid}/perdas/{pe['perda_id']}/relatorio?idioma=pt",
                "en": f"/vigilancia/projeto/{pid}/perdas/{pe['perda_id']}/relatorio?idioma=en",
                "kml": f"/vigilancia/projeto/{pid}/perdas/{pe['perda_id']}/kml",
            }
            pe["aviso_verra"] = {
                "rascunho": f"/vigilancia/projeto/{pid}/perdas/{pe['perda_id']}/aviso-verra",
                "eml": f"/vigilancia/projeto/{pid}/perdas/{pe['perda_id']}/aviso-verra.eml",
            }
        al = self.arm.alertas("projeto", pid)
        vig = aprendizado.vigentes(self.marcacoes()).set_index("alerta_id")
        areas_info, avisos_poligono = [], []
        try:
            a = self.areas(pid)
            areas_info = [
                {
                    "classe": r["classe"],
                    "papel": r["papel"],
                    "ha": round(float(r["ha"]), 2),
                    "declarado_ha": None if pd.isna(r["declarado_ha"]) else float(r["declarado_ha"]),
                }
                for _, r in a.iterrows()
            ]
            avisos_poligono = projetos.conferir_areas(a)
            carbono = a[a["papel"] == "projeto"]
            area_carbono = float(shapely.union_all(carbono.geometry.values).area) / 1e4 if len(carbono) else 0.0
        except Exception as ex:  # noqa: BLE001
            avisos_poligono = [f"polígono do projeto indisponível: {type(ex).__name__}"]
            area_carbono = None
        v = self.regras.verra
        out = {
            "id": pid,
            "nome_projeto": p.nome,
            "padrao": p.get("padrao"),
            "verra_id": p.get("verra_id"),
            "inicio": p.inicio,
            "cliente": p.get("cliente"),
            "vcus_emitidos": p.get("vcus_emitidos"),
            "area_carbono_ha": round(area_carbono, 2) if area_carbono is not None else None,
            "areas": areas_info,
            "avisos_poligono": avisos_poligono
            + ([] if p.inicio else ["início do projeto não informado: toda perda conta (conservador)"]),
            "situacao": perdas.situacao_projeto(lista),
            "regra": {
                "versao": self.regras.versao,
                "aviso_verra_dias": v["aviso_verra_dias"],
                "relatorio_anos": v["relatorio_anos"],
                "limiar_evento_pct": v["limiar_evento_pct"],
                "documento": v["documento"],
                "modelo_relatorio": v["modelo_relatorio"],
                "base": v["base"],
            },
            "perdas": lista,
            "avisos_verra_informados": self.avisos_verra_informados(hoje, pid),
            "alertas": [
                self._alerta_json(a, vig)
                for _, a in al.sort_values("data_evento", ascending=False, na_position="last").head(limite).iterrows()
            ],
            "fontes": self._fontes(),
        }
        if geo:
            out["geojson"] = _geojson(al.head(limite))
        return limpo(out)

    def _perda(self, pid: str, perda_id: str, hoje: dt.date | None = None) -> dict | None:
        if pid not in self.projetos:
            return None
        lista, _ = self.perdas(pid, hoje)
        return next((p for p in lista if p["perda_id"] == perda_id), None)

    def relatorio(self, pid: str, perda_id: str, idioma: str = "pt", hoje: dt.date | None = None) -> str | None:
        hoje = hoje or hoje_brasil()
        pe = self._perda(pid, perda_id, hoje)
        if pe is None:
            return None
        return mascarar(relatorio.rascunho(self.projetos[pid], pe, self.regras, hoje, idioma))

    def kml(self, pid: str, perda_id: str) -> str | None:
        pe = self._perda(pid, perda_id)
        return relatorio.kml_da_perda(self.projetos[pid], pe) if pe else None

    def aviso_verra(self, pid: str, perda_id: str, hoje: dt.date | None = None) -> dict | None:
        hoje = hoje or hoje_brasil()
        if pid not in self.projetos:
            return None
        pe = self._perda(pid, perda_id, hoje) if len(self.arm.alertas("projeto", pid)) else None
        prazo = aviso_verra.prazo_registrado(self.projetos[pid], perda_id)
        if pe is None and prazo is None:
            return None
        ev = self.eventos()
        confirmado = perdas._ultimo_evento(ev, perda_id, ("verra_avisada",))
        encerramento = perdas._ultimo_evento(ev, perda_id, ("perda_descartada", "perda_reaberta", "relatorio_enviado"))
        d = aviso_verra.preparar(
            self.projetos[pid],
            perda_id,
            self.regras,
            hoje,
            perda=pe,
            prazo_informado=prazo,
            envio_confirmado_em=_data(confirmado["data"]) if confirmado else None,
            encerrado=bool(encerramento and encerramento["tipo"] in ("perda_descartada", "relatorio_enviado")),
        )
        if pe is None:
            d["origem_prazo"] = "informado_pelo_cliente_e_registrado_no_projeto"
        return d

    def avisos_verra_informados(self, hoje: dt.date | None = None, pid: str | None = None) -> list[dict]:
        hoje = hoje or hoje_brasil()
        out = []
        for projeto in self.projetos.values():
            if pid is not None and projeto.id != pid:
                continue
            for registro in projeto.get("avisos_verra_informados") or []:
                d = self.aviso_verra(projeto.id, registro["perda_id"], hoje)
                if d:
                    base = f"/vigilancia/projeto/{projeto.id}/perdas/{registro['perda_id']}"
                    out.append({**d, "rascunho": f"{base}/aviso-verra", "eml": f"{base}/aviso-verra.eml"})
        return out

    def avisos(self, estado: str | None = None, hoje: dt.date | None = None) -> list[dict]:
        hoje = hoje or hoje_brasil()
        criados = self.arm.ler_privado_json("avisos_criados.json", {}) or {}
        ev = self.eventos()
        out = []
        for pid, p in self.projetos.items():
            for pe in self.perdas(pid, hoje)[0]:
                out += aviso.avisos(pe, p, self.regras, ev, criados, hoje)
        if estado:
            out = [a for a in out if a["estado"] == estado]
        return limpo(sorted(out, key=lambda a: (a["criado_em"], a["aviso_id"]), reverse=True))

    # ------------------------------------------------------------------ marcação e eventos (entram como entrada)

    def marcar(
        self,
        alerta_id: str,
        verdadeiro: bool,
        fonte: str,
        quem: str,
        evidencia: str = "",
        observado_em: dt.date | None = None,
    ) -> dict:
        if alerta_id not in set(self.arm.alertas()["alerta_id"]):
            raise KeyError("alerta não encontrado")
        m = aprendizado.marcacao(alerta_id, verdadeiro, fonte, quem, evidencia, observado_em)
        caminho = self.arm.nova_entrada("marcacao", m)
        return {**limpo(m), "publicada": self._enviar(caminho)}

    def evento(self, alvo: str, alvo_id: str, tipo: str, data: dt.date | None, quem: str, nota: str = "") -> dict:
        if alvo not in TIPOS_EVENTO or tipo not in TIPOS_EVENTO[alvo]:
            raise ValueError(f"evento inválido; para {alvo}: {', '.join(TIPOS_EVENTO.get(alvo, ()))}")
        if tipo == "descoberta_informada" and not nota.strip():
            raise ValueError("descoberta informada precisa de justificativa na nota")
        agora = dt.datetime.now(dt.UTC)
        e = {
            "evento_id": hashlib.sha1(f"{alvo}|{alvo_id}|{tipo}|{agora.isoformat()}".encode()).hexdigest()[:16],
            "alvo": alvo,
            "alvo_id": alvo_id,
            "tipo": tipo,
            "data": (data or hoje_brasil()).isoformat(),
            "quem": mascarar(str(quem or "").strip().lower() or "nao_informado")[:40],
            "nota": mascarar(str(nota or ""))[:1000],
            "registrado_em": agora.isoformat(timespec="seconds"),
        }
        caminho = self.arm.nova_entrada("evento", e)
        return {**e, "publicada": self._enviar(caminho)}

    def _enviar(self, caminho) -> bool:
        try:
            return publicacao.enviar_entrada(publicacao.Release(self.cfg), self.cfg.chave, caminho)
        except Exception as ex:  # noqa: BLE001 (fica local; a rodada não vê até subir)
            log.warning("entrada não subiu para o Release: %s", type(ex).__name__)
            return False

    # ------------------------------------------------------------------ aprendizado e saúde

    def acerto(self) -> list[dict]:
        return limpo(aprendizado.acerto(self.arm.alertas(), self.marcacoes()))

    def saude(self, hoje: dt.date | None = None) -> dict:
        hoje = hoje or hoje_brasil()
        rod = self.arm.rodadas(1)
        ultima = rod[-1] if rod else {}
        fim = _data(ultima.get("fim"))
        return limpo(
            {
                "ultima_rodada": ultima.get("fim"),
                "dias_desde_a_ultima": (hoje - fim).days if fim else None,
                "atrasada": (fim is None) or (hoje - fim).days > 1,
                "fontes": self._fontes(),
                "regra_versao": self.regras.versao,
                "entradas_pendentes": len(self.arm.entradas()),
            }
        )


def _geojson(al: pd.DataFrame) -> dict:
    feats = []
    for _, a in al.iterrows():
        g = a.get("geometria")
        if not isinstance(g, bytes | bytearray):
            continue
        geom = shapely.geometry.mapping(shapely.from_wkb(g))
        feats.append(
            {
                "type": "Feature",
                "geometry": geom,
                "properties": {
                    k: _json_ok(a.get(k)) for k in ("alerta_id", "fonte", "tipo", "data_evento", "gravidade")
                },
            }
        )
    return {"type": "FeatureCollection", "features": feats}
