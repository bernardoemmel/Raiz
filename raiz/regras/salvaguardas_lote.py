"""Salvaguardas do lote: dupla contagem, direitos coletivos e revisão humana.

Uma pendência conserva o imóvel no planejamento, mas nunca libera venda. A camada
geográfica recebida deve identificar programa, fonte e vigência; ausência de camada
não prova ausência de sobreposição. Documentos pessoais ficam fora desta trilha:
guardar somente referência/hash da evidência e o código do imóvel.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import sqlite3
import uuid
from collections.abc import Iterable, Mapping
from functools import lru_cache
from pathlib import Path

import pandas as pd
import yaml

from raiz.privacidade import mascarar

ARQ = Path(__file__).parent / "padroes" / "salvaguardas_lote.yaml"
MOTIVOS_REVISAO = ("contestar_criterio", "corrigir_dado", "apresentar_documento", "contestar_nota")


@lru_cache(maxsize=4)
def _ler_regra(arquivo: Path, marca: tuple) -> dict:
    texto = arquivo.read_bytes()
    r = yaml.safe_load(texto)
    conteudo = texto + b"\n--codigo--\n" + Path(__file__).read_bytes()
    r["versao_completa"] = f"{r['versao']}+{hashlib.sha256(conteudo).hexdigest()[:8]}"
    return r


def regra() -> dict:
    codigo = Path(__file__)
    return _ler_regra(ARQ, (ARQ.stat().st_mtime_ns, ARQ.stat().st_size, codigo.stat().st_mtime_ns))


def _s(x) -> str:
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return ""
    s = str(x).strip()
    return "" if s.lower() in ("nan", "none", "null", "<na>") else s


def _num(x) -> float | None:
    try:
        n = float(x)
    except (ValueError, TypeError):
        return None
    return n if math.isfinite(n) else None


def _bool(x) -> bool:
    return _s(x).lower() in ("true", "1", "sim", "t") or (not isinstance(x, str) and _num(x) == 1)


def _data(x) -> dt.date | None:
    try:
        return dt.date.fromisoformat(_s(x)[:10])
    except ValueError:
        return None


def decisao(cod_imovel: str, tipo: str, criterio: str, texto: str, modelo_versao: str, **dados) -> dict:
    """Decisão estável e revisável. `dados` contém somente parâmetros, nunca identidade do titular."""
    if not all(_s(v) for v in (cod_imovel, tipo, criterio, texto, modelo_versao)):
        raise ValueError("decisão exige imóvel, tipo, critério em texto e versão do modelo")
    from raiz.privacidade import colunas_pessoais

    if colunas_pessoais(dados):
        raise ValueError("a trilha não aceita dados pessoais")
    r = regra()
    out = {
        "cod_imovel": str(cod_imovel),
        "tipo": tipo,
        "criterio": criterio,
        "texto": texto,
        "modelo_versao": modelo_versao,
        "versao_regras": r["versao_completa"],
        "fundamento_revisao": r["revisao"]["fundamento"],
        "revisao_humana_disponivel": True,
        "parametros": dados,
    }
    limpo = mascarar(json.dumps(out, ensure_ascii=False, sort_keys=True, allow_nan=False))
    out = json.loads(limpo)
    out["id"] = hashlib.sha256(limpo.encode()).hexdigest()
    return out


def cruzar_jurisdicional(imoveis, programas, data_referencia: dt.date) -> pd.DataFrame:
    """Sobreposição real em hectares (SIRGAS 2000 / Brazil Polyconic), sem duplicar polígonos.

    GeoDataFrames com CRS: imóveis precisam de cod_imovel; programas de programa_id,
    fonte, inicio_em e fim_em. Esta função cruza a camada fornecida; não presume que
    o catálogo de programas seja completo fora de sua cobertura territorial.
    """
    from shapely import make_valid
    from shapely.ops import unary_union

    if imoveis.crs is None or programas.crs is None:
        raise ValueError("as duas camadas precisam de CRS")
    exigidas = {"programa_id", "fonte", "inicio_em", "fim_em"}
    if "cod_imovel" not in imoveis or not exigidas <= set(programas.columns):
        raise ValueError("camada sem identificador, fonte ou vigência")
    if not isinstance(data_referencia, dt.date):
        raise ValueError("informe a data de referência da camada")
    vigentes = programas[
        programas.apply(
            lambda x: (
                (_data(x.inicio_em) or dt.date.max) <= data_referencia
                and (_data(x.fim_em) or dt.date.max) >= data_referencia
            ),
            axis=1,
        ).astype(bool)
    ].to_crs(5880)
    out = []
    for _, im in imoveis.to_crs(5880).iterrows():
        inter, ids, fontes = [], [], []
        for _, p in vigentes.iterrows():
            if im.geometry is None or p.geometry is None:
                continue
            g = make_valid(im.geometry).intersection(make_valid(p.geometry))
            if not g.is_empty and g.area > 0:
                if not _s(p.fonte):
                    raise ValueError("programa sobreposto sem fonte")
                inter.append(g)
                ids.append(str(p.programa_id))
                fontes.append(str(p.fonte))
        ha = unary_union(inter).area / 10_000 if inter else 0.0
        out.append(
            {
                "cod_imovel": str(im.cod_imovel),
                "jurisdicional_programa": "; ".join(sorted(set(ids))),
                "jurisdicional_sobreposicao_ha": ha,
                "jurisdicional_situacao": "sobreposicao" if ha > 0 else "desconhecido",
                "jurisdicional_fonte": "; ".join(sorted(set(fontes))),
                "jurisdicional_camada_em": data_referencia.isoformat(),
            }
        )
    return pd.DataFrame(out)


def _criterio_reserva(linha: Mapping, modelo_versao: str) -> tuple[str, dict, bool]:
    """Justifica os componentes da nota publicada, sem reconstruir premissas históricas com a regra atual."""
    from raiz import restauracao as R

    origem = _s(linha.get("restauracao_versao")) or modelo_versao
    dados = {
        c: _num(linha.get(c))
        for c in (
            "reserva_risco_pct",
            "fogo_risco_ano_pct",
            "derrubada_risco_ano_pct",
            "perda_natural_40a_pct",
            "fogo_anos_media",
            "taxa_supressao_secundaria_municipio",
        )
    }
    dados.update(versao_origem=origem, fonte=_s(linha.get("reserva_risco_fonte")))
    if origem != R.versao():
        return (
            "Reserva recebida de outra versão do cálculo: conservar os valores publicados e solicitar a "
            "justificativa daquela versão; a fórmula atual não reconstrói a nota histórica.",
            dados,
            True,
        )
    try:
        c = R.cenario(_s(linha.get("restauracao_cenario")) or None)
    except ValueError:
        return "Cenário da reserva não reconhecido; conferir a premissa de origem.", dados, True
    texto = R._texto_reserva(dict(linha), c)
    npm = R.regra()["nao_permanencia"]
    piso = 100 * R._reserva_base(c)
    criterio = (
        f"{texto} Cálculo R.nao_permanencia: frequência anual de fogo = anos com fogo / "
        f"{npm['anos_serie_fogo']}; taxa mitigada = frequência de fogo × {npm['severidade_fogo']} × "
        f"(1 − {npm['mitigacao_fogo']}) + supressão anual de secundária × {npm['severidade_derrubada']} × "
        f"(1 − {npm['mitigacao_derrubada']}); perda = 1 − exp(−{npm['horizonte_anos']} × taxa mitigada). "
        f"Reserva = máximo({piso:g}%, mínimo({100 * npm['teto']:g}%, máximo({100 * npm['piso_vcs']:g}%, "
        f"{100 * npm['risco_interno_externo']:g}% + 100 × perda))). "
        "Severidade e mitigação são premissas Raíz, dependentes de aceiro, brigada, contrato e monitoramento."
    )
    faltou = (
        dados["fonte"] != "fazenda"
        or dados["fogo_anos_media"] is None
        or dados["taxa_supressao_secundaria_municipio"] is None
    )
    if faltou:
        criterio += (
            " Histórico ausente ou incompleto: o componente ausente não comprova risco zero. "
            "O motor mantém o piso e trata o componente ausente como zero; conferir a reserva com histórico completo."
        )
    dados["cenario"] = c["cenario"]
    return criterio, dados, faltou


def avaliar(linha: Mapping, modelo_versao: str) -> dict:
    """Avalia uma fazenda. Qualquer interseção tradicional exige salvaguardas, sem piso de tamanho.

    Para exclusão jurisdicional: situação, referência documental, data de comunicação
    e início do período de geração. Pedido pendente não é exclusão documentada.
    'comercializavel' cobre estas salvaguardas; não substitui certificação/título.
    """
    r = regra()
    cod = _s(linha.get("cod_imovel"))
    if not cod or not _s(modelo_versao):
        raise ValueError("informe imóvel e versão do modelo")
    uf = _s(linha.get("uf")).upper() or cod[:2].upper()
    programa = r["jurisdicional"]["programas"].get(uf, {})
    fonte = _s(linha.get("jurisdicional_fonte")) or programa.get("fonte", "")
    evidencia = _s(linha.get("jurisdicional_evidencia"))
    sit = _s(linha.get("jurisdicional_situacao")) or "desconhecido"
    ha = _num(linha.get("jurisdicional_sobreposicao_ha"))
    if ha is not None and ha > 0 and sit != "exclusao_documentada":
        sit = "sobreposicao"
    if sit not in ("sem_sobreposicao", "exclusao_documentada", "sobreposicao", "desconhecido"):
        sit = "desconhecido"
    exclusao, geracao = _data(linha.get("jurisdicional_exclusao_em")), _data(linha.get("creditos_inicio_em"))
    excluida = bool(
        sit == "exclusao_documentada" and evidencia and fonte and exclusao and geracao and geracao >= exclusao
    )
    sem_sobreposicao = bool(sit == "sem_sobreposicao" and evidencia and fonte and not (ha and ha > 0))
    pendencias, decisoes = [], []

    def pendencia(codigo: str, texto: str, criterio: str, bloqueia=False):
        pendencias.append({"codigo": codigo, "texto": texto, "bloqueia_planejamento": bloqueia})
        decisoes.append(decisao(cod, "impedimento" if bloqueia else "pendencia", criterio, texto, modelo_versao))

    if not (excluida or sem_sobreposicao):
        if sit == "sobreposicao" or (ha is not None and ha > 0):
            pendencia(
                "dupla_contagem_jurisdicional",
                "Sobreposição jurisdicional confirmada: créditos retidos até "
                "documentar exclusão e período sem dupla contagem.",
                r["jurisdicional"]["fundamento"],
                True,
            )
        else:
            pendencia(
                "jurisdicional_a_conferir",
                "Falta comprovar ausência de sobreposição ou comunicação de exclusão "
                "do programa jurisdicional para o período dos créditos.",
                r["jurisdicional"]["fundamento"],
            )
    tradicional = (
        _bool(linha.get("territorio_tradicional"))
        or _bool(linha.get("terra_indigena"))
        or _s(linha.get("caminho_terra")) == "terra_indigena_ou_tradicional"
        or any(
            (_num(linha.get(c)) or 0) > 0
            for c in ("ti_ha", "ti_funai_ha", "quilombo_ha", "terra_tradicional_ha", "territorio_tradicional_ha")
        )
    )
    tipo = _s(linha.get("tipo_credito")).lower() or "remocao"
    minimo = r["tradicional"]["minimo_redd_mercado" if tipo in ("redd", "redd+", "redd_mercado") else "minimo_remocao"]
    consulta = _s(linha.get("clpi_situacao"))
    consentida = consulta == "consentida" and bool(_s(linha.get("clpi_evidencia")))
    if tradicional:
        if not consentida:
            recusada = consulta == "recusada"
            pendencia(
                "clpi",
                "Consentimento em consulta livre, prévia e informada "
                + ("recusado pela comunidade." if recusada else "pendente, custeada pelo desenvolvedor."),
                r["tradicional"]["fundamento"],
                recusada,
            )
        fracao = _num(linha.get("fracao_creditos_comunidade"))
        if not (fracao is not None and minimo <= fracao <= 1 and _s(linha.get("reparticao_evidencia"))):
            pendencia(
                "reparticao_comunidade",
                f"Comprovar cláusula que assegure no mínimo {minimo:.0%} dos créditos "
                "à comunidade, gestão participativa e conta específica.",
                r["tradicional"]["fundamento"],
            )
    for campo, motivo, versao in (
        ("risco_terra", "risco_terra_motivo", "terra_regra_versao"),
        ("titulo_nota", "titulo_decisao_texto", "titulo_nota_versao"),
    ):
        if _s(linha.get(campo)):
            criterio = _s(linha.get(motivo))
            if not criterio:
                criterio = f"{campo} recebido sem justificativa de origem; requer conferência humana."
                pendencia(f"criterio_{campo}", criterio, r["revisao"]["fundamento"])
            decisoes.append(
                decisao(
                    cod,
                    "nota_risco",
                    criterio,
                    f"{campo}: {_s(linha.get(campo))}.",
                    modelo_versao,
                    campo=campo,
                    versao_origem=_s(linha.get(versao)) or "nao_informada",
                )
            )
    if _s(linha.get("reserva_risco_pct")):
        criterio, dados_reserva, falta_reserva = _criterio_reserva(linha, modelo_versao)
        if falta_reserva:
            pendencia(
                "criterio_reserva_risco",
                "Completar o histórico e a justificativa da reserva contra reversão.",
                r["revisao"]["fundamento"],
            )
        decisoes.append(
            decisao(
                cod,
                "nota_risco",
                criterio,
                f"Reserva contra reversão: {_s(linha.get('reserva_risco_pct'))}%.",
                dados_reserva["versao_origem"],
                campo="reserva_risco_pct",
                **dados_reserva,
            )
        )
    return {
        "cod_imovel": cod,
        "modelo_versao": modelo_versao,
        "versao_regras": r["versao_completa"],
        "elegivel_planejamento": not any(x["bloqueia_planejamento"] for x in pendencias),
        "comercializavel": not pendencias,
        "jurisdicional": {
            "programa": _s(linha.get("jurisdicional_programa")) or programa.get("id"),
            "situacao": sit if (excluida or sem_sobreposicao or sit == "sobreposicao") else "desconhecido",
            "sobreposicao_ha": ha,
            "fonte": fonte,
            "evidencia": mascarar(evidencia),
        },
        "territorio_tradicional": tradicional,
        "consulta_livre_previa_informada": {
            "exigida": tradicional,
            "situacao": ("consentida" if consentida else "recusada" if consulta == "recusada" else "pendente")
            if tradicional
            else "nao_aplicavel",
            "custeio": "desenvolvedor",
        },
        "fracao_creditos_comunidade_minima": minimo if tradicional else None,
        "pendencias": pendencias,
        "decisoes": decisoes,
    }


def preparar_oferta(oferta: pd.DataFrame, linhas: Mapping[str, Mapping], modelo_versao: str):
    """Acrescenta salvaguardas e conserva todas as linhas; seleção decide pelo campo de planejamento."""
    out, decisoes = oferta.copy(), []
    avaliacoes = [
        avaliar({**li, **linhas.get(str(li["cod_imovel"]), {})}, modelo_versao) for li in oferta.to_dict("records")
    ]
    campos = {
        "salvaguardas_planejamento": "elegivel_planejamento",
        "salvaguardas_comercializavel": "comercializavel",
        "salvaguardas_pendencias": "pendencias",
        "salvaguardas_jurisdicional": "jurisdicional",
        "consulta_livre_previa_informada": "consulta_livre_previa_informada",
        "fracao_creditos_comunidade_minima": "fracao_creditos_comunidade_minima",
    }
    for col, chave in campos.items():
        out[col] = [a[chave] for a in avaliacoes]
    for a in avaliacoes:
        decisoes.extend(a["decisoes"])
    return out, decisoes


def gravar_decisoes(arquivo: str | Path, decisoes: Iterable[dict]) -> int:
    """JSONL imutável por id; rodadas novas conservam decisões anteriores. Sem dados do titular."""
    import fcntl
    import os

    arquivo = Path(arquivo)
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with arquivo.open("a+", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.seek(0)
        existentes = {json.loads(s)["id"] for s in f if s.strip()}
        for d in decisoes:
            if d["id"] not in existentes:
                f.write(json.dumps(d, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n")
                existentes.add(d["id"])
                n += 1
        f.flush()
        os.fsync(f.fileno())
    return n


def pedir_revisao_humana(
    banco: str | Path,
    arquivo_decisoes: str | Path,
    decisao_id: str,
    cod_imovel: str,
    motivo: str = "contestar_criterio",
) -> dict:
    """Protocola pedido persistente e idempotente. Não altera decisão nem libera o crédito.

    O atendimento autentica o requerente em canal próprio; esta função recebe somente
    CAR e motivo codificado. Nenhum nome, documento, contato ou alegação pessoal é gravado.
    """
    if motivo not in MOTIVOS_REVISAO:
        raise ValueError(f"motivo deve ser um de {MOTIVOS_REVISAO}")
    import fcntl

    encontrada = None
    with Path(arquivo_decisoes).open(encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_SH)
        for s in f:
            d = json.loads(s)
            if d["id"] == decisao_id:
                encontrada = d
                break
    if encontrada is None or encontrada["cod_imovel"] != cod_imovel:
        raise ValueError("decisão não encontrada para o imóvel")
    banco = Path(banco)
    banco.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(banco) as con:
        con.row_factory = sqlite3.Row
        con.execute("""CREATE TABLE IF NOT EXISTS revisao_humana (
            protocolo TEXT PRIMARY KEY, decisao_id TEXT NOT NULL UNIQUE, cod_imovel TEXT NOT NULL,
            motivo TEXT NOT NULL, situacao TEXT NOT NULL, solicitado_em TEXT NOT NULL, decisao_json TEXT NOT NULL)""")
        con.execute(
            "INSERT OR IGNORE INTO revisao_humana VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                str(uuid.uuid4()),
                decisao_id,
                cod_imovel,
                motivo,
                "aguardando_pessoa",
                dt.datetime.now(dt.UTC).isoformat(),
                json.dumps(encontrada, ensure_ascii=False),
            ),
        )
        row = con.execute(
            "SELECT protocolo, decisao_id, cod_imovel, motivo, situacao, solicitado_em "
            "FROM revisao_humana WHERE decisao_id = ?",
            (decisao_id,),
        ).fetchone()
        return dict(row)
