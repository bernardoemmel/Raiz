"""Portão PCCP: protocolo fixado, comparação pareada cega e retorno por subgrupo/controle."""

from collections import defaultdict

from pydantic import Field, model_validator

from raiz.avaliacao.contratos import (
    Contrato,
    ControleEstavel,
    GabaritoCego,
    Inclusao,
    MedicaoControle,
    PlanoMudanca,
    PrevisaoCarbono,
)
from raiz.avaliacao.equidade import medir, politica
from raiz.avaliacao.integridade import resumo_hash
from raiz.avaliacao.metricas import crps


def hash_coorte(registros) -> str:
    return resumo_hash(sorted(registros, key=lambda x: str(x.caso_id)))


def hash_inclusao(xs) -> str:
    return resumo_hash(
        sorted(
            [x.model_dump(mode="json", exclude={"entrou"}) for x in xs],
            key=lambda x: (x["decisao_id"], x["caso_id"]),
        )
    )


class Ensaio(Contrato):
    plano: PlanoMudanca
    anteriores: tuple[PrevisaoCarbono, ...] = Field(min_length=1)
    candidatas: tuple[PrevisaoCarbono, ...] = Field(min_length=1)
    gabaritos: tuple[GabaritoCego, ...] = Field(min_length=1)
    controle: ControleEstavel
    medicoes_controle: tuple[MedicaoControle, ...] = Field(min_length=1)
    inclusoes: tuple[Inclusao, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def pareamento(self):
        conjuntos = [{x.caso_id for x in xs} for xs in (self.anteriores, self.candidatas, self.gabaritos)]
        if not conjuntos[0] == conjuntos[1] == conjuntos[2]:
            raise ValueError("previsões e gabarito devem cobrir exatamente a mesma coorte")
        if any(
            len(ids) != len(xs)
            for ids, xs in zip(conjuntos, (self.anteriores, self.candidatas, self.gabaritos), strict=True)
        ):
            raise ValueError("caso repetido na prova")
        if len({x.amostra_cega_id for x in self.gabaritos}) != len(self.gabaritos):
            raise ValueError("amostra cega repetida")
        return self


def avaliar(ensaio: Ensaio) -> dict:
    p, controle = ensaio.plano, ensaio.controle
    regra = politica()
    if resumo_hash(regra) != p.politica_equidade_sha256:
        raise ValueError("política de equidade diverge do plano")
    if hash_coorte(ensaio.anteriores) != p.previsoes_anteriores_sha256:
        raise ValueError("previsões anteriores divergem do plano congelado")
    if hash_coorte(ensaio.gabaritos) != p.conjunto_cego_sha256 or resumo_hash(controle) != p.controle_sha256:
        raise ValueError("gabarito ou controle divergem do plano congelado")
    if controle.fixado_em > p.fixado_em:
        raise ValueError("controle fixado depois do plano")
    tolerancias = {x.estrato.chave: x for x in p.tolerancias}
    if {x.estrato.chave for x in ensaio.gabaritos} != set(tolerancias):
        raise ValueError("cobertura de subgrupos diverge do plano")
    anteriores = {x.caso_id: x for x in ensaio.anteriores}
    candidatas = {x.caso_id: x for x in ensaio.candidatas}
    notas = defaultdict(list)
    if len({x.modelo_sha256 for x in ensaio.candidatas}) != 1:
        raise ValueError("candidato precisa usar uma só versão congelada")
    for g in ensaio.gabaritos:
        a, c = anteriores[g.caso_id], candidatas[g.caso_id]
        if (
            a.modelo_sha256 != p.modelo_anterior_sha256
            or c.receita_sha256 != p.receita_candidata_sha256
            or c.modelo_sha256 == p.modelo_anterior_sha256
        ):
            raise ValueError("versão de modelo diverge do plano")
        if not (a.emitida_em <= p.fixado_em < p.inicio_treino_em <= c.emitida_em < g.revelado_em):
            raise ValueError("plano tardio ou gabarito revelado antes da previsão")
        if a.horizonte_em != c.horizonte_em or c.horizonte_em != g.horizonte_em:
            raise ValueError("horizontes diferentes não podem ser pareados")
        if a.decisao_em != c.decisao_em or a.entradas_sha256 != c.entradas_sha256:
            raise ValueError("decisão ou retrato de entradas diferente")
        if g.controle_id != controle.controle_id or g.procedimento_sha256 != controle.procedimento_sha256:
            raise ValueError("gabarito sem controle do mesmo procedimento")
        notas[g.estrato.chave].append((crps(g.valor, a.sorteios), crps(g.valor, c.sorteios)))
    subgrupos = []
    for chave, pares in sorted(notas.items()):
        t = tolerancias[chave]
        anterior = sum(a for a, _ in pares) / len(pares)
        candidata = sum(c for _, c in pares) / len(pares)
        aprovado = len(pares) >= t.minimo and candidata <= t.crps_max and candidata - anterior <= t.aumento_crps_max
        subgrupos.append(
            {
                "estrato": t.estrato.model_dump(),
                "n": len(pares),
                "crps_anterior": anterior,
                "crps_candidata": candidata,
                "aprovado": aprovado,
            }
        )
    for m in ensaio.medicoes_controle:
        if m.controle_id != controle.controle_id or m.procedimento_sha256 != controle.procedimento_sha256:
            raise ValueError("medição de controle sem vínculo ao padrão congelado")
        if m.medido_em <= controle.fixado_em:
            raise ValueError("medição de controle anterior à referência")
    datas_controle = {m.medido_em.date() for m in ensaio.medicoes_controle}
    if not {g.medido_em.date() for g in ensaio.gabaritos} <= datas_controle:
        raise ValueError("dia de medição do gabarito sem controle")
    controle_ok = all(
        abs(m.valor - controle.centro) <= controle.multiplicador * controle.desvio_padrao
        for m in ensaio.medicoes_controle
    )
    if hash_inclusao(ensaio.inclusoes) != p.coorte_inclusao_sha256:
        raise ValueError("denominador ou aptidão da inclusão diverge do plano")
    equidade = medir(
        list(ensaio.inclusoes), limite=regra["equidade_diferenca_maxima"], minimo=regra["equidade_minimo_por_classe"]
    )
    aprovado = controle_ok and equidade["aprovado"] and all(x["aprovado"] for x in subgrupos)
    return {
        "aprovado": aprovado,
        "acao": "elegivel_para_revisao" if aprovado else "manter_ou_retornar_anterior",
        "plano_sha256": resumo_hash(p),
        "controle_aprovado": controle_ok,
        "subgrupos": subgrupos,
        "equidade": equidade,
    }
