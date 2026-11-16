"""Captura o que o executor realmente leu, sem download adicional nem retrospectiva.

Os invólucros valem apenas durante uma tarefa do município. Ao sair, restauram
as funções de produção; nenhuma entrada de outro município fica no retrato.
"""

from __future__ import annotations

import contextlib
import functools
import hashlib
import json
import math
import numbers
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from raiz.aprendizado.reexecucao import FONTES, HistoricoInsuficiente
from raiz.privacidade import colunas_pessoais

TEXTOS = {
    "uf": set("AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split()),
    "bioma": {"Amazônia", "Cerrado", "Mata Atlântica", "Caatinga", "Pantanal", "Pampa"},
    "caminho_terra": {"privada_matricula", "posse_em_titulacao", "assentamento", "publica_concessao",
                      "publica_sem_destinacao", "terra_indigena_ou_tradicional"},
    "status_imovel": {"AT", "PE", "SU", "CA"},
    "tipo_imovel": {"IRU", "AST", "PCT"},
    "filtro_territorial": {"ok", "atencao", "bloqueio"},
    "reserva_risco_fonte": {"fazenda"},
    "vazamento_motivo": {"mitigacao_vizinha", "sem_gado", "sem_vizinha", "sem_rebanho"},
    "linha_base_fonte": {"ybyra", "municipio", "cenario"},
}  # fmt: skip


# Lista positiva dos indicadores consumidos pelos modelos; colunas novas não
# entram no treino por parecerem numéricas. Atualizar junto ao modelo.
NUMERICOS = set(
    """
alem_RL_ha app_desmatada_ha app_recompor_ha area arrendamento_referencia_fonte
arrendamento_referencia_rs_ha_ano assentamento_ha bioma cabecas_deslocadas cacau_aptidao caminho_terra
captura_fator_ajuste captura_tco2_ha_ano_p50 captura_total_tco2_ha_p50 carbono_ha carbono_tco2_ano
chuva_mm_ano cidade_proxima_km cod_municipio_ibge credito_liquido_tco2_ano credito_liquido_tco2_contrato
credito_liquido_tco2_ha_ano credito_liquido_tco2_ha_ano_p10 credito_liquido_tco2_ha_ano_p90
custo_credito_usd custo_fator_ajuste custo_implantacao_ha_p50 declividade_media_pct deficit_RL_ha
derrubada_risco_ano_pct desconto_linha_base desconto_linha_base_pct desm_pos2008_ha desm_pos2016_ha
desm_pos2020_ha desm_total_ha divida_fracao divida_limitada_icsd divida_rs_ha dono_rs_ha_ano embargo_ha
estrada_acesso_km f_matricula fator_liquido filtro_territorial fogo_anos_media fogo_risco_ano_pct
gpw_ugpp grupo_credito_tco2_ano grupo_creditos_prazo grupo_fecha_contrato grupo_ha
grupo_ha_para_contrato grupo_id grupo_imoveis ha linha_base_fonte linha_base_medida_pct
linha_base_regenera_pct m_fiscal marcos_todos_chance_pct matricula_conferida matricula_ha
matricula_onus_graves mb_pasto_2025_ha mb_pasto_idade_anos_media mb_pasto_vigor_principal
mitigacao_vizinha modo_restauracao modo_restauracao_pontos modo_restauracao_regra multa_esperada_rs_ha
pasto_ate1km_ha pasto_ha pasto_idade_anos_media pasto_vigor_media perda_risco_ano_pct
preco_equilibrio_usd_t problema projeto_carbono_ha quilombo_ha rebanho_cab_p50 rebanho_cabecas
rebanho_fonte rebanho_pasto_ha regularizacao_proximo_passo rescisao_chance_pct reserva_risco_fonte
restauracao_area_ha restauracao_cenario restauracao_faltou restauracao_versao risco_terra secundaria_ha
sigef_ha solo_cec_cmolc_kg status_imovel taxa_supressao_secundaria_municipio taxa_tco2_ha_ano
terra_concessao terra_concessao_ha terra_publica_ha terra_sigef_assentamento_ha
terra_sigef_assentamento_titulado_ha terra_sigef_posse_ha terra_sigef_registrada_ha
terra_sigef_titulacao_ha terra_tradicional_ha terra_uc_publica_ha ti_funai_ha ti_ha tipo_imovel
tir_projeto_pct_arrendamento tir_projeto_pct_duas_fases tir_projeto_pct_p50 titulo_nota titulo_reprova
uc_protecao_integral_ha uf valor_desenvolvedor_rs vazamento_mitigacao vazamento_mitigacao_imovel
vazamento_motivo volume_contratado_tco2_ha
""".split()
)
PADRAO_NUMERICO = re.compile(
    r"(?:mb_(?:pasto|agricultura|veg_secundaria|supressao_secundaria|recuperacao_secundaria|fogo)_20\d{2}_ha"
    r"|pasto_d[0-3]_ha|linha_base_taxa_d[0-3])"
)
NUMERICOS.difference_update(TEXTOS)
NUMERICOS.difference_update(
    {
        "arrendamento_referencia_fonte",
        "grupo_id",
        "modo_restauracao",
        "modo_restauracao_regra",
        "rebanho_fonte",
        "regularizacao_proximo_passo",
        "restauracao_cenario",
        "restauracao_faltou",
        "restauracao_versao",
        "terra_concessao",
        "vazamento_mitigacao_imovel",
    }
)


def _numero(v):
    if isinstance(v, numbers.Real) and not isinstance(v, bool) and math.isfinite(float(v)):
        return float(v)
    return None


def sanitizar_entrada(nome_fonte: str, atributos: dict, contexto: dict) -> tuple[dict, dict]:
    """Só números, booleanos e categorias fechadas; nunca nomes ou texto livre."""
    if not isinstance(atributos, dict) or not isinstance(contexto, dict):
        raise HistoricoInsuficiente("entrada de modelo exige atributos e contexto estruturados")
    pessoais = set(colunas_pessoais(atributos))
    out = {}
    for k, v in atributos.items():
        if k in pessoais:
            continue
        if k == "cod_imovel":
            # A chave é conservada fora dos atributos pelo chamador.
            continue
        if isinstance(v, np.generic):
            v = v.item()
        if k in ("uf", "tipo_imovel", "status_imovel") and isinstance(v, str):
            v = v.upper()
        numerico = k in NUMERICOS or PADRAO_NUMERICO.fullmatch(k) is not None
        if isinstance(v, bool) and numerico:
            out[k] = v
        elif numerico and (n := _numero(v)) is not None:
            out[k] = n
        elif k in TEXTOS and isinstance(v, str) and v in TEXTOS[k]:
            out[k] = v
    ctx = {}
    if nome_fonte == "entrada_flag":
        ctx["pasto_baixo_vigor_ha"] = _numero(contexto.get("pasto_baixo_vigor_ha"))
    elif nome_fonte == "entrada_triagem":
        permitidos = {
            "cadeia.origem": {"chega_a_origem", "falta_ler_origem", "quebra", "sem_origem"},
            "geometria.car_sigef": {f"D{i}" for i in range(1, 8)},
        }
        ctx["achados"] = []
        for a in contexto.get("achados", []):
            regra, valor = a.get("regra"), a.get("valor")
            if regra in permitidos:
                # Valor desconhecido deve continuar impedindo triagem rápida.
                ctx["achados"].append(
                    {"regra": regra, "valor": valor if valor in permitidos[regra] else "desconhecido"}
                )
    elif nome_fonte == "entrada_rebanho":
        totais = contexto.get("totais")
        if not isinstance(totais, dict) or set(totais) != {"ppm", "ppm_2017", "censo_2017"}:
            raise HistoricoInsuficiente("rebanho sem os três totais históricos")
        ctx["totais"] = {k: _numero(v) for k, v in totais.items()}
    return out, ctx


@dataclass
class Captura:
    uf: str
    municipio: int
    dados: dict[str, pd.DataFrame] = field(default_factory=dict)
    entradas: dict[str, dict] = field(default_factory=dict)
    indisponiveis: set[str] = field(default_factory=set)

    def fonte(self, nome: str, df: pd.DataFrame) -> None:
        esp = FONTES[nome]
        df = df.copy()
        # Fontes vazias podem vir só com a coluna geometry.
        if df.empty:
            for c in esp.campos:
                if c not in df:
                    df[c] = pd.Series(dtype=object)
        if not set(esp.campos) <= set(df.columns):
            self.indisponiveis.add(nome)
            return
        campos = [*esp.campos, *(["geometry"] if esp.geometria else [])]
        self.dados[nome] = df[campos].copy()

    def entrada(self, modelo: str, linha: dict, contexto: dict | None = None):
        nome = f"entrada_{modelo}"
        atributos, ctx = sanitizar_entrada(nome, linha, contexto or {})
        cod = str(linha["cod_imovel"])
        self.entradas.setdefault(nome, {})[cod] = {"cod_imovel": cod, "atributos": atributos, "contexto": ctx}

    @contextlib.contextmanager
    def modelos(self):
        from raiz import flag, rebanho, restauracao
        from raiz.titulo import regularizacao, triagem

        orig = (flag.por_imovel, restauracao.por_imovel, regularizacao.avaliar, triagem.triar, rebanho.espalhar)

        @functools.wraps(orig[0])
        def flag_(linha, pasto_baixo_vigor_ha=None, r=None):
            result = orig[0](linha, pasto_baixo_vigor_ha, r)
            self.entrada("flag", linha, {"pasto_baixo_vigor_ha": pasto_baixo_vigor_ha})
            return result

        @functools.wraps(orig[1])
        def restauracao_(linha, c=None, r=None):
            result = orig[1](linha, c, r)
            self.entrada("restauracao", linha)
            return result

        @functools.wraps(orig[2])
        def regularizacao_(linha, r=None):
            result = orig[2](linha, r)
            self.entrada("regularizacao", linha)
            return result

        @functools.wraps(orig[3])
        def triagem_(linha, achados, r=None):
            result = orig[3](linha, achados, r)
            self.entrada("triagem", linha, {"achados": achados})
            return result

        @functools.wraps(orig[4])
        def rebanho_(linhas, cod_municipio, r=None, totais=None):
            usados = dict(totais) if totais is not None else {"ppm": None, "ppm_2017": None, "censo_2017": None}
            bovinos, censo = rebanho.bovinos_municipio, rebanho.censo_2017

            def bovinos_(*args, **kwargs):
                v = bovinos(*args, **kwargs)
                usados.update(ppm=v[0], ppm_2017=v[1])
                return v

            def censo_(*args, **kwargs):
                v = censo(*args, **kwargs)
                usados["censo_2017"] = v
                return v

            rebanho.bovinos_municipio, rebanho.censo_2017 = bovinos_, censo_
            try:
                result = orig[4](linhas, cod_municipio, r, totais)
            finally:
                rebanho.bovinos_municipio, rebanho.censo_2017 = bovinos, censo
            for li in linhas:
                self.entrada("rebanho", li, {"totais": usados})
            return result

        flag.por_imovel, restauracao.por_imovel = flag_, restauracao_
        regularizacao.avaliar, triagem.triar, rebanho.espalhar = regularizacao_, triagem_, rebanho_
        try:
            yield
        finally:
            flag.por_imovel, restauracao.por_imovel, regularizacao.avaliar, triagem.triar, rebanho.espalhar = orig

    @contextlib.contextmanager
    def motor(self, R, embargos):
        nomes = ("car_mun", "sigef", "camadas", "biomas", "alertas", "regeneracao")
        orig = {n: getattr(R, n) for n in nomes}

        def car(*args, **kw):
            df = orig["car_mun"](*args, **kw)
            d = df.copy()
            campos = [c for c in FONTES["car"].campos if c != "_hash"]
            if d.empty:
                for c in campos:
                    if c not in d:
                        d[c] = pd.Series(dtype=object)
            if "geometry" not in d or d.geometry.isna().any() or d.geometry.is_empty.any():
                self.indisponiveis.add("car")
                return df
            if set(campos) <= set(d):
                # Hash somente do contrato público e da geometria desta captura.
                d["_hash"] = [
                    hashlib.sha256(
                        json.dumps(
                            {**{c: str(li[c]) for c in campos}, "geom": li["geometry"].normalize().wkt}, sort_keys=True
                        ).encode()
                    ).hexdigest()
                    for li in d.to_dict("records")
                ]
                self.fonte("car", d)
            else:
                self.indisponiveis.add("car")
            return df

        def sigef(*args, **kw):
            df = orig["sigef"](*args, **kw)
            self.fonte("sigef", df)
            return df

        def camadas(*args, **kw):
            resultado = orig["camadas"](*args, **kw)
            for n, df in resultado[0].items():
                if n in ("yd", "acc", "nf", "hy", "ti", "uc"):
                    self.fonte(n, df)
            return resultado

        def biomas(*args, **kw):
            df = orig["biomas"](*args, **kw)
            self.fonte("biomas", df)
            return df

        def alertas(*args, **kw):
            df = orig["alertas"](*args, **kw)
            # O motor usa vazio quando não existe arquivo; não é coleta vazia.
            arq = Path(R.CACHE) / "alerta" / f"alerta_{self.uf}.parquet"
            if arq.exists():
                self.fonte("alertas", df.rename(columns={"ANODETEC": "anodetec"}))
            else:
                self.indisponiveis.add("alertas")
            return df

        def regeneracao(c, *args, **kw):
            alvos = c.index[c.frente.isin(["carbono", "regularizar_antes", "assentamento_agrupado"])]
            df = orig["regeneracao"](c, *args, **kw)
            campos = ("pasto_ha", "secundaria_ha", "pasto_ate1km_ha")
            if "car" not in self.dados or (len(alvos) and not set(campos) <= set(df)):
                self.indisponiveis.add("regeneracao")
                return df
            hashes = self.dados["car"].set_index("cod_imovel")["_hash"].to_dict()
            linhas = [
                {"cod_imovel": cod, "car_hash": hashes[cod], **{k: df.at[cod, k] for k in campos}} for cod in alvos
            ]
            reg = pd.DataFrame(linhas, columns=FONTES["regeneracao"].campos)
            if not reg.empty and reg[list(campos)].isna().any().any():
                self.indisponiveis.add("regeneracao")
            else:
                self.fonte("regeneracao", reg)
            return df

        for nome, fn in zip(nomes, (car, sigef, camadas, biomas, alertas, regeneracao), strict=True):
            setattr(R, nome, fn)
        try:
            yield
        finally:
            for nome, fn in orig.items():
                setattr(R, nome, fn)
            if embargos is not None:
                emb = embargos.rename(columns={c: c.lower() for c in embargos.columns})
                if "cod_municipio" in emb:
                    cods = pd.to_numeric(emb.cod_municipio, errors="coerce")
                    self.fonte("ibama", emb.loc[cods == self.municipio])
            proj = getattr(R, "PROJ", None)
            if proj is not None and len(proj):
                self.fonte("projetos", proj.to_crs(4674))
            else:
                # Pasta ausente/vazia não prova consulta completa ao registro.
                self.indisponiveis.add("projetos")

    def fontes_validas(self) -> dict[str, pd.DataFrame]:
        from raiz.aprendizado.arquivo_historico import _normalizar

        dados = {**self.dados, **{n: pd.DataFrame(list(rs.values())) for n, rs in self.entradas.items()}}
        validos = {}
        for nome, df in dados.items():
            conferir = {nome: df}
            if nome == "regeneracao" and "car" in validos:
                conferir["car"] = validos["car"]
            try:
                _normalizar(conferir, exigir_completo=False)
            except (ValueError, TypeError, KeyError):
                self.indisponiveis.add(nome)
            else:
                validos[nome] = df
        return validos

    def publicar(self, con) -> dict:
        from raiz.aprendizado.arquivo_historico import arquivar

        validos = self.fontes_validas()
        if not validos:
            return {"situacao": "sem_captura", "indisponiveis": sorted(self.indisponiveis)}
        r = arquivar(con, validos, self.uf, self.municipio, exigir_completo=False)
        return {**r, "situacao": "arquivado", "indisponiveis": sorted(self.indisponiveis)}
