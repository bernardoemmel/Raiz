"""Apenas números artificiais e UUIDs; nenhum CAR ou proprietário real."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from raiz.avaliacao.contratos import (
    ControleEstavel,
    Estrato,
    GabaritoCego,
    Inclusao,
    MedicaoControle,
    PlanoMudanca,
    PrevisaoCarbono,
    Tolerancia,
)
from raiz.avaliacao.equidade import politica
from raiz.avaliacao.integridade import resumo_hash
from raiz.avaliacao.mudanca import Ensaio, hash_coorte, hash_inclusao

DIA = datetime(2026, 1, 1, tzinfo=UTC)


def id_(i):
    return UUID(int=i + 1)


def digest(i):
    return resumo_hash([i])


def inclusoes():
    return [
        Inclusao(
            caso_id=id_(mun * 1000 + porte * 100 + j),
            decisao_id=id_(9000),
            municipio=municipio,
            modulos_fiscais=modulos,
            aptidao="alta",
            entrou=j % 2 == 0,
        )
        for mun, municipio in enumerate((1504950, 1505536))
        for porte, modulos in enumerate((2, 8, 20))
        for j in range(40)
    ]


def ensaio():
    controle = ControleEstavel(
        controle_id=id_(7000),
        fixado_em=DIA,
        procedimento_sha256=digest(1),
        referencia_sha256=digest(2),
        centro=10,
        desvio_padrao=1,
        multiplicador=3,
        minimo_referencia=20,
        referencia_n=30,
    )
    anteriores, candidatas, gabaritos, tolerancias = [], [], [], []
    for i, porte in enumerate(("pequena", "media", "grande")):
        estrato = Estrato(municipio=1504950, porte=porte, aptidao="alta")
        tolerancias.append(Tolerancia(estrato=estrato, minimo=30, aumento_crps_max=0.1, crps_max=2))
        for j in range(30):
            base = dict(
                caso_id=id_(i * 100 + j),
                entradas_sha256=digest(3),
                receita_sha256=digest(4),
                decisao_em=DIA + timedelta(days=1),
                entradas_disponiveis_em=DIA,
                horizonte_em=DIA + timedelta(days=365),
            )
            anteriores.append(
                PrevisaoCarbono(**base, modelo_sha256=digest(5), emitida_em=base["decisao_em"], sorteios=(8, 10, 12))
            )
            candidatas.append(
                PrevisaoCarbono(
                    **{**base, "receita_sha256": digest(6)},
                    modelo_sha256=digest(7),
                    emitida_em=DIA + timedelta(days=100),
                    sorteios=(9, 10, 11),
                )
            )
            gabaritos.append(
                GabaritoCego(
                    caso_id=base["caso_id"],
                    estrato=estrato,
                    valor=10,
                    incerteza_padrao=0.1,
                    horizonte_em=base["horizonte_em"],
                    medido_em=DIA + timedelta(days=366),
                    registrado_em=DIA + timedelta(days=367),
                    revelado_em=DIA + timedelta(days=368),
                    laboratorio_id=id_(8000),
                    amostra_cega_id=id_(9000 + i * 100 + j),
                    procedimento_sha256=digest(1),
                    evidencia_sha256=digest(8 + i * 100 + j),
                    metodo="campo_independente",
                    controle_id=controle.controle_id,
                )
            )
    coorte = inclusoes()
    plano = PlanoMudanca(
        plano_id=id_(6000),
        fixado_em=DIA + timedelta(days=2),
        inicio_treino_em=DIA + timedelta(days=3),
        modelo_anterior_sha256=digest(5),
        receita_candidata_sha256=digest(6),
        previsoes_anteriores_sha256=hash_coorte(anteriores),
        conjunto_cego_sha256=hash_coorte(gabaritos),
        controle_sha256=resumo_hash(controle),
        coorte_inclusao_sha256=hash_inclusao(coorte),
        politica_equidade_sha256=resumo_hash(politica()),
        mudancas=("calibracao",),
        tolerancias=tuple(tolerancias),
        condicao_retorno="qualquer_subgrupo_ou_controle_fora_da_tolerancia",
    )
    return Ensaio(
        plano=plano,
        anteriores=tuple(anteriores),
        candidatas=tuple(candidatas),
        gabaritos=tuple(gabaritos),
        controle=controle,
        inclusoes=tuple(coorte),
        medicoes_controle=(
            MedicaoControle(
                controle_id=controle.controle_id,
                procedimento_sha256=digest(1),
                medido_em=DIA + timedelta(days=366),
                valor=10,
            ),
        ),
    )
