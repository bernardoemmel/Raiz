"""Rastreio de exportações e indícios auditáveis de varredura, sem mensagens externas.

O código de rastreio é HMAC por cliente e versão; não contém ID, nome, documento,
contato, token ou segredo. Os eventos usam apenas códigos do CAR e metadados
fechados. Um alerta é um indício para o operador, nunca uma acusação ou bloqueio.
"""

from __future__ import annotations

import contextlib
import contextvars
import csv
import datetime as dt
import hashlib
import hmac
import io
import json
import logging
import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Engine, text

from raiz.prospeccao_acesso import ErroAcesso

SENTINELA = "Sentinela de rastreio Raíz: identifica a licença desta cópia; não é fazenda nem dado da terra."
_VERSAO = r"[a-zA-Z0-9][a-zA-Z0-9_.]{0,23}"
_MARCA = re.compile(rf"RZP-({_VERSAO})-([a-f0-9]{{32}})")
_CAR = re.compile(r"[A-Z]{2}-\d{7}-[A-F0-9]{32}")
_ACOES = frozenset(
    (
        "ficha",
        "busca",
        "comparacao",
        "exportacao_pdf",
        "exportacao_json",
        "exportacao_csv",
        "visual",
        "historico",
        "pasta",
        "exportacao_pasta",
    )
)
_CANAIS = frozenset(("site", "api", "mcp", "interno"))
_ATIVA = contextvars.ContextVar("prospeccao_operacao_vigiada", default=None)
_LOG = logging.getLogger(__name__)
_REGRAS = Path(__file__).with_name("regras") / "padroes" / "protecao_dados.yaml"


@dataclass(frozen=True)
class MarcaExportacao:
    codigo: str
    versao: str

    def metadados(self) -> dict:
        validar_marca(self)
        return {"marca": self.codigo, "versao": self.versao, "sentinela": SENTINELA}


def validar_marca(marca: MarcaExportacao) -> None:
    if not isinstance(marca, MarcaExportacao):
        raise ErroAcesso(503, "A exportação exige uma marca de rastreio configurada no servidor.")
    match = _MARCA.fullmatch(marca.codigo) if isinstance(marca.codigo, str) else None
    if match is None or match.group(1) != marca.versao:
        raise ErroAcesso(503, "A marca de exportação não é válida.")


def _chave(versao: str | None = None) -> tuple[str, bytes]:
    try:
        escolhido = versao if versao is not None else os.environ.get("RAIZ_PROTECAO_VERSAO", "")
        chaves = json.loads(os.environ.get("RAIZ_PROTECAO_CHAVES", "{}"))
        if not re.fullmatch(_VERSAO, escolhido) or not isinstance(chaves, dict) or len(chaves) > 20:
            raise ValueError
        segredo = chaves[escolhido]
        if not isinstance(segredo, str) or not 32 <= len(segredo.encode()) <= 4096:
            raise ValueError
        return escolhido, segredo.encode()
    except (ValueError, TypeError, KeyError):
        raise ErroAcesso(503, "A exportação ainda não tem a chave de rastreio configurada no servidor.") from None


def marca_cliente(cliente_id: int, *, versao: str | None = None) -> MarcaExportacao:
    if type(cliente_id) is not int or not 0 < cliente_id < 2**63:
        raise ErroAcesso(503, "A exportação exige uma conta autenticada.")
    versao, chave = _chave(versao)
    digest = hmac.new(chave, f"raiz:exportacao:v1:{versao}:{cliente_id}".encode(), hashlib.sha256).hexdigest()[:32]
    return MarcaExportacao(f"RZP-{versao}-{digest}", versao)


def registrar_marca(engine: Engine, cliente_id: int) -> MarcaExportacao:
    """Guarda o vínculo privado; trocar segredo exige versão nova, preservando o histórico."""
    marca = marca_cliente(cliente_id)
    with engine.begin() as con:
        con.execute(
            text("""insert into negocio.prospeccao_marca_cliente (codigo, cliente_id, versao_chave)
                values (:m,:c,:v) on conflict (cliente_id,versao_chave) do nothing"""),
            {"m": marca.codigo, "c": cliente_id, "v": marca.versao},
        )
        anterior = con.execute(
            text("select codigo from negocio.prospeccao_marca_cliente where cliente_id=:c and versao_chave=:v"),
            {"c": cliente_id, "v": marca.versao},
        ).scalar_one()
        if not hmac.compare_digest(anterior, marca.codigo):
            raise ErroAcesso(503, "A chave de rastreio mudou sem nova versão; exportação interrompida.")
    return marca


def rastrear_marca(engine: Engine, codigo: str) -> dict | None:
    """Consulta interna do operador; o chamador deve exigir autorização operacional."""
    if not isinstance(codigo, str) or not _MARCA.fullmatch(codigo):
        return None
    with engine.connect() as con:
        row = (
            con.execute(
                text(
                    "select cliente_id, versao_chave, criada_em from negocio.prospeccao_marca_cliente where codigo=:m"
                ),
                {"m": codigo},
            )
            .mappings()
            .first()
        )
        return dict(row) if row else None


def gerar_json(ficha: dict, marca: MarcaExportacao) -> bytes:
    from raiz.prospeccao_contrato import projetar_ficha

    validar_marca(marca)
    return json.dumps(
        {"ficha": projetar_ficha(ficha), "protecao": marca.metadados()}, ensure_ascii=False, allow_nan=False
    ).encode()


def _celula(valor) -> str:
    if isinstance(valor, (int, float)) and not isinstance(valor, bool):
        return str(valor)  # Número negativo não é uma fórmula.
    texto = "" if valor is None else str(valor)
    # Aspas CSV não impedem fórmulas em planilhas. Também cobre prefixos com
    # espaços/controles; a aspa faz o conteúdo ser tratado como texto literal.
    if texto.lstrip().startswith(("=", "+", "-", "@")) or texto.startswith(("\t", "\r", "\n")):
        texto = "'" + texto
    return texto


def gerar_csv(ficha: dict, marca: MarcaExportacao) -> bytes:
    from raiz.prospeccao_contrato import projetar_ficha

    validar_marca(marca)
    saida = io.StringIO(newline="")
    escritor = csv.writer(saida, lineterminator="\r\n")
    escritor.writerow(("tipo_registro", "campo", "valor", "marca_rastreio"))
    escritor.writerow(("sentinela_rastreio", "aviso", SENTINELA, marca.codigo))

    def percorrer(valor, caminho=""):
        if isinstance(valor, dict):
            for chave, item in valor.items():
                percorrer(item, f"{caminho}.{chave}" if caminho else chave)
        elif isinstance(valor, list):
            for indice, item in enumerate(valor):
                percorrer(item, f"{caminho}[{indice}]")
        else:
            escritor.writerow(("dado_da_terra", _celula(caminho), _celula(valor), marca.codigo))

    percorrer(projetar_ficha(ficha))
    return saida.getvalue().encode("utf-8-sig")


class _Perfil(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    monitorar_sucessos: bool
    volume_min: int = Field(ge=2, le=1000000)
    diversidade_car_min: int = Field(ge=2, le=1000000)
    sequencia_car_min: int = Field(ge=2, le=512)
    paginas_consecutivas_min: int = Field(ge=2, le=512)
    falhas_min: int = Field(ge=2, le=1000000)
    taxa_falhas_min: float = Field(gt=0, le=1)


class _Regras(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    versao: str = Field(pattern=r"^[a-zA-Z0-9_.-]{1,50}$")
    janela_s: int = Field(ge=60, le=86400)
    deduplicacao_s: int = Field(ge=60, le=604800)
    retencao_eventos_dias: int = Field(ge=1, le=365)
    sequencia_max_eventos: int = Field(ge=2, le=512)
    padrao: _Perfil
    licenciada: _Perfil


def regras() -> dict:
    dados = Path(os.environ.get("RAIZ_PROTECAO_REGRAS") or _REGRAS).read_bytes()
    doc = _Regras.model_validate(yaml.safe_load(dados)).model_dump()
    doc["versao_completa"] = doc["versao"] + "+" + hashlib.sha256(dados).hexdigest()[:12]
    return doc


def _codigos(codigos) -> list[str]:
    resultado = []
    for codigo in codigos:
        if not isinstance(codigo, str):
            continue
        limpo = re.sub(r"[^A-Z0-9]", "", codigo.upper())
        canonico = f"{limpo[:2]}-{limpo[2:9]}-{limpo[9:]}"
        if _CAR.fullmatch(canonico) and canonico not in resultado:
            resultado.append(canonico)
        if len(resultado) == 200:
            break
    return resultado


def _sequencias(eventos: list[dict]) -> tuple[int, int]:
    """Runs de CAR crescente/decrescente e de páginas consecutivas da mesma consulta."""
    crescente = decrescente = maior_car = 0
    anterior = None
    paginas = {}
    maior_pagina = 0
    for evento in eventos:
        cars = evento["codigos_car"]
        if len(cars) == 1:
            atual = cars[0]
            crescente = crescente + 1 if anterior is not None and atual > anterior else 1
            decrescente = decrescente + 1 if anterior is not None and atual < anterior else 1
            maior_car = max(maior_car, crescente, decrescente)
            anterior = atual
        else:
            anterior, crescente, decrescente = None, 0, 0
        pagina, consulta = evento["pagina"], evento["consulta_hash"]
        if pagina is not None and consulta:
            chave = (evento["acao"], consulta)
            ultima, run = paginas.get(chave, (None, 0))
            run = run + 1 if ultima is not None and pagina == ultima + 1 else 1
            paginas[chave] = (pagina, run)
            maior_pagina = max(maior_pagina, run)
    return maior_car, maior_pagina


def _detectar(metricas, perfil):
    regras_atingidas = []
    if perfil["monitorar_sucessos"]:
        if (
            metricas["volume_observado"] >= perfil["volume_min"]
            and metricas["diversidade_car"] >= perfil["diversidade_car_min"]
        ):
            regras_atingidas.append(
                ("volume_e_diversidade", metricas["diversidade_car"], perfil["diversidade_car_min"])
            )
        if metricas["sequencia_car"] >= perfil["sequencia_car_min"]:
            regras_atingidas.append(("sequencia_car", metricas["sequencia_car"], perfil["sequencia_car_min"]))
        if metricas["paginas_consecutivas"] >= perfil["paginas_consecutivas_min"]:
            regras_atingidas.append(
                ("paginacao_sequencial", metricas["paginas_consecutivas"], perfil["paginas_consecutivas_min"])
            )
    if (
        metricas["falhas"] >= perfil["falhas_min"]
        and metricas["falhas"] / max(1, metricas["tentativas"]) >= perfil["taxa_falhas_min"]
        and (
            metricas["diversidade_car"] >= perfil["sequencia_car_min"]
            or metricas["paginas_consecutivas"] >= perfil["paginas_consecutivas_min"]
        )
    ):
        regras_atingidas.append(("varredura_recusada", metricas["falhas"], perfil["falhas_min"]))
    return regras_atingidas


def registrar_tentativa(
    engine: Engine,
    cliente_id: int,
    *,
    acao: str,
    canal: str = "site",
    status: int,
    codigos_car=(),
    pagina: int | None = None,
    consulta_hash: str | None = None,
    evento_id: str | uuid.UUID | None = None,
) -> dict:
    """ID gerado pelo servidor por operação; nunca usar idempotency-key enviada pelo consumidor."""
    if type(cliente_id) is not int or not 0 < cliente_id < 2**63:
        raise ValueError("O registro exige a conta autenticada.")
    if acao not in _ACOES or canal not in _CANAIS or type(status) is not int or not 100 <= status <= 599:
        raise ValueError("Metadados de operação fora do contrato de proteção.")
    if pagina is not None and (type(pagina) is not int or not 1 <= pagina <= 1000000):
        raise ValueError("Página fora do contrato de proteção.")
    if consulta_hash is not None and not re.fullmatch(r"[a-f0-9]{64}", consulta_hash):
        raise ValueError("O registro aceita somente o hash da consulta, nunca filtros ou texto livre.")
    evento = uuid.UUID(str(evento_id)) if evento_id is not None else uuid.uuid4()
    identidade = {
        "cliente_id": cliente_id,
        "acao": acao,
        "canal": canal,
        "codigos_car": _codigos(codigos_car),
        "pagina": pagina,
        "consulta_hash": consulta_hash,
    }
    config = regras()
    corrigido = False
    with engine.begin() as con:
        con.execute(
            text("select pg_advisory_xact_lock(hashtextextended(:chave,0))"), {"chave": f"protecao:{cliente_id}"}
        )
        criada = con.execute(
            text("""insert into negocio.prospeccao_evento_protecao
                (id,cliente_id,acao,canal,status,codigos_car,pagina,consulta_hash)
                values (:id,:c,:a,:via,:s,:cars,:p,:h) on conflict (id) do nothing returning id"""),
            {
                "id": evento,
                "c": cliente_id,
                "a": acao,
                "via": canal,
                "s": status,
                "cars": identidade["codigos_car"],
                "p": pagina,
                "h": consulta_hash,
            },
        ).scalar_one_or_none()
        if criada is None:
            anterior = (
                con.execute(
                    text("""select cliente_id,acao,canal,codigos_car,pagina,consulta_hash,status
                from negocio.prospeccao_evento_protecao where id=:id"""),
                    {"id": evento},
                )
                .mappings()
                .one()
            )
            if any(anterior[k] != v for k, v in identidade.items()):
                raise ValueError("O identificador da operação já pertence a outros metadados.")
            if anterior["status"] < 400 <= status:
                con.execute(
                    text("""update negocio.prospeccao_evento_protecao set status=:s
                    where id=:id and cliente_id=:c and status<400"""),
                    {"id": evento, "c": cliente_id, "s": status},
                )
                corrigido = True
            else:
                return {"evento_id": str(evento), "duplicado": True, "corrigido": False, "alertas": []}
        licenciada = bool(
            con.execute(
                text("select licenca_dados_aprovada_em is not null from negocio.conta_api where cliente_id=:c"),
                {"c": cliente_id},
            ).scalar()
        )
        perfil = config["licenciada" if licenciada else "padrao"]
        agora = con.execute(text("select now()")).scalar_one()
        desde = agora - dt.timedelta(seconds=config["janela_s"])
        parametros = {"c": cliente_id, "desde": desde, "sucessos": perfil["monitorar_sucessos"]}
        metricas = dict(
            con.execute(
                text("""with eventos as materialized (
                select status,codigos_car from negocio.prospeccao_evento_protecao
                where cliente_id=:c and criado_em>=:desde
            ) select count(*) as tentativas,
                count(*) filter (where status in (402,403,404,422,429)) as falhas,
                    count(*) filter (where (:sucessos and status<400)
                        or status in (402,403,404,422,429)) as volume_observado,
                (select count(distinct car) from eventos cross join lateral unnest(codigos_car) as car
                  where (:sucessos and status<400) or status in (402,403,404,422,429)) as diversidade_car
            from eventos"""),
                parametros,
            )
            .mappings()
            .one()
        )
        eventos = list(
            con.execute(
                text("""select codigos_car,pagina,consulta_hash,acao from negocio.prospeccao_evento_protecao
                where cliente_id=:c and criado_em>=:desde
                and ((:sucessos and status<400) or status in (402,403,404,422,429))
                order by criado_em desc,id desc limit :limite"""),
                {**parametros, "limite": config["sequencia_max_eventos"]},
            ).mappings()
        )
        metricas["sequencia_car"], metricas["paginas_consecutivas"] = _sequencias(list(reversed(eventos)))
        metricas["janela_s"] = config["janela_s"]
        metricas["licenciada"] = licenciada
        inicio = dt.datetime.fromtimestamp(
            int(agora.timestamp()) // config["deduplicacao_s"] * config["deduplicacao_s"], dt.UTC
        )
        detectadas = _detectar(metricas, perfil)
        if corrigido:
            # Conserva o alerta original como trilha auditável, atualizando a
            # evidência caso a falha final tenha invalidado o sinal preliminar.
            regras_ativas = [r for r, _, _ in detectadas]
            con.execute(
                text("""update negocio.prospeccao_alerta_protecao
                set metricas=cast(:m as jsonb) || jsonb_build_object(
                    'reavaliado_apos_falha',true,'criterio_atingido',regra=any(cast(:ativas as text[]))),
                    atualizado_em=:agora
                where cliente_id=:c and regras_versao=:v and janela_inicio=:j"""),
                {
                    "m": json.dumps(metricas),
                    "ativas": regras_ativas,
                    "agora": agora,
                    "c": cliente_id,
                    "v": config["versao_completa"],
                    "j": inicio,
                },
            )
        alertas = []
        for regra, valor, limite in detectadas:
            params = {
                "c": cliente_id,
                "r": regra,
                "v": config["versao_completa"],
                "j": inicio,
                "m": json.dumps({**metricas, "criterio_atingido": True, "reavaliado_apos_falha": corrigido}),
                "agora": agora,
            }
            existente = con.execute(
                text("""select id from negocio.prospeccao_alerta_protecao
                where cliente_id=:c and regra=:r and regras_versao=:v and janela_inicio=:j"""),
                params,
            ).scalar()
            if existente is None:
                publico_id = con.execute(
                    text("""insert into negocio.alerta_api
                    (cliente_id,tipo,regra,valor,limite)
                    values (:c,'raspagem_alerta',:r,:valor,:limite) returning id"""),
                    {"c": cliente_id, "r": "prospeccao:" + regra, "valor": valor, "limite": limite},
                ).scalar_one()
                alerta_id = con.execute(
                    text("""insert into negocio.prospeccao_alerta_protecao
                    (cliente_id,regra,regras_versao,janela_inicio,metricas,alerta_api_id)
                    values (:c,:r,:v,:j,cast(:m as jsonb),:alerta) returning id"""),
                    {**params, "alerta": publico_id},
                ).scalar_one()
                alertas.append({"id": alerta_id, "regra": regra})
            else:
                con.execute(
                    text("""update negocio.prospeccao_alerta_protecao set metricas=cast(:m as jsonb),
                    ocorrencias=ocorrencias+:incremento,atualizado_em=:agora where id=:id"""),
                    {**params, "id": existente, "incremento": 0 if corrigido else 1},
                )
    return {"evento_id": str(evento), "duplicado": False, "corrigido": corrigido, "alertas": alertas}


def limpar_eventos(engine: Engine) -> int:
    """Manutenção interna; mantém marcas e alertas auditados, remove somente eventos antigos."""
    dias = regras()["retencao_eventos_dias"]
    with engine.begin() as con:
        return con.execute(
            text("""delete from negocio.prospeccao_evento_protecao
            where criado_em < now() - make_interval(days => :dias)"""),
            {"dias": dias},
        ).rowcount


def fechar_alerta(registro: dict) -> dict:
    """Contrato interno fechado, compartilhado pelo CLI e pela lista da conta."""
    brutas = registro.get("metricas")
    brutas = brutas if isinstance(brutas, dict) else {}
    numeros = (
        "tentativas",
        "falhas",
        "volume_observado",
        "diversidade_car",
        "sequencia_car",
        "paginas_consecutivas",
        "janela_s",
    )
    metricas = {k: brutas[k] for k in numeros if type(brutas.get(k)) is int and brutas[k] >= 0}
    metricas.update(
        {
            k: brutas[k]
            for k in ("licenciada", "criterio_atingido", "reavaliado_apos_falha")
            if type(brutas.get(k)) is bool
        }
    )
    regra = registro.get("regra")
    permitidas = {"volume_e_diversidade", "sequencia_car", "paginacao_sequencial", "varredura_recusada"}
    versao = registro.get("regras_versao")
    saida = {
        "regra": regra if regra in permitidas else "regra_desconhecida",
        "regras_versao": versao
        if isinstance(versao, str) and re.fullmatch(r"[a-zA-Z0-9_.-]{1,50}\+[a-f0-9]{12}", versao)
        else None,
        "metricas": metricas,
        "criterio_atingido": metricas.get("criterio_atingido") is not False,
        "reavaliado_apos_falha": metricas.get("reavaliado_apos_falha") is True,
    }
    for chave in ("id", "cliente_id", "alerta_api_id", "ocorrencias"):
        valor = registro.get(chave)
        saida[chave] = valor if type(valor) is int and valor > 0 else None
    for chave in ("criado_em", "atualizado_em", "janela_inicio"):
        valor = registro.get(chave)
        try:
            data = dt.datetime.fromisoformat(valor) if isinstance(valor, str) else valor
            saida[chave] = data.isoformat() if isinstance(data, dt.datetime) else None
        except ValueError:
            saida[chave] = None
    return saida


def alertas(
    engine: Engine, *, limite: int = 100, apenas_ativos: bool = False, cliente_id: int | None = None
) -> list[dict]:
    """Somente operador autenticado/CLI; mantém também indícios invalidados no histórico."""
    if type(limite) is not int or not 1 <= limite <= 1000 or type(apenas_ativos) is not bool:
        raise ValueError("Filtro de alertas inválido.")
    if cliente_id is not None and (type(cliente_id) is not int or cliente_id < 1):
        raise ValueError("Conta inválida para consulta operacional.")
    filtros = []
    if cliente_id is not None:
        filtros.append("cliente_id=:c")
    if apenas_ativos:
        filtros.append("(metricas->'criterio_atingido') is distinct from 'false'::jsonb")
    where = "where " + " and ".join(filtros) if filtros else ""
    with engine.connect() as con:
        if con.execute(text("select to_regclass('negocio.prospeccao_alerta_protecao')")).scalar() is None:
            return []
        rows = con.execute(
            text(f"""select id,cliente_id,regra,regras_versao,janela_inicio,
            metricas,ocorrencias,alerta_api_id,criado_em,atualizado_em
            from negocio.prospeccao_alerta_protecao {where}
            order by atualizado_em desc,id desc limit :n"""),
            {"c": cliente_id, "n": limite},
        ).mappings()
        return [fechar_alerta(dict(row)) for row in rows]


def _cars_resultado(resultado) -> list[str]:
    if not isinstance(resultado, dict):
        return []
    cars = [resultado.get("codigo_car"), resultado.get("cod_imovel")]
    for chave in ("fichas", "imoveis"):
        for item in (resultado.get(chave) or [])[:200]:
            if isinstance(item, dict):
                cars.extend((item.get("codigo_car"), item.get("cod_imovel")))
    return _codigos(cars)


@contextlib.contextmanager
def operacao_vigiada(
    engine, cliente_id, *, acao, canal="site", codigos_car=(), pagina=None, consulta_hash=None, evento_id=None
):
    """Audita antes do commit da consulta quando concluir() é chamado dentro dela.

    Erro da auditoria numa resposta bem-sucedida propaga para permitir rollback.
    Ao tratar uma falha da operação, preserva a exceção original e registra somente
    o tipo do erro de auditoria. Contextos internos do mesmo cliente não duplicam.
    """
    if _ATIVA.get() == cliente_id:
        yield lambda resultado=None: None
        return
    token = _ATIVA.set(cliente_id)
    id_evento = evento_id or uuid.uuid4()
    concluida = False
    params = {
        "acao": acao,
        "canal": canal,
        "codigos_car": codigos_car,
        "pagina": pagina,
        "consulta_hash": consulta_hash,
        "evento_id": id_evento,
    }

    def concluir(resultado=None):
        nonlocal concluida
        if not concluida:
            params["codigos_car"] = _codigos([*codigos_car, *_cars_resultado(resultado)])
            try:
                registrar_tentativa(
                    engine,
                    cliente_id,
                    status=200,
                    **params,
                )
            except Exception as exc:
                _LOG.error("Registro de proteção indisponível (%s).", type(exc).__name__)
                raise ErroAcesso(503, "Não foi possível registrar a consulta. Tente novamente.") from None
            concluida = True

    try:
        yield concluir
        concluir()
    except Exception as exc:
        status = getattr(exc, "status", getattr(exc, "status_code", 500))
        status = status if type(status) is int and 400 <= status <= 599 else 500
        try:
            registrar_tentativa(engine, cliente_id, status=status, **params)
        except Exception as erro_auditoria:
            _LOG.error("Registro de proteção indisponível (%s).", type(erro_auditoria).__name__)
        raise
    finally:
        _ATIVA.reset(token)


def executar_vigiado(
    engine,
    cliente_id,
    funcao,
    *args,
    acao,
    canal="site",
    codigos_car=(),
    pagina=None,
    consulta_hash=None,
    evento_id=None,
    **kwargs,
):
    with operacao_vigiada(
        engine,
        cliente_id,
        acao=acao,
        canal=canal,
        codigos_car=codigos_car,
        pagina=pagina,
        consulta_hash=consulta_hash,
        evento_id=evento_id,
    ) as concluir:
        resultado = funcao(*args, **kwargs)
        concluir(resultado)
        return resultado
