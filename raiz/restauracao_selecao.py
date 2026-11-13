"""Grupos operacionais indivisíveis e seleção com orçamento explícito de busca.

O limite vale para o modelo inteiro, inclusive no fallback. Grupo espacial não
comprova contiguidade dos polígonos. Uma busca limitada nunca é anunciada como
ótimo global ou como prova de inexistência de oferta fora dos candidatos.
"""

from __future__ import annotations

import hashlib
import math
import time
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.spatial import cKDTree

from raiz.pedidos.campos import CamposPedido
from raiz.pedidos.premissas import premissas

VERSAO = "selecao-nacional-1"
RAIO_TERRA_KM = 6371.0088


@dataclass(frozen=True)
class LimitesSelecao:
    grupos_iniciais: int = 128
    grupos_maximos: int = 3000
    tempo_solver_s: float = 15.0
    gap_relativo: float = 0.002
    ancoras_espaciais: int = 32

    def __post_init__(self):
        if not 1 <= self.grupos_iniciais <= self.grupos_maximos <= 10000:
            raise ValueError("A busca exige 1 <= grupos iniciais <= máximos <= 10.000.")
        if not 0 < self.tempo_solver_s <= 120 or not 0 <= self.gap_relativo <= 1:
            raise ValueError("Tempo/gap da busca fora do orçamento permitido.")
        if not 1 <= self.ancoras_espaciais <= 128:
            raise ValueError("Número de âncoras espaciais fora do orçamento.")


def _esfera(lon, lat):
    lon, lat = np.radians(lon), np.radians(lat)
    return np.column_stack([np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat)])


def distancia_km(lon, lat, lon0, lat0):
    a, b = np.radians(lat), np.radians(lat0)
    dlon = np.radians(lon) - np.radians(lon0)
    h = np.sin((a - b) / 2) ** 2 + np.cos(a) * np.cos(b) * np.sin(dlon / 2) ** 2
    return 2 * RAIO_TERRA_KM * np.arcsin(np.sqrt(np.clip(h, 0, 1)))


def agrupar_oferta(oferta: pd.DataFrame, *, diametro_km: float = 15.0, max_membros: int = 128) -> pd.DataFrame:
    """Agrupa pequenas sem barreira de UF/município/célula e sem matriz quadrática.

    Vizinhas ficam até diâmetro/2 do ponto âncora: pela desigualdade triangular,
    qualquer par fica dentro do diâmetro. O limite operacional de membros e a
    busca k-vizinhos são declarados; grupos unitários preservam todo imóvel.
    Coordenada aproximada/ausente não é usada como prova de vizinhança.
    """
    if not 0 < diametro_km <= 1000 or not 2 <= max_membros <= 512:
        raise ValueError("Diâmetro ou tamanho operacional inválido.")
    if oferta.cod_imovel.isna().any() or not oferta.cod_imovel.is_unique:
        raise ValueError("Cada imóvel deve aparecer uma única vez no agrupamento.")
    f = oferta.sort_values("cod_imovel", kind="stable").reset_index(drop=True)
    n = len(f)
    if not n:
        return pd.DataFrame(
            columns=["cod_imovel", "grupo_id", "grupo_lon", "grupo_lat", "grupo_raio_km", "agrupamento_pendente"]
        )
    lon, lat = f.lon.to_numpy(float), f.lat.to_numpy(float)
    valido = np.isfinite(lon) & np.isfinite(lat) & (np.abs(lon) <= 180) & (np.abs(lat) <= 90)
    if "local_aproximado" in f:
        valido &= ~f.local_aproximado.fillna(True).to_numpy(bool)
    pequenas = f.pequena.fillna(False).to_numpy(bool)
    pontos = np.flatnonzero(valido & pequenas)
    xyz = _esfera(lon[pontos], lat[pontos])
    arvore = cKDTree(xyz) if len(pontos) else None
    atribuido = np.zeros(n, dtype=bool)
    grupos = np.empty(n, dtype=object)
    glon, glat, raio = np.full(n, np.nan), np.full(n, np.nan), np.zeros(n)
    chord = 2 * math.sin(diametro_km / (4 * RAIO_TERRA_KM))
    for local, i in enumerate(pontos):
        if atribuido[i]:
            continue
        # k limita inclusive bairros muito densos; nenhum imóvel fora da busca é descartado.
        dist, viz = arvore.query(xyz[local], k=min(max_membros * 2, len(pontos)), distance_upper_bound=chord)
        dist, viz = np.atleast_1d(dist), np.atleast_1d(viz)
        viz = viz[np.isfinite(dist)]
        membros = pontos[viz]
        membros = membros[~atribuido[membros]]
        membros = np.unique(np.append(i, membros))[:max_membros]
        gid = "g-" + hashlib.sha256(f.cod_imovel.iloc[i].encode()).hexdigest()[:20]
        grupos[membros] = gid
        glon[membros], glat[membros] = lon[i], lat[i]
        raio[membros] = float(np.max(distancia_km(lon[membros], lat[membros], lon[i], lat[i])))
        atribuido[membros] = True
    for i in np.flatnonzero(~atribuido):
        grupos[i] = "g-" + hashlib.sha256(f.cod_imovel.iloc[i].encode()).hexdigest()[:20]
        if valido[i]:
            glon[i], glat[i] = lon[i], lat[i]
    return pd.DataFrame(
        {
            "cod_imovel": f.cod_imovel,
            "grupo_id": grupos,
            "grupo_lon": glon,
            "grupo_lat": glat,
            "grupo_raio_km": raio,
            "agrupamento_pendente": ~valido,
        }
    )


def _validar_forma(grupos: pd.DataFrame, pedido: CamposPedido) -> list[str]:
    erros = []
    if not len(grupos):
        return erros
    if pedido.forma.max_donos and grupos.membros.sum() > pedido.forma.max_donos:
        erros.append("max_donos")
    if pedido.forma.area_min_contigua_ha:
        if "contiguidade_verificada" not in grupos or not grupos.contiguidade_verificada.fillna(False).all():
            erros.append("contiguidade_nao_comprovada")
        elif "area_contigua_ha" not in grupos or (grupos.area_contigua_ha < pedido.forma.area_min_contigua_ha).any():
            erros.append("area_contigua_insuficiente")
    if pedido.forma.distancia_max_km:
        lon, lat, r = (grupos[c].to_numpy(float) for c in ("grupo_lon", "grupo_lat", "grupo_raio_km"))
        if not (np.isfinite(lon).all() and np.isfinite(lat).all() and np.isfinite(r).all()):
            erros.append("localizacao_nao_comprovada")
        else:
            # Limite conservador entre círculos; não afirma que pontos sejam polígonos contíguos.
            for i in range(len(lon)):
                d = distancia_km(lon[i + 1 :], lat[i + 1 :], lon[i], lat[i]) + r[i + 1 :] + r[i]
                if r[i] * 2 > pedido.forma.distancia_max_km + 1e-8 or (d > pedido.forma.distancia_max_km + 1e-8).any():
                    erros.append("distancia_max_km")
                    break
    return erros


def _janela_espacial(g, ordem, pedido, limite):
    dmax = pedido.forma.distancia_max_km
    if dmax is None or not len(ordem):
        return ordem
    lon, lat, raio = (g[c].to_numpy(float) for c in ("grupo_lon", "grupo_lat", "grupo_raio_km"))
    melhor, criterio = np.array([], dtype=int), (-1.0, -1)
    for i in ordem[: limite.ancoras_espaciais]:
        if not math.isfinite(lon[i]) or not math.isfinite(lat[i]):
            continue
        d = distancia_km(lon[ordem], lat[ordem], lon[i], lat[i]) + raio[ordem]
        janela = ordem[np.isfinite(d) & (d <= dmax / 2 + 1e-8)]
        # Toda a janela cabe em uma bola de raio dmax/2; reservas obedecem à mesma janela.
        valor = (min(float(g.quantidade.iloc[janela].sum()), pedido.meta.valor * 1.5), -len(janela))
        if valor > criterio:
            melhor, criterio = janela, valor
    return melhor


def _ordenar_compacta(g, ordem, alvo, limite):
    """Prioriza vizinhanças capazes de cobrir a meta; busca espacial limitada e declarada."""
    if not len(ordem):
        return ordem, None
    lon, lat = (g[c].to_numpy(float) for c in ("grupo_lon", "grupo_lat"))
    validos = ordem[np.isfinite(lon[ordem]) & np.isfinite(lat[ordem])]
    if not len(validos):
        return ordem, None
    arvore = cKDTree(_esfera(lon[validos], lat[validos]))
    melhor, criterio, ancora = None, (math.inf, math.inf), None
    k = min(len(validos), limite.grupos_maximos)
    for i in validos[: limite.ancoras_espaciais]:
        _, pos = arvore.query(_esfera([lon[i]], [lat[i]]), k=k)
        vizinhos = validos[np.atleast_1d(pos).ravel()]
        soma = np.cumsum(g.quantidade.to_numpy(float)[vizinhos])
        n = min(k, int(np.searchsorted(soma, alvo)) + 1)
        dist = distancia_km(lon[vizinhos[:n]], lat[vizinhos[:n]], lon[i], lat[i])
        valor = (max(0.0, alvo - soma[n - 1]), float(np.max(dist)))
        if valor < criterio:
            melhor, criterio, ancora = vizinhos, valor, int(i)
    mascara = np.zeros(len(g), dtype=bool)
    mascara[melhor] = True
    return np.concatenate([melhor, ordem[~mascara[ordem]]]), ancora


def selecionar_grupos(
    grupos: pd.DataFrame,
    pedido: CamposPedido,
    opcao: str,
    *,
    limites: LimitesSelecao | None = None,
    reserva_meta: float | None = None,
) -> dict:
    """Seleciona IDs de grupos completos. Valores agregados já incluem todos os membros.

    Colunas: grupo_id, quantidade, credito_p50, area_ha, membros, custo_total,
    risco_total, penalidade_total, grupo_lon/lat/raio_km. Não recalcula previsões.
    """
    inicio = time.monotonic()
    limites = limites or LimitesSelecao()
    p = premissas()["otimizador"]
    if opcao not in p["pesos"]:
        raise ValueError("Opção desconhecida.")
    exigidas = {
        "grupo_id",
        "quantidade",
        "credito_p50",
        "area_ha",
        "membros",
        "custo_total",
        "risco_total",
        "penalidade_total",
        "grupo_lon",
        "grupo_lat",
        "grupo_raio_km",
    }
    if not exigidas <= set(grupos) or not grupos.grupo_id.is_unique:
        raise ValueError("Grupos sem colunas obrigatórias ou com identidade duplicada.")
    g = grupos.reset_index(drop=True)
    q = g.quantidade.to_numpy(float)
    if not np.isfinite(q).all() or (q <= 0).any() or (g.membros < 1).any():
        raise ValueError("Quantidade e número de membros devem ser positivos e finitos.")
    w = p["pesos"][opcao]
    objetivo = (
        w["custo"] * g.custo_total.to_numpy(float)
        + w["risco"] * g.risco_total.to_numpy(float)
        + g.penalidade_total.to_numpy(float)
        + w["compacta"] * p["custo_grupo_usd"]
    )
    if not np.isfinite(objetivo).all() or (objetivo < 0).any():
        raise ValueError("Custos da seleção precisam ser finitos e não negativos.")
    ordem = np.lexsort((g.grupo_id.astype(str).to_numpy(), objetivo / q))
    if pedido.forma.max_donos:
        ordem = ordem[g.membros.iloc[ordem].to_numpy() <= pedido.forma.max_donos]
    impedimentos = []
    if pedido.forma.area_min_contigua_ha:
        if "contiguidade_verificada" not in g or "area_contigua_ha" not in g:
            ordem = np.array([], dtype=int)
            impedimentos.append("Contiguidade exige geometria/evidência; área de pontos agrupados não a comprova.")
        else:
            ok = g.contiguidade_verificada.fillna(False) & (g.area_contigua_ha >= pedido.forma.area_min_contigua_ha)
            ordem = ordem[ok.iloc[ordem].to_numpy(bool)]
    alvo_reserva = float(reserva_meta if reserva_meta is not None else pedido.meta.valor * p["reserva_fracao"])
    if not math.isfinite(alvo_reserva) or alvo_reserva < 0:
        raise ValueError("Meta de reserva deve ser finita e não negativa.")
    ancora = None
    if opcao == "compacta":
        ordem, ancora = _ordenar_compacta(g, ordem, 1.5 * (pedido.meta.valor + alvo_reserva), limites)
    n_busca = min(len(ordem), limites.grupos_iniciais)
    expansoes = []
    alvo_pool = max(3 * pedido.meta.valor, pedido.meta.valor + alvo_reserva)
    while n_busca and q[ordem[:n_busca]].sum() < alvo_pool and n_busca < min(len(ordem), limites.grupos_maximos):
        expansoes.append(n_busca)
        n_busca = min(n_busca * 2, len(ordem), limites.grupos_maximos)
    pool = ordem[:n_busca]
    pool = _janela_espacial(g, pool, pedido, limites)
    selecionados, reservas, estado, gap, solver_status = [], [], "sem_candidato", None, None
    if len(pool):
        alvo = min(float(pedido.meta.valor), float(q[pool].sum()))
        matriz, baixos, altos = [q[pool]], [alvo], [np.inf]
        if pedido.forma.max_donos:
            matriz.append(g.membros.iloc[pool].to_numpy(float))
            baixos.append(0)
            altos.append(pedido.forma.max_donos)
        try:
            resultado = milp(
                c=objetivo[pool],
                integrality=np.ones(len(pool)),
                bounds=Bounds(0, 1),
                constraints=LinearConstraint(np.asarray(matriz), baixos, altos),
                options={"time_limit": limites.tempo_solver_s, "mip_rel_gap": limites.gap_relativo},
            )
            solver_status = int(resultado.status)
            x = resultado.x
            gap = getattr(resultado, "mip_gap", None)
        except (ValueError, RuntimeError):
            x = None
        if x is not None:
            selecionados = pool[np.asarray(x) > 0.5].tolist()
            estado = "otimo_nos_candidatos" if solver_status == 0 else "limite_solver"
        else:
            total, donos = 0.0, 0
            for i in pool:
                if total >= pedido.meta.valor:
                    break
                if pedido.forma.max_donos and donos + int(g.membros.iloc[i]) > pedido.forma.max_donos:
                    continue
                selecionados.append(int(i))
                total += q[i]
                donos += int(g.membros.iloc[i])
            estado = "heuristica_verificada"
        # Reserva percorre candidatos adicionais, ainda sob o teto global e a mesma forma.
        restantes = [int(i) for i in pool if i not in set(selecionados)]
        total, donos = 0.0, int(g.membros.iloc[selecionados].sum())
        for i in restantes:
            if total >= alvo_reserva:
                break
            if pedido.forma.max_donos and donos + int(g.membros.iloc[i]) > pedido.forma.max_donos:
                continue
            reservas.append(i)
            total += q[i]
            donos += int(g.membros.iloc[i])
        if total < alvo_reserva and n_busca < min(len(ordem), limites.grupos_maximos):
            novos = ordem[n_busca : limites.grupos_maximos]
            for i in novos:
                if total >= alvo_reserva:
                    break
                if pedido.forma.max_donos and donos + int(g.membros.iloc[i]) > pedido.forma.max_donos:
                    continue
                if _validar_forma(g.iloc[selecionados + reservas + [int(i)]], pedido):
                    continue
                reservas.append(int(i))
                total += q[i]
                donos += int(g.membros.iloc[i])
            n_busca = min(len(ordem), limites.grupos_maximos)
    erros = _validar_forma(g.iloc[selecionados + reservas], pedido)
    if erros:
        raise RuntimeError("Resultado recusado pela verificação das restrições: " + ", ".join(erros))
    obtido, reservado = float(q[selecionados].sum()), float(q[reservas].sum())
    corte = n_busca < len(ordem)
    if obtido < pedido.meta.valor - 1e-8:
        estado = "limite_busca" if corte or pedido.forma.distancia_max_km else "oferta_ou_forma_insuficiente"
    if impedimentos:
        estado = "evidencia_de_forma_pendente"
    sel = g.iloc[selecionados + reservas]
    diametro = None
    if ancora is not None and len(sel) and sel[["grupo_lon", "grupo_lat"]].notna().all().all():
        dist = distancia_km(
            sel.grupo_lon.to_numpy(float),
            sel.grupo_lat.to_numpy(float),
            g.grupo_lon.iloc[ancora],
            g.grupo_lat.iloc[ancora],
        ) + sel.grupo_raio_km.to_numpy(float)
        diametro = float(2 * max(dist))  # limite superior pela bola, não distância máxima medida entre polígonos
    return {
        "titulares": g.grupo_id.iloc[selecionados].tolist(),
        "reservas": g.grupo_id.iloc[reservas].tolist(),
        "estado": estado,
        "quantidade_titulares": obtido,
        "quantidade_reservas": reservado,
        "fecha_meta": obtido >= pedido.meta.valor - 1e-8,
        "fecha_reserva": reservado >= alvo_reserva - 1e-8,
        "diagnosticos": {
            "versao": VERSAO,
            "limites": asdict(limites),
            "grupos_disponiveis": len(g),
            "grupos_examinados": n_busca,
            "variaveis_milp": len(pool),
            "expansoes": expansoes,
            "busca_limitada": corte or bool(pedido.forma.distancia_max_km),
            "otimo_global_comprovado": False,
            "gap_nos_candidatos": float(gap) if gap is not None and math.isfinite(float(gap)) else None,
            "solver_status": solver_status,
            "restricoes_verificadas": True,
            "impedimentos": impedimentos,
            "duracao_s": time.monotonic() - inicio,
            "compacidade": "vizinhancas_por_ancoras_e_numero_de_grupos"
            if opcao == "compacta"
            else "sem_objetivo_espacial",
            "diametro_limite_superior_km": diametro,
            "ancoras_espaciais_maximas": limites.ancoras_espaciais if opcao == "compacta" else 0,
        },
    }
