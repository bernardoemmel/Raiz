"""Cache de extração, calibrado por conferências integrais independentes de matrícula.

O escore é uma regra fixa de ordenação, não uma probabilidade de acerto. O MAPIE
controla a precisão das leituras reutilizadas (LTT, Bonferroni). A garantia depende
de matrículas conferidas representativas da produção; revisão só dos casos difíceis
não serve. Motor, regras e data são reconferidos mesmo quando a extração é reutilizada.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import os
import tempfile
import warnings
from collections import defaultdict
from pathlib import Path

import numpy as np

from raiz.documentos.armazem import Armazem, Leitura, _canonico
from raiz.documentos.certidao import esquema, proveniencia
from raiz.documentos.claude import falta_campo
from raiz.documentos.config import pasta_dados

VERSAO_ESCORE = "matricula-escore-v1"
CORTES = np.array([0.5, 0.7, 0.8, 0.9, 0.95])
FONTES = {"cartorio", "onr", "conferencia_humana"}


def caminho_padrao() -> Path:
    return pasta_dados() / "cache-calibracao.json"


def escore(dados: dict) -> float:
    """Combina confiança declarada e completude, sem aprender na amostra de calibração."""
    documento = dados.get("documento") or {}
    if (
        falta_campo(dados, esquema.ESQUEMA)
        or not documento.get("legivel")
        or documento.get("paginas_ilegiveis")
        or documento.get("tipo_documento") == "nao_e_certidao"
    ):
        return 0.0
    completos = [
        (dados.get("cartorio") or {}).get("cns"),
        (dados.get("matricula") or {}).get("numero"),
        (dados.get("imovel") or {}).get("area_valor"),
        (dados.get("imovel") or {}).get("area_unidade"),
        documento.get("data_emissao"),
    ]
    base = {"alta": 0.95, "media": 0.65, "baixa": 0.35}.get(dados.get("confianca"), 0.0)
    return round(base * sum(x is not None and x != "" for x in completos) / len(completos), 6)


def assinatura(lt: Leitura) -> str:
    return _canonico(
        dict(
            modelo=lt.modelo,
            modelo_pedido=lt.modelo_pedido,
            esforco=lt.esforco,
            prompt=lt.prompt_versao,
            esquema=lt.esquema_versao,
            leitor=lt.leitor_versao,
            escore=VERSAO_ESCORE,
            receita_hash=(lt.derivados or {}).get("receita_hash"),
        )
    )


def _gabaritos(armazem: Armazem) -> dict[int, dict]:
    todos = armazem.gabaritos()
    desmentidas = {g["leitura_id"] for g in todos if g["confirma"] == 0}
    return {
        g["leitura_id"]: {**g, "confirma": 0 if g["leitura_id"] in desmentidas else g["confirma"]}
        for g in todos
        if g["alvo"] == "leitura_integral"
    }


def _hash_gabaritos(gabaritos: dict) -> str:
    # Inclui correções: o corte deixa de valer até que se calibre de novo.
    return hashlib.sha256(_canonico(list(gabaritos.values())).encode()).hexdigest()


def _probabilidades(escores):
    x = np.asarray(escores, dtype=float)
    return np.column_stack([1 - x, x])


def calibrar(
    armazem: Armazem | None = None,
    *,
    caminho: str | Path | None = None,
    risco: float = 0.05,
    confianca: float = 0.95,
    hoje: dt.date | None = None,
) -> dict:
    """Calibra por receita, sem misturar modelos; uma matrícula por amostra.

    Só a conferência integral, com fonte reconhecida e amostra aleatória declarada,
    entra. Simulações, leitura humana e revisões parciais não medem o leitor.
    Sem um corte estatisticamente aprovado, o grupo continua sem cache.
    """
    from mapie.risk_control import BinaryClassificationController

    if not 0 < risco < 1 or not 0 < confianca < 1:
        raise ValueError("risco e confiança devem estar entre zero e um")
    armazem = armazem or Armazem()
    gabs = _gabaritos(armazem)
    receita = proveniencia.receita_hash()
    grupos = defaultdict(dict)
    for lt in armazem.leituras(tipo="certidao"):
        g = gabs.get(lt.id)
        der = lt.derivados or {}
        if (
            not g
            or g["confirma"] is None
            or g["fonte"] not in FONTES
            or g["nota"] != "amostra_aleatoria_cache"
            or lt.erro
            or lt.modelo in {None, "humano", "simulado"}
            or der.get("origem_leitura") != "api"
            or der.get("escore_versao") != VERSAO_ESCORE
            or der.get("receita_hash") != receita
            or not armazem.conferir_hash(lt.id)
        ):
            continue
        # Primeira leitura conferida de cada matrícula: tentativas repetidas não
        # aumentam n nem permitem escolher a resposta mais favorável.
        grupos[assinatura(lt)].setdefault(lt.chave, (lt, g))
    hoje = hoje or dt.datetime.now(dt.UTC).date()
    resultado = dict(
        versao=VERSAO_ESCORE,
        receita_hash=receita,
        calibrador_hash=proveniencia.calibrador_hash(risco=risco, confianca=confianca, cortes=CORTES.tolist()),
        metodo="MAPIE LTT precisão, Bonferroni",
        criado_em=hoje.isoformat(),
        valido_ate=(hoje + dt.timedelta(days=90)).isoformat(),
        risco_maximo=risco,
        confianca=confianca,
        gabaritos_hash=_hash_gabaritos(gabs),
        grupos={},
    )
    for chave, amostra in sorted(grupos.items()):
        escores = np.array([lt.derivados["escore_confianca"] for lt, _ in amostra.values()])
        corretas = np.array([g["confirma"] for _, g in amostra.values()])
        controlador = BinaryClassificationController(
            predict_function=_probabilidades,
            risk="precision",
            target_level=1.0 - risco,
            confidence_level=confianca,
            best_predict_param_choice="predicted_positive_fraction",
            list_predict_params=CORTES,
            fwer_method="bonferroni",
        )
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            controlador.calibrate(escores, corretas)
        corte = controlador.best_predict_param
        selecionadas = escores >= corte if corte is not None else np.zeros(len(escores), dtype=bool)
        n = int(selecionadas.sum())
        resultado["grupos"][chave] = dict(
            corte=float(corte) if corte is not None and n else None,
            matriculas=len(amostra),
            reutilizaveis=n,
            erros=int((corretas[selecionadas] == 0).sum()),
            motivo="calibrado" if corte is not None and n else "sem corte: continuar relendo",
        )
    caminho = Path(caminho) if caminho is not None else caminho_padrao()
    caminho.parent.mkdir(parents=True, exist_ok=True)
    # Substituição atômica: uma leitura simultânea nunca usa um arquivo parcial.
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=caminho.parent, delete=False) as f:
        temporario = Path(f.name)
        f.write(json.dumps(resultado, ensure_ascii=False, indent=2) + "\n")
    try:
        os.replace(temporario, caminho)
    finally:
        temporario.unlink(missing_ok=True)
    return resultado


def consultar(
    armazem: Armazem,
    *,
    arquivo_sha256: str,
    modelo: str,
    esforco: str,
    prompt_versao: str,
    esquema_versao: str,
    leitor_versao: str,
    caminho: str | Path | None = None,
    hoje: dt.date | None = None,
) -> tuple[Leitura | None, dict]:
    """Só reutiliza o mesmo PDF e a mesma receita; registra cada decisão sem o PDF."""
    with armazem.con() as c:
        linha = c.execute(
            """select id from leitura where tipo = 'certidao' and arquivo_sha256 = ?
               and modelo_pedido = ? and modelo = ? and esforco = ? and prompt_versao = ?
               and esquema_versao = ? and leitor_versao = ? order by id desc limit 1""",
            (arquivo_sha256, modelo, modelo, esforco, prompt_versao, esquema_versao, leitor_versao),
        ).fetchone()
    lt = armazem.leitura(linha["id"]) if linha else None
    decisao = dict(reutilizada=False, motivo="sem leitura compatível", leitura_id=lt.id if lt else None)
    if lt:
        decisao.update(_decidir(armazem, lt, caminho, hoje))
    armazem.gravar_cache_decisao(arquivo_sha256, decisao)
    return (lt if decisao["reutilizada"] else None), decisao


def _decidir(armazem, lt, caminho, hoje) -> dict:
    der = lt.derivados or {}
    if lt.erro or der.get("escore_versao") != VERSAO_ESCORE or der.get("origem_leitura") != "api":
        return dict(motivo="leitura sem escore válido de produção")
    if der.get("receita_hash") != proveniencia.receita_hash():
        return dict(motivo="receita da leitura mudou: reler")
    if not armazem.conferir_hash(lt.id):
        return dict(motivo="integridade da leitura inválida")
    try:
        bruto = (Path(caminho) if caminho else caminho_padrao()).read_bytes()
        cal = json.loads(bruto)
        hoje = hoje or dt.datetime.now(dt.UTC).date()
        if not dt.date.fromisoformat(cal["criado_em"]) <= hoje <= dt.date.fromisoformat(cal["valido_ate"]):
            return dict(motivo="calibração vencida ou futura")
        if cal["versao"] != VERSAO_ESCORE:
            return dict(motivo="versão do escore mudou")
        if cal.get("receita_hash") != der["receita_hash"] or cal.get("calibrador_hash") != proveniencia.calibrador_hash(
            risco=cal["risco_maximo"], confianca=cal["confianca"], cortes=CORTES.tolist()
        ):
            return dict(motivo="receita da calibração mudou: recalibrar")
        gabs = _gabaritos(armazem)
        if cal["gabaritos_hash"] != _hash_gabaritos(gabs):
            return dict(motivo="gabaritos mudaram: recalibrar")
        if any(g["leitura_id"] == lt.id and g["confirma"] == 0 for g in armazem.gabaritos()):
            return dict(motivo="leitura desmentida por conferência")
        corte = cal["grupos"].get(assinatura(lt), {}).get("corte")
        if corte is None:
            return dict(motivo="sem corte calibrado para esta receita")
        score = der["escore_confianca"]
        if not math.isfinite(corte) or not 0 < corte <= 1 or not math.isfinite(score) or not 0 <= score <= 1:
            return dict(motivo="escore ou corte inválido")
        reutilizada = score >= corte
        return dict(
            reutilizada=reutilizada,
            motivo="acima do corte calibrado" if reutilizada else "abaixo do corte: reler",
            escore=score,
            corte=corte,
            calibracao_hash=hashlib.sha256(bruto).hexdigest(),
            receita_hash=der["receita_hash"],
            calibrador_hash=cal["calibrador_hash"],
        )
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return dict(motivo="calibração ausente ou inválida")
