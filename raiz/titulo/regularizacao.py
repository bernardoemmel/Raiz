"""Regularização da posse: para cada imóvel em posse (ou lote de assentamento), o que falta para o título sair.

Regra em raiz/regras/padroes/regularizacao.yaml (versão + hash vão em cada linha). Entradas, pelo nome das colunas:
imoveis_<mun>.csv (motor: ha, m_fiscal, status_imovel, desmatamento por período, embargo, TI, UC, SIGEF),
filtros_<mun>.csv (TI da FUNAI, quilombo, UC por grupo) e terra_<mun>.csv (caminho da terra e sobreposições com o
SIGEF por situação da parcela). Sem terra_<mun>.csv, o caminho é calculado das colunas do motor (raiz/terra.py).

Saídas: regularizacao_<mun>.csv (uma linha por imóvel; nao_se_aplica fora da posse e do assentamento) e
achados_<mun>.csv (cada requisito como achado da fase "regularizacao", raiz/titulo/achados.py).

Evidência de ocupação por satélite: área aberta até 2008 = desmatamento acumulado menos o desmatamento depois de 2008
(PRODES, colunas do motor). Os requisitos pessoais (sem outro imóvel, sem benefício anterior) ficam sempre "conferir":
a Raíz não usa CPF.

Aprendizado: a chance a priori de o título sair em 12 meses entra congelada como previsão (alvo
titulo_regularizado_12m, modelo "regularizacao"); o gabarito vem sozinho quando o imóvel passa a ter matrícula no
caminho da terra (1) ou quando o horizonte vence sem título (0).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import math
from functools import lru_cache
from pathlib import Path

import yaml

from raiz.titulo.achados import COLUNAS as COLUNAS_ACHADO
from raiz.titulo.achados import Achado, chave_registro, gravidade_da_situacao

ARQ_REGRA = Path(__file__).resolve().parents[1] / "regras" / "padroes" / "regularizacao.yaml"
CLASSES = ("em_titulacao", "pronta_para_pedir", "falta_georreferenciamento", "pendente", "impedida", "nao_se_aplica")
CAMINHOS_ALVO = ("posse_em_titulacao", "assentamento")
ATIVO = {"AT", "ATIVO", "ATIVA"}
PENDENTE_CAR = {"PE", "PENDENTE"}  # CAR com pendência no SICAR: conferir, não impede pedir o título
# "conferir" que segura a classe: sem a evidência de ocupação ou acima do limite de área, não dá para dizer "pronta"
CONFERIR_SEGURA = {"ocupacao_antes_marco", "area_limite"}
ALVO = "titulo_regularizado_12m"
HORIZONTE_DIAS = 365


@lru_cache
def _ler(arq: Path, _marca: tuple) -> dict:
    texto = arq.read_bytes()
    r = yaml.safe_load(texto)
    r["versao_completa"] = f"{r['versao']}+{hashlib.sha256(texto).hexdigest()[:8]}"
    return r


def regra(arq: Path | None = None) -> dict:
    a = Path(arq or ARQ_REGRA)
    return _ler(a, (str(a), a.stat().st_mtime_ns, a.stat().st_size))


def versao() -> str:
    return regra()["versao_completa"]


def _num(linha: dict, *cols) -> float | None:
    for c in cols:
        v = linha.get(c)
        if v is None or isinstance(v, bool):
            continue
        try:
            x = float(v)
        except (TypeError, ValueError):
            continue
        if not math.isnan(x):
            return x
    return None


def _n0(linha: dict, *cols) -> float:
    return _num(linha, *cols) or 0.0


def _ha(x: float) -> str:
    return f"{x:,.1f}".replace(",", "§").replace(".", ",").replace("§", ".")


def orgao(uf: str, r: dict | None = None) -> str:
    r = r or regra()
    est = (r.get("orgaos_estaduais") or {}).get(uf)
    if uf in (r.get("amazonia_legal") or []):
        return f"INCRA ou {est}" if est else "INCRA ou órgão de terras do estado"
    return est or "órgão de terras do estado"


def ocupacao(linha: dict) -> dict:
    """Área aberta até 2008, até 2016 e até 2020 (PRODES, colunas do motor), em ha. None quando falta a coluna."""
    total = _num(linha, "desm_total_ha")
    if total is None:
        return {"ate_2008": None, "ate_2016": None, "ate_2020": None}
    return {
        "ate_2008": max(total - _n0(linha, "desm_pos2008_ha"), 0.0)
        if _num(linha, "desm_pos2008_ha") is not None
        else None,
        "ate_2016": max(total - _n0(linha, "desm_pos2016_ha"), 0.0)
        if _num(linha, "desm_pos2016_ha") is not None
        else None,
        "ate_2020": max(total - _n0(linha, "desm_pos2020_ha"), 0.0)
        if _num(linha, "desm_pos2020_ha") is not None
        else None,
    }


def requisitos(linha: dict, r: dict | None = None) -> list[dict]:
    """Cada requisito com situação (ok, falta, impede, conferir), campo, valor, mensagem e fonte."""
    r = r or regra()
    L = r["limiares"]
    req = r["requisitos"]
    ha = _n0(linha, "ha", "area")
    out = []

    def add(rid, situacao, campo, valor, msg, fonte):
        falta = req[rid]["gravidade_falta"]
        if situacao == "falta" and falta == "impede":
            situacao = "impede"
        elif situacao == "falta" and falta == "confirmar":
            situacao = "conferir"
        out.append(
            dict(
                regra=rid,
                situacao=situacao,
                campo=campo,
                valor=valor,
                mensagem=msg,
                fonte=fonte,
                gravidade=gravidade_da_situacao(situacao, falta),
                base="; ".join(r["base_legal"][b]["texto"].strip() for b in req[rid]["base"]),
            )
        )

    trad = max(_n0(linha, "ti_ha"), _n0(linha, "ti_funai_ha"), _n0(linha, "terra_tradicional_ha")) + _n0(
        linha, "quilombo_ha"
    )
    if trad >= L["sobreposicao_impede_ha"]:
        add(
            "sobreposicao_tradicional",
            "falta",
            "terra_tradicional_ha",
            _ha(trad),
            f"{_ha(trad)} ha sobre terra indígena ou quilombo.",
            "FUNAI, INCRA e TerraBrasilis",
        )
    else:
        add(
            "sobreposicao_tradicional",
            "ok",
            "terra_tradicional_ha",
            _ha(trad),
            "Fora de terra indígena e quilombo.",
            "FUNAI, INCRA e TerraBrasilis",
        )

    pub = max(_n0(linha, "terra_publica_ha"), _n0(linha, "terra_uc_publica_ha"), _n0(linha, "uc_protecao_integral_ha"))
    if pub >= L["sobreposicao_impede_ha"]:
        add(
            "sobreposicao_publica",
            "falta",
            "terra_publica_ha",
            _ha(pub),
            f"{_ha(pub)} ha sobre unidade de conservação de domínio público ou floresta pública.",
            "CNUC e Cadastro Nacional de Florestas Públicas (SFB)",
        )
    else:
        add(
            "sobreposicao_publica",
            "ok",
            "terra_publica_ha",
            _ha(pub),
            "Fora de unidade de conservação de domínio público e de floresta pública.",
            "CNUC e Cadastro Nacional de Florestas Públicas (SFB)",
        )

    sigef = (
        _n0(linha, "terra_sigef_titulacao_ha")
        + _n0(linha, "terra_sigef_posse_ha")
        + _n0(linha, "terra_sigef_assentamento_ha", "assentamento_ha")
    )
    if _num(linha, "terra_sigef_titulacao_ha") is None and _num(linha, "terra_sigef_posse_ha") is None:
        sigef = max(sigef, _n0(linha, "sigef_ha"))  # sem a sobreposição do produto: o SIGEF que o motor mediu
    if sigef > 0:
        add(
            "georreferenciamento",
            "ok",
            "sigef_ha",
            _ha(sigef),
            f"Parcela certificada no SIGEF em {_ha(sigef)} ha.",
            "SIGEF (INCRA)",
        )
    else:
        add(
            "georreferenciamento",
            "falta",
            "sigef_ha",
            "0",
            "Sem parcela certificada no SIGEF: falta o georreferenciamento.",
            "SIGEF (INCRA)",
        )

    oc = ocupacao(linha)
    minimo = max(L["ocupacao_min_ha"], L["ocupacao_min_fracao"] * ha)
    if oc["ate_2008"] is None:
        add(
            "ocupacao_antes_marco",
            "conferir",
            "aberto_ate_2008_ha",
            None,
            "Sem a série do PRODES para ver o uso antes de 2008: a prova vem de documentos e testemunhos.",
            "motor",
        )
    elif oc["ate_2008"] >= minimo:
        add(
            "ocupacao_antes_marco",
            "ok",
            "aberto_ate_2008_ha",
            _ha(oc["ate_2008"]),
            f"O satélite mostra {_ha(oc['ate_2008'])} ha abertos até 2008 (PRODES): sinal de uso antes do marco.",
            "PRODES (INPE)",
        )
    else:
        add(
            "ocupacao_antes_marco",
            "falta",
            "aberto_ate_2008_ha",
            _ha(oc["ate_2008"]),
            "O satélite não mostra área aberta antes de 2008: a prova da ocupação precisa vir de documentos e "
            "testemunhos.",
            "PRODES (INPE)",
        )

    if ha <= L["area_max_federal_ha"]:
        add("area_limite", "ok", "ha", _ha(ha), f"{_ha(ha)} ha: dentro do limite de 2.500 ha.", "CAR")
    else:
        add(
            "area_limite",
            "falta",
            "ha",
            _ha(ha),
            f"{_ha(ha)} ha: acima de 2.500 ha, só a parte até o limite pode ser regularizada.",
            "CAR",
        )

    emb = _n0(linha, "embargo_ha")
    if emb > L["embargo_ha"]:
        add(
            "sem_embargo",
            "falta",
            "embargo_ha",
            _ha(emb),
            f"Embargo do Ibama sobre {_ha(emb)} ha: resolver antes.",
            "Ibama",
        )
    else:
        add("sem_embargo", "ok", "embargo_ha", _ha(emb), "Sem embargo do Ibama.", "Ibama")

    d20 = _n0(linha, "desm_pos2020_ha")
    if d20 > L["desmatamento_recente_ha"]:
        add(
            "sem_desmatamento_recente",
            "falta",
            "desm_pos2020_ha",
            _ha(d20),
            f"{_ha(d20)} ha desmatados depois de 2020: acertar a pendência ambiental antes.",
            "PRODES (INPE)",
        )
    else:
        add(
            "sem_desmatamento_recente",
            "ok",
            "desm_pos2020_ha",
            _ha(d20),
            "Sem desmatamento depois de 2020.",
            "PRODES (INPE)",
        )

    st = str(linha.get("status_imovel") or "").strip().upper()
    if not st:
        add("car_ativo", "conferir", "status_imovel", None, "Sem a situação do CAR.", "SICAR")
    elif st in ATIVO:
        add("car_ativo", "ok", "status_imovel", st, "CAR ativo.", "SICAR")
    elif st in PENDENTE_CAR:
        add(
            "car_ativo",
            "conferir",
            "status_imovel",
            st,
            "CAR com pendência no SICAR: ver qual é a pendência (não impede pedir o título).",
            "SICAR",
        )
    else:
        add("car_ativo", "falta", "status_imovel", st, f"CAR na situação {st}: regularizar o cadastro.", "SICAR")

    add(
        "requisitos_pessoais",
        "conferir",
        None,
        None,
        "O dono declara que não tem outro imóvel rural e não foi beneficiado antes por reforma agrária ou "
        "regularização.",
        "declaração do dono",
    )
    return out


def _classe(reqs: list[dict], titulacao: bool) -> tuple[str, str | None]:
    """(classe, primeira pendência em texto)."""
    sit = {q["regra"]: q["situacao"] for q in reqs}
    impede = [q for q in reqs if q["situacao"] == "impede"]
    if impede:
        return "impedida", impede[0]["mensagem"].rstrip(".")
    if titulacao:
        return "em_titulacao", None
    pendentes = [
        q for q in reqs if q["situacao"] == "falta" or (q["situacao"] == "conferir" and q["regra"] in CONFERIR_SEGURA)
    ]
    if not pendentes:
        return "pronta_para_pedir", None
    if [q["regra"] for q in pendentes] == ["georreferenciamento"]:
        return "falta_georreferenciamento", None
    if sit.get("georreferenciamento") == "falta" and all(
        q["regra"] in ("georreferenciamento", "area_limite") for q in pendentes
    ):
        return "falta_georreferenciamento", None
    p = next((q for q in pendentes if q["regra"] != "georreferenciamento"), pendentes[0])
    return "pendente", p["mensagem"].rstrip(".")


def avaliar(linha: dict, r: dict | None = None) -> tuple[dict, list[Achado]]:
    """Colunas de regularizacao_<mun>.csv e os achados de um imóvel. A linha precisa de caminho_terra (ou das
    colunas do motor para calculá-lo)."""
    r = r or regra()
    cod = str(linha["cod_imovel"])
    cam = linha.get("caminho_terra")
    if not isinstance(cam, str) or not cam:
        from raiz import terra

        cam = terra.caminho(linha)["caminho_terra"]
    base = {"cod_imovel": cod, "regularizacao_regra_versao": r["versao_completa"]}
    if cam not in CAMINHOS_ALVO:
        c = r["classes"]["nao_se_aplica"]
        return {**base, "regularizacao_classe": "nao_se_aplica", "regularizacao_classe_rotulo": c["nome"]}, []
    uf = str(linha.get("uf") or "").upper()
    ha = _n0(linha, "ha", "area")
    reqs = requisitos(linha, r)
    titulacao = _n0(linha, "terra_sigef_titulacao_ha") > 0 or (
        cam == "assentamento" and _n0(linha, "terra_sigef_assentamento_titulado_ha") > 0
    )
    classe, pend = _classe(reqs, titulacao)
    c = r["classes"][classe]
    org = "INCRA (assentamento)" if cam == "assentamento" else orgao(uf, r)
    passo = " ".join(str(c["passo"]).split()).format(orgao=org, pendencia=pend or "")
    if cam == "assentamento":
        passo = f"Lote de assentamento: {passo[:1].lower()}{passo[1:]}"
    oc = ocupacao(linha)
    L = r["limiares"]
    minimo = max(L["ocupacao_min_ha"], L["ocupacao_min_fracao"] * ha)
    usu_esp = ha <= L["usucapiao_especial_max_ha"] and (oc["ate_2020"] or 0) >= minimo
    usu_10 = (oc["ate_2016"] or 0) >= minimo
    mf = _num(linha, "m_fiscal")
    pz = c.get("prazo_meses") or [None, None, None]
    pend_txt = "; ".join(q["mensagem"].rstrip(".") for q in reqs if q["situacao"] in ("falta", "impede", "conferir"))
    linha_out = {
        **base,
        "regularizacao_classe": classe,
        "regularizacao_classe_rotulo": c["nome"],
        "regularizacao_orgao": org,
        "regularizacao_proximo_passo": passo,
        "regularizacao_pendencias": pend_txt or None,
        "regularizacao_requisitos_ok": sum(q["situacao"] == "ok" for q in reqs),
        "regularizacao_requisitos_falta": sum(q["situacao"] in ("falta", "impede") for q in reqs),
        "regularizacao_requisitos_conferir": sum(q["situacao"] == "conferir" for q in reqs),
        "ocupacao_ate_2008_ha": None if oc["ate_2008"] is None else round(oc["ate_2008"], 2),
        "ocupacao_ate_2008_pct": None if oc["ate_2008"] is None or ha <= 0 else round(100 * oc["ate_2008"] / ha, 1),
        "regularizacao_gratuita": None if mf is None else bool(mf <= L["modulos_gratuita"]),
        "regularizacao_usucapiao_especial": bool(cam == "posse_em_titulacao" and usu_esp),
        "regularizacao_usucapiao_10anos": bool(cam == "posse_em_titulacao" and usu_10),
        "regularizacao_chance_12m": c.get("chance_12m"),
        "regularizacao_prazo_meses_p10": pz[0],
        "regularizacao_prazo_meses_p50": pz[1],
        "regularizacao_prazo_meses_p90": pz[2],
    }
    reg = chave_registro(cod)
    achados = [
        Achado(
            registro=reg,
            cod_imovel=cod,
            fase="regularizacao",
            regra=f"regularizacao.{q['regra']}",
            situacao=q["situacao"],
            gravidade=q["gravidade"],
            mensagem=q["mensagem"],
            campo=q["campo"],
            valor=q["valor"],
            fonte=q["fonte"],
            base=q["base"] or None,
            regra_versao=r["versao_completa"],
        )
        for q in reqs
    ]
    return linha_out, achados


# --- município ---------------------------------------------------------------------------------------------------


def _ler_csv(f: Path):
    import pandas as pd

    from raiz.privacidade import remover_colunas_pessoais

    df, _ = remover_colunas_pessoais(pd.read_csv(f, low_memory=False))
    if "cod_imovel" in df.columns:
        df["cod_imovel"] = df.cod_imovel.astype(str)
    return df


def entrada_municipio(pasta: str | Path, cod: int):
    """imoveis + filtros + terra (+ mb_agricultura do mapbiomas), uma linha por imóvel, pelo nome das colunas."""
    pasta = Path(pasta)
    im = _ler_csv(pasta / f"imoveis_{cod}.csv")
    for nome in ("filtros", "terra"):
        f = pasta / f"{nome}_{cod}.csv"
        if f.exists():
            t = _ler_csv(f)
            im = im.merge(
                t[[c for c in t.columns if c == "cod_imovel" or c not in im.columns]], on="cod_imovel", how="left"
            )
    return im


def calcular_municipio(pasta: str | Path, cod: int, r: dict | None = None):
    """(regularizacao_<mun>, achados_<mun>) como DataFrames."""
    import pandas as pd

    r = r or regra()
    im = entrada_municipio(pasta, cod)
    linhas, achados = [], []
    for linha in im.to_dict("records"):
        linha = {k: (None if isinstance(v, float) and math.isnan(v) else v) for k, v in linha.items()}
        lo, ac = avaliar(linha, r)
        linhas.append(lo)
        achados += [a.linha() for a in ac]
    return pd.DataFrame(linhas), pd.DataFrame(achados, columns=COLUNAS_ACHADO)


def achados_da_certidao(pasta: str | Path, cod: int):
    """Achados das certidões lidas (matricula_conferencia_<mun>.csv), na pasta ou na saída de raiz/documentos."""
    import pandas as pd

    from raiz.titulo.achados import da_certidao

    f = arquivo_documentos(Path(pasta), cod, "matricula_conferencia")
    if f is None:
        return pd.DataFrame(columns=COLUNAS_ACHADO)
    df = pd.read_csv(f, dtype={"registro_cns": str, "registro_matricula": str})
    out = [a.linha() for linha in df.to_dict("records") for a in da_certidao(linha)]
    return pd.DataFrame(out, columns=COLUNAS_ACHADO)


def arquivo_documentos(pasta: Path, cod: int, tabela: str) -> Path | None:
    """<tabela>_<cod>.csv na pasta do município ou, se não estiver lá, na saída de raiz/documentos (mesma UF)."""
    f = pasta / f"{tabela}_{cod}.csv"
    if f.exists():
        return f
    try:
        from raiz.documentos.config import pasta_dados
    except ImportError:  # pragma: no cover
        return None
    g = pasta_dados() / "saida" / pasta.name.upper() / f"{tabela}_{cod}.csv"
    return g if g.exists() else None


def versao_do_arquivo(f: Path) -> str | None:
    import pandas as pd

    if not f.exists():
        return None
    v = pd.read_csv(f, usecols=lambda c: c == "regularizacao_regra_versao", nrows=1)
    return str(v.iloc[0, 0]) if len(v) and len(v.columns) else None


def escrever_municipio(pasta: str | Path, cod: int) -> dict:
    import pandas as pd

    pasta = Path(pasta)
    reg, ach = calcular_municipio(pasta, cod)
    ach = pd.concat([ach, achados_da_certidao(pasta, cod)], ignore_index=True)
    reg.to_csv(pasta / f"regularizacao_{cod}.csv", index=False)
    ach.to_csv(pasta / f"achados_{cod}.csv", index=False)
    return {
        "imoveis": len(reg),
        "achados": len(ach),
        **{f"classe_{k}": int(v) for k, v in reg.regularizacao_classe.value_counts().items()},
    }


def recalcular(saida: str | Path, ufs: list[str] | None = None) -> dict:
    """Refaz regularizacao_<mun>.csv que falta ou foi calculado com outra versão da regra."""
    saida = Path(saida)
    v = versao()
    feitos, em_dia, erros = [], 0, []
    for pasta_uf in sorted(p for p in saida.iterdir() if p.is_dir() and (not ufs or p.name.upper() in ufs)):
        for f in sorted(pasta_uf.glob("imoveis_*.csv")):
            cod = int(f.stem.split("_")[1])
            if versao_do_arquivo(pasta_uf / f"regularizacao_{cod}.csv") == v:
                em_dia += 1
                continue
            try:
                escrever_municipio(pasta_uf, cod)
                feitos.append(cod)
            except Exception as ex:  # noqa: BLE001 - um município quebrado não para os outros
                erros.append(f"{cod}: {ex}")
    return {"refeitos": feitos, "em_dia": em_dia, "erros": erros}


def resumo(pasta: str | Path, cod: int) -> list[dict]:
    """Por classe: imóveis, hectares, área de carbono e tCO2/ano (o estoque que cada classe pode destravar)."""
    pasta = Path(pasta)
    im = entrada_municipio(pasta, cod)
    f = pasta / f"regularizacao_{cod}.csv"
    reg = _ler_csv(f) if f.exists() else calcular_municipio(pasta, cod)[0]
    df = im.merge(reg[["cod_imovel", "regularizacao_classe"]], on="cod_imovel", how="left")
    out = []
    for cl in CLASSES:
        g = df[df.regularizacao_classe == cl]
        if g.empty:
            continue
        out.append(
            dict(
                classe=cl,
                imoveis=len(g),
                ha=round(float(g.get("ha", 0).fillna(0).sum()), 1),
                carbono_ha=round(float(g["carbono_ha"].fillna(0).sum()), 1) if "carbono_ha" in g else None,
                carbono_tco2_ano=round(float(g["carbono_tco2_ano"].fillna(0).sum()), 1)
                if "carbono_tco2_ano" in g
                else None,
            )
        )
    return out


def mutiroes(pasta: str | Path, cod: int) -> list[dict]:
    """Imóveis que só precisam do georreferenciamento, juntos por grupo de vizinhas (grupo_id do
    desenvolvedor_<mun>.csv: pontos a até ~15 km). Um mesmo profissional certifica o grupo numa ida a campo; pequenas
    entram junto com as vizinhas. Sem grupo, o imóvel sai sozinho."""
    pasta = Path(pasta)
    im = entrada_municipio(pasta, cod)
    f = pasta / f"regularizacao_{cod}.csv"
    reg = _ler_csv(f) if f.exists() else calcular_municipio(pasta, cod)[0]
    df = im.merge(reg[["cod_imovel", "regularizacao_classe"]], on="cod_imovel", how="left")
    d = pasta / f"desenvolvedor_{cod}.csv"
    if d.exists():
        dv = _ler_csv(d)
        if "grupo_id" in dv.columns:
            df = df.merge(dv[["cod_imovel", "grupo_id"]], on="cod_imovel", how="left")
    if "grupo_id" not in df.columns:
        df["grupo_id"] = None
    alvo = df[df.regularizacao_classe == "falta_georreferenciamento"].copy()
    alvo["grupo"] = alvo.grupo_id.where(alvo.grupo_id.notna(), "sozinho:" + alvo.cod_imovel)
    out = []
    for g, x in alvo.groupby("grupo"):
        out.append(
            dict(
                grupo=str(g),
                imoveis=len(x),
                cod_imoveis=sorted(x.cod_imovel),
                ha=round(float(x.get("ha", 0).fillna(0).sum()), 1),
                pequenas=int((x.get("m_fiscal", 99).fillna(99) <= 4).sum()) if "m_fiscal" in x else None,
                carbono_tco2_ano=round(float(x["carbono_tco2_ano"].fillna(0).sum()), 1)
                if "carbono_tco2_ano" in x
                else None,
            )
        )
    return sorted(out, key=lambda m: (-(m["carbono_tco2_ano"] or 0), m["grupo"]))


# --- aprendizado ---------------------------------------------------------------------------------------------------


def congelar_regularizacao(con, rodada_id: int) -> tuple[str | None, bool, int]:
    """Congela a chance a priori de título em 12 meses de cada imóvel em posse ou assentamento da rodada
    (complemento 'regularizacao')."""
    from sqlalchemy import text

    from raiz.aprendizado.registro import Previsao, Versoes, registrar_lote

    r = con.execute(text("select * from funil.rodada where id = :i"), {"i": rodada_id}).first()
    if r is None:
        raise ValueError(f"rodada {rodada_id} não existe")
    ps, versoes = [], set()
    for cod, a in con.execute(
        text("""select cod_imovel, atributos from funil.complemento_imovel
                where rodada_id = :r and tipo = 'regularizacao'"""),
        {"r": rodada_id},
    ):
        ch = (a or {}).get("regularizacao_chance_12m")
        if ch is None or (isinstance(ch, float) and math.isnan(ch)):
            continue
        versoes.add((a or {}).get("regularizacao_regra_versao") or "desconhecida")
        ps.append(
            Previsao(cod, ALVO, HORIZONTE_DIAS, valor_num=float(ch), valor_texto=(a or {}).get("regularizacao_classe"))
        )
    if not ps:
        return None, False, 0
    v = Versoes(
        modelo="regularizacao",
        modelo_versao=",".join(sorted(versoes)),
        entradas_versao=r.hash_entradas,
        data_corte=r.data_corte,
        regras_versao=r.regras_versao,
        tipo="ao_vivo",
        rodada_id=rodada_id,
    )
    lh, novo = registrar_lote(con, ps, v, f"regularização da posse, município {r.cod_municipio}, rodada {rodada_id}")
    return lh, novo, len(ps)


def gabaritar(con, hoje: dt.date | None = None) -> dict:
    """Gabarito automático das previsões de título: 1 quando a rodada mais nova do município põe o imóvel em
    matrícula (privada_matricula); 0 quando o horizonte vence sem título. Não repete gabarito já registrado."""
    from sqlalchemy import text

    from raiz.aprendizado.registro import registrar_gabarito

    hoje = hoje or dt.date.today()
    pend = con.execute(
        text("""select distinct on (p.cod_imovel) p.cod_imovel, p.data_corte, p.horizonte_em
                from aprendizado.previsao p
                where p.modelo = 'regularizacao' and p.alvo = :a
                  and not exists (select 1 from aprendizado.gabarito g where g.cod_imovel = p.cod_imovel
                                  and g.alvo = p.alvo and g.observado_em > p.data_corte)
                order by p.cod_imovel, p.data_corte desc"""),
        {"a": ALVO},
    ).all()
    n1 = n0 = 0
    for cod, corte, horizonte in pend:
        atual = con.execute(
            text("""select c.atributos->>'caminho_terra' as cam, c.rodada_id
                    from funil.complemento_imovel c join funil.rodada r on r.id = c.rodada_id
                    where c.tipo = 'terra' and c.cod_imovel = :c and r.data_corte > :d
                    order by r.data_corte desc, r.id desc limit 1"""),
            {"c": cod, "d": corte},
        ).first()
        if atual is not None and atual.cam == "privada_matricula":
            registrar_gabarito(
                con,
                cod,
                ALVO,
                max(hoje, corte + dt.timedelta(days=1)),
                "caminho_terra",
                valor_num=1.0,
                referencia=f"rodada:{atual.rodada_id}",
            )
            n1 += 1
        elif horizonte <= hoje:
            registrar_gabarito(
                con,
                cod,
                ALVO,
                horizonte,
                "caminho_terra",
                valor_num=0.0,
                referencia=f"rodada:{atual.rodada_id}" if atual else None,
            )
            n0 += 1
    return {"titulados": n1, "sem_titulo_no_prazo": n0, "em_aberto": len(pend) - n1 - n0}
