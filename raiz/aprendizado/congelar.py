"""Congela como previsão o que o motor já afirma sobre cada imóvel, para comparar com o gabarito quando ele chegar.

Cada alvo diz de onde vem, o horizonte (quando dá para conferir) e qual gabarito vai confirmar ou desmentir.
Se a Raíz carregou uma saída pronta (não rodou o motor), a versão do modelo leva o sufixo "-suposta": o código do
motor no repositório pode não ser o que gerou aquele arquivo.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from sqlalchemy import Connection, text

from raiz.aprendizado.registro import Previsao, Versoes, registrar_lote


@dataclass(frozen=True)
class Alvo:
    nome: str
    tabela: str  # resultado | filtro | complemento:<tipo>
    coluna: str
    tipo: str  # num | texto | bool
    horizonte_dias: int
    gabarito: str  # o que vai dizer se acertou


ALVOS_MOTOR: list[Alvo] = [
    Alvo("frente", "resultado", "frente", "texto", 365, "caminho que o imóvel seguiu (projeto, aceite, recusa)"),
    Alvo("problema", "resultado", "problema", "bool", 365, "embargo, TI, PRODES ou alerta confirmados no ano seguinte"),
    Alvo("eudr_ok", "resultado", "eudr_ok", "bool", 365, "due diligence do comprador europeu"),
    Alvo("compra_arrendamento", "resultado", "compra_arrendamento", "bool", 365, "certidão de matrícula"),
    Alvo("f_matricula", "resultado", "f_matricula", "num", 365, "certidão de matrícula e SIGEF conferidos"),
    Alvo("deficit_rl_ha", "resultado", "deficit_rl_ha", "num", 730, "análise do CAR pelo órgão estadual (SICAR)"),
    Alvo("alem_rl_ha", "resultado", "alem_rl_ha", "num", 730, "análise do CAR pelo órgão estadual (SICAR)"),
    Alvo("app_recompor_ha", "resultado", "app_recompor_ha", "num", 730, "análise do CAR pelo órgão estadual"),
    Alvo("carbono_ha", "resultado", "carbono_ha", "num", 1825, "área com regeneração medida (campo ou YbYrá)"),
    Alvo("carbono_tco2_ano", "resultado", "carbono_tco2_ano", "num", 1825, "medição de carbono em campo"),
    Alvo("filtro_territorial", "filtro", "filtro_territorial", "texto", 365, "checagem jurídica do território"),
    Alvo("persistencia_nota", "complemento:extras", "persistencia_nota", "num", 1825, "capoeira ainda de pé (YbYrá)"),
]


def _valor(alvo: Alvo, v) -> tuple[float | None, str | None]:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None, None
    if alvo.tipo == "num":
        try:
            x = float(v)
        except (TypeError, ValueError):
            return None, None
        return (None, None) if math.isnan(x) or math.isinf(x) else (x, None)
    if alvo.tipo == "bool":
        if isinstance(v, str):
            v = {"true": True, "false": False}.get(v.lower(), v)
        return (None, "sim" if v else "não") if isinstance(v, bool) else (None, None)
    return None, str(v)


def _valores(con: Connection, rodada_id: int, alvo: Alvo):
    if alvo.tabela == "resultado":
        q = f"select cod_imovel, {alvo.coluna} as v from funil.resultado_imovel where rodada_id = :r"
        params = {"r": rodada_id}
    elif alvo.tabela == "filtro":
        q = f"select cod_imovel, {alvo.coluna} as v from funil.filtro_imovel where rodada_id = :r"
        params = {"r": rodada_id}
    else:
        q = "select cod_imovel, atributos->:col as v from funil.complemento_imovel where rodada_id = :r and tipo = :t"
        params = {"r": rodada_id, "t": alvo.tabela.split(":", 1)[1], "col": alvo.coluna}
    return con.execute(text(q), params).all()


def previsoes_da_rodada(con: Connection, rodada_id: int, alvos: list[Alvo] = ALVOS_MOTOR) -> list[Previsao]:
    out = []
    for a in alvos:
        for cod, v in _valores(con, rodada_id, a):
            vn, vt = _valor(a, v)
            if vn is not None or vt is not None:
                out.append(Previsao(cod, a.nome, a.horizonte_dias, valor_num=vn, valor_texto=vt))
    return out


def congelar_rodada(con: Connection, rodada_id: int) -> tuple[str, bool, int]:
    """Congela as previsões do motor de uma rodada de município. Devolve (lote_hash, novo, n_previsoes)."""
    r = con.execute(text("select * from funil.rodada where id = :i"), {"i": rodada_id}).first()
    if r is None or r.tipo != "municipio":
        raise ValueError(f"rodada {rodada_id} não é de município")
    previsoes = previsoes_da_rodada(con, rodada_id)
    versao = r.motor_versao if r.motor_versao_confirmada else f"{r.motor_versao}-suposta"
    v = Versoes(
        modelo="motor",
        modelo_versao=versao,
        entradas_versao=r.hash_entradas,
        data_corte=r.data_corte,
        regras_versao=r.regras_versao,
        tipo="ao_vivo",
        rodada_id=rodada_id,
    )
    desc = f"motor, município {r.cod_municipio} ({r.uf}), rodada {rodada_id}"
    lh, novo = registrar_lote(con, previsoes, v, desc)
    # o valor para quem restaura vai num lote à parte, com a versão do modelo dele (raiz/restauracao.py)
    from raiz.restauracao_aprendizado import congelar_restauracao

    congelar_restauracao(con, rodada_id)
    # a chance a priori de título da posse, idem (raiz/titulo/regularizacao.py)
    from raiz.titulo.regularizacao import congelar_regularizacao

    congelar_regularizacao(con, rodada_id)
    # a chance de a busca completa achar problema no título, idem (raiz/titulo/triagem.py)
    from raiz.titulo.triagem import congelar_triagem

    congelar_triagem(con, rodada_id)
    return lh, novo, len(previsoes)
