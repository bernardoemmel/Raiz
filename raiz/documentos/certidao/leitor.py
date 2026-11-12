"""Leitor de certidão de matrícula: PDF -> leitura (modelo) -> regras (código) -> conferência com o motor -> armazém.

    from raiz.documentos.certidao.leitor import ler_certidao
    r = ler_certidao("certidao.pdf", cod_imovel="PA-1504950-0E3B...")
    r.conferencias[0].situacao   # conferida | divergente | cancelada | revisar

A leitura pode vir de gente (json_manual): fica gravada com modelo="humano" e serve de gabarito para o modelo.
Reconferir (reconferir()) refaz só a conferência, sem pagar outra leitura, quando o motor ou as regras mudam.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import io
import logging
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from raiz.documentos import __version__, tabelas
from raiz.documentos.armazem import Armazem, Leitura
from raiz.documentos.certidao import cache, esquema, proveniencia
from raiz.documentos.certidao.conferencia import Conferencia, conferir, versao_regras
from raiz.documentos.certidao.regras import Derivados, derivar, normalizar_cns, normalizar_matricula
from raiz.documentos.claude import LeitorClaude, falta_campo
from raiz.documentos.config import municipio_do_imovel
from raiz.documentos.privacidade import limpar, mascarar_documento

log = logging.getLogger(__name__)

INSTITUICOES = {"orgao_publico", "instituicao_financeira"}


@dataclass
class ResultadoCertidao:
    leitura: Leitura
    derivados: Derivados | None = None
    conferencias: list[Conferencia] = field(default_factory=list)
    cache: dict | None = None

    @property
    def erro(self) -> str | None:
        return self.leitura.erro

    @property
    def situacao(self) -> str | None:
        """A pior situação entre os imóveis (para mensagem curta)."""
        ordem = ["revisar", "cancelada", "divergente", "conferida"]
        sits = [c.situacao for c in self.conferencias]
        return next((s for s in ordem if s in sits), None)


def paginas_pdf(pdf: bytes) -> int | None:
    try:
        from pypdf import PdfReader

        return len(PdfReader(io.BytesIO(pdf)).pages)
    except Exception:  # noqa: BLE001 - PDF quebrado ainda pode ser lido pelo modelo
        return None


def sanear(dados: dict) -> dict:
    """Segunda e terceira trancas: documento só mascarado, nome de instituição só para órgão público e banco, nomes
    fora dos textos livres. Roda em toda leitura, inclusive a manual."""
    partes = []
    for p in dados.get("partes") or []:
        p = dict(p)
        p["documento"] = mascarar_documento(p.get("documento"))
        if p.get("tipo") not in INSTITUICOES:
            p["nome_instituicao"] = None
        partes.append(p)
    dados = {**dados, "partes": partes}
    lugares = [(dados.get("imovel") or {}).get("municipio"), (dados.get("cartorio") or {}).get("comarca")]
    return limpar(dados, esquema.CHAVES_SEGURAS, permitir=[x for x in lugares if x])


def chave_certidao(dados: dict) -> str:
    cns = normalizar_cns((dados.get("cartorio") or {}).get("cns")) or "?"
    mat = normalizar_matricula((dados.get("matricula") or {}).get("numero")) or "?"
    return f"cns:{cns}|mat:{mat}"


def _motor(dados: dict, cod_imovel: str | None, cod_municipio: int | None) -> tuple[pd.DataFrame | None, ...]:
    """(linhas do certidoes_<mun>.csv, imoveis_<mun>.csv, arquivo). Sem município, procura em todos os arquivos."""
    cod_mun = cod_municipio or (municipio_do_imovel(cod_imovel) if cod_imovel else None)
    if cod_mun:
        caminho = tabelas.achar("certidoes", cod_mun)
        motor = tabelas.ler_csv(caminho) if caminho else None
        tem = motor is not None and (not cod_imovel or (motor.cod_imovel == cod_imovel).any())
        if tem or cod_municipio:
            return motor, tabelas.ler("imoveis", cod_mun), str(caminho) if caminho else None
    # sem município, ou CAR que cruza divisa (aparece no arquivo de outro município): procura em todos
    mat = normalizar_matricula((dados.get("matricula") or {}).get("numero"))
    for caminho in tabelas.arquivos("certidoes"):
        df = tabelas.ler_csv(caminho)
        if cod_imovel:
            achou = "cod_imovel" in df.columns and (df.cod_imovel == cod_imovel).any()
        else:
            achou = (
                "registro_matricula" in df.columns and (df.registro_matricula.map(normalizar_matricula) == mat).any()
            )
        if achou:
            cod = tabelas.municipio_do_arquivo(caminho)
            return df, tabelas.ler("imoveis", cod) if cod else None, str(caminho)
    return None, None, None


def ler_certidao(
    arquivo: str | Path | bytes,
    *,
    cod_imovel: str | None = None,
    cod_municipio: int | None = None,
    leitor: LeitorClaude | None = None,
    armazem: Armazem | None = None,
    json_manual: dict | None = None,
    hoje: dt.date | None = None,
    forcar_releitura: bool = False,
    calibracao_cache: str | Path | None = None,
) -> ResultadoCertidao:
    pdf = arquivo if isinstance(arquivo, bytes) else Path(arquivo).read_bytes()
    sha = hashlib.sha256(pdf).hexdigest()
    armazem = armazem or Armazem()
    base = dict(
        tipo="certidao",
        arquivo_sha256=sha,
        paginas=paginas_pdf(pdf),
        prompt_versao=esquema.versao_prompt(),
        esquema_versao=esquema.versao_esquema(),
        leitor_versao=__version__,
        regras_versao=versao_regras(),
    )
    decisao_cache = None
    if json_manual is not None:
        erro = falta_campo(json_manual, esquema.ESQUEMA)
        if erro:
            raise ValueError(f"leitura manual fora do esquema: {erro}")
        dados_brutos, info = json_manual, dict(modelo_pedido="humano", modelo="humano")
    else:
        leitor = leitor or LeitorClaude()
        if not forcar_releitura:
            existente, decisao_cache = cache.consultar(
                armazem,
                arquivo_sha256=sha,
                modelo=leitor.modelo,
                esforco=leitor.esforco,
                prompt_versao=base["prompt_versao"],
                esquema_versao=base["esquema_versao"],
                leitor_versao=base["leitor_versao"],
                caminho=calibracao_cache,
                hoje=hoje,
            )
            if existente:
                # O cache guarda a extração. Derivação e conferência usam a data,
                # as regras e o motor de agora, inclusive para outro CAR.
                der = derivar(existente.dados, hoje=hoje)
                confs = _conferir_e_gravar(armazem, existente, existente.dados, der, cod_imovel, cod_municipio, hoje)
                return ResultadoCertidao(existente, der, confs, decisao_cache)
        else:
            decisao_cache = dict(reutilizada=False, motivo="releitura forçada", leitura_id=None)
            armazem.gravar_cache_decisao(sha, decisao_cache)
        log.info("lendo certidão: %d bytes, %s páginas, modelo %s", len(pdf), base["paginas"], leitor.modelo)
        r = leitor.ler_pdf(pdf, esquema.SISTEMA, esquema.PEDIDO, esquema.ESQUEMA)
        info = dict(
            modelo_pedido=leitor.modelo,
            modelo=r.modelo,
            esforco=leitor.esforco,
            duracao_ms=r.duracao_ms,
            tokens_entrada=r.uso.entrada,
            tokens_saida=r.uso.saida,
            tokens_cache_leitura=r.uso.cache_leitura,
            tokens_cache_escrita=r.uso.cache_escrita,
            custo_usd=r.custo_usd,
        )
        if not r.ok:
            lt = Leitura(chave=f"sha:{sha[:16]}", dados={}, erro=r.erro, **base, **info)
            armazem.gravar_leitura(lt)
            return ResultadoCertidao(lt, cache=decisao_cache)
        dados_brutos = r.dados

    dados = sanear(dados_brutos)
    der = derivar(dados, hoje=hoje)
    qualidade = dict(
        escore_confianca=cache.escore(dados),
        escore_versao=cache.VERSAO_ESCORE,
        receita_hash=proveniencia.receita_hash(),
        origem_leitura=(
            "manual"
            if json_manual is not None
            else "simulada"
            if getattr(leitor._cliente, "simulado", False)
            else "api"
        ),
    )
    lt = Leitura(
        chave=chave_certidao(dados),
        dados=dados,
        derivados={**der.para_dict(), **qualidade},
        situacao_documento=der.situacao_documento,
        confianca=dados.get("confianca"),
        **base,
        **info,
    )
    armazem.gravar_leitura(lt)
    confs = _conferir_e_gravar(armazem, lt, dados, der, cod_imovel, cod_municipio, hoje)
    return ResultadoCertidao(lt, der, confs, decisao_cache)


def _conferir_e_gravar(armazem, lt, dados, der, cod_imovel, cod_municipio, hoje) -> list[Conferencia]:
    motor, imoveis, arquivo = _motor(dados, cod_imovel, cod_municipio)
    confs = conferir(dados, der, motor, cod_imovel=cod_imovel, imoveis=imoveis, motor_arquivo=arquivo, hoje=hoje)
    rv = versao_regras()
    for c in confs:
        armazem.gravar_conferencia(
            lt.id,
            c.situacao,
            c.motivos_dict(),
            rv,
            cod_imovel=c.cod_imovel,
            registro_cns=c.registro_cns,
            registro_matricula=c.registro_matricula,
            precisa_confirmar=c.precisa_confirmar,
            motor_arquivo=arquivo,
            motor_ha_sobre_car=c.motor_ha_sobre_car,
        )
    return confs


def reconferir(
    leitura_id: int,
    *,
    cod_imovel: str | None = None,
    cod_municipio: int | None = None,
    armazem: Armazem | None = None,
    hoje: dt.date | None = None,
) -> ResultadoCertidao:
    """Refaz regras e conferência sobre uma leitura já gravada (motor novo ou regra nova), sem chamar o modelo."""
    armazem = armazem or Armazem()
    lt = armazem.leitura(leitura_id)
    if lt is None or lt.tipo != "certidao":
        raise ValueError(f"leitura de certidão {leitura_id} não existe")
    if lt.erro:
        return ResultadoCertidao(lt)
    if cod_imovel is None and cod_municipio is None:  # o município da conferência anterior
        antes = [c for c in armazem.conferencias_por_leitura(leitura_id) if c["cod_imovel"]]
        if antes:
            cod_municipio = municipio_do_imovel(antes[-1]["cod_imovel"])
    der = derivar(lt.dados, hoje=hoje)
    return ResultadoCertidao(lt, der, _conferir_e_gravar(armazem, lt, lt.dados, der, cod_imovel, cod_municipio, hoje))
