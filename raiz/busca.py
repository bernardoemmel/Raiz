"""Busca nacional (código do CAR e nome de município) e manutenção das tabelas que ela usa.

O código do CAR aparece de vários jeitos (PA-1504950-00162AB1E0B34E339E65946061393F10, com pontos a cada quatro
letras na tela do SICAR, em minúsculas): a busca compara só letras e números, em maiúsculas. O nome do município é
comparado sem acento e em minúsculas.
"""

from __future__ import annotations

import re
import secrets
import unicodedata

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import Connection, Engine, text

from raiz.terra import CAMINHOS, RISCOS

_NAO_ALNUM = re.compile(r"[^0-9A-Za-z]")


def normalizar_codigo(cod: str) -> str:
    """Mesma regra do banco (migração 0013): só letras e números, em maiúsculas."""
    return _NAO_ALNUM.sub("", cod or "").upper()


def normalizar_nome(nome: str) -> str:
    s = unicodedata.normalize("NFKD", nome or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip().lower()


def parece_codigo(q: str) -> bool:
    """UF + dígitos (PA15...), ou só dígitos do município em diante: busca por código, não por nome."""
    n = normalizar_codigo(q)
    return len(n) >= 3 and (bool(re.match(r"^[A-Z]{2}\d", n)) or n.isdigit())


def atualizar_vigente(con: Connection, cod_municipio: int) -> int:
    """Aponta os imóveis do município para a rodada vigente dele (data de corte mais nova; empate, a última
    carregada). Imóvel que não está nessa rodada sai. Devolve quantos imóveis o município tem agora."""
    rid = con.execute(
        text("""select id from funil.rodada where tipo = 'municipio' and cod_municipio = :m
                order by data_corte desc, id desc limit 1"""),
        {"m": cod_municipio},
    ).scalar()
    if rid is None:
        return 0
    con.execute(
        text("delete from funil.vigente where cod_municipio_ibge = :m and rodada_id <> :r"),
        {"m": cod_municipio, "r": rid},
    )
    con.execute(
        text("""
        insert into funil.vigente (cod_imovel, rodada_id, cod_municipio_ibge, uf, cod_busca)
        select r.cod_imovel, r.rodada_id, ro.cod_municipio, ro.uf,
               upper(regexp_replace(r.cod_imovel, '[^0-9A-Za-z]', '', 'g'))
        from funil.resultado_imovel r join funil.rodada ro on ro.id = r.rodada_id
        where r.rodada_id = :r
        on conflict (cod_imovel) do update
        set rodada_id = excluded.rodada_id, cod_municipio_ibge = excluded.cod_municipio_ibge, uf = excluded.uf,
            cod_busca = excluded.cod_busca, atualizado_em = now()
        where funil.vigente.rodada_id is distinct from excluded.rodada_id"""),
        {"r": rid},
    )
    garantir_codigos(con, cod_municipio)
    n, nome, uf = con.execute(
        text("""select count(*), max(r.municipio), max(v.uf) from funil.vigente v
                join funil.resultado_imovel r on r.rodada_id = v.rodada_id and r.cod_imovel = v.cod_imovel
                where v.cod_municipio_ibge = :m"""),
        {"m": cod_municipio},
    ).one()
    if nome:
        _municipio(con, cod_municipio, nome, uf, n, rid)
    return n


def _municipio(con: Connection, cod: int, nome: str, uf: str | None, imoveis: int | None, rid: int | None) -> None:
    con.execute(
        text("""
        insert into funil.municipio_busca (cod_ibge, municipio, uf, nome_busca, imoveis, rodada_id)
        values (:c, :n, :u, :b, coalesce(:i, 0), :r)
        on conflict (cod_ibge) do update
        set municipio = excluded.municipio, uf = coalesce(excluded.uf, funil.municipio_busca.uf),
            nome_busca = excluded.nome_busca,
            imoveis = case when :i is null then funil.municipio_busca.imoveis else excluded.imoveis end,
            rodada_id = coalesce(excluded.rodada_id, funil.municipio_busca.rodada_id), atualizado_em = now()"""),
        {"c": cod, "n": nome, "u": uf, "b": normalizar_nome(nome), "i": imoveis, "r": rid},
    )


def municipios_do_resumo(con: Connection, rodada_resumo: int) -> int:
    """Todo município do resumo da UF entra na busca por nome, mesmo antes de ter imóveis carregados."""
    linhas = con.execute(
        text("""select m.cod_ibge, m.municipio, ro.uf, m.imoveis from funil.resumo_municipio m
                join funil.rodada ro on ro.id = m.rodada_id where m.rodada_id = :r and m.municipio is not null"""),
        {"r": rodada_resumo},
    ).all()
    for cod, nome, uf, n in linhas:
        _municipio(con, int(cod), nome, uf, None, None)
        con.execute(
            text("update funil.municipio_busca set imoveis_resumo = :n where cod_ibge = :c"),
            {"n": None if n is None else int(n), "c": int(cod)},
        )
    return len(linhas)


ALFABETO = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford: sem I, L, O e U (não confunde na leitura)
TAMANHO_CODIGO = 7


def novo_codigo() -> str:
    return "".join(secrets.choice(ALFABETO) for _ in range(TAMANHO_CODIGO))


def garantir_codigos(con: Connection, cod_municipio: int) -> int:
    """Dá um código curto sorteado (sem relação com o CAR) a cada imóvel vigente do município que ainda não tem.
    O código fica para sempre com o imóvel. Devolve quantos códigos novos."""
    novos = 0
    for _ in range(5):  # sorteio repetido só se bater com um código já usado (32^7 = 34 bilhões)
        faltam = [
            c
            for (c,) in con.execute(
                text("""select v.cod_imovel from funil.vigente v
                        left join negocio.codigo_curto k on k.cod_imovel = v.cod_imovel
                        where v.cod_municipio_ibge = :m and k.cod_imovel is null"""),
                {"m": cod_municipio},
            )
        ]
        if not faltam:
            break
        r = con.execute(
            text("""insert into negocio.codigo_curto (cod_imovel, codigo)
                    select * from unnest(cast(:c as text[]), cast(:k as text[])) on conflict do nothing"""),
            {"c": faltam, "k": [novo_codigo() for _ in faltam]},
        )
        novos += r.rowcount or 0
    return novos


# --- Prospecção nacional: todas as fazendas vigentes, inclusive pequenas e sem estimativa --------------------

UFS = frozenset("AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split())
BIOMAS = {normalizar_nome(b): b for b in ("Amazônia", "Caatinga", "Cerrado", "Mata Atlântica", "Pampa", "Pantanal")}
SITUACOES_TERRA = ("pronta_agora", "em_espera", "so_mostrar", "sem_dados")
UNIDADE_CREDITO = "tCO2e líquidos no contrato"
FONTE_PROSPECCAO = "SICAR e cálculos da Raíz da rodada vigente (terra e restauração)"
CRITERIO_AGRUPAMENTO = "Até 4 módulos fiscais ou assentamento no mesmo município e bioma; vizinhança a conferir."


class FiltrosProspeccao(BaseModel):
    """Filtros explícitos; não há área mínima, corte de elegibilidade ou risco implícitos.

    Crédito é o total líquido do contrato da E3, não a captura bruta anual. Campo
    ausente não vira zero e não satisfaz filtro numérico. UF e bioma têm catálogo
    fechado; texto e intervalos têm limites para impedir consulta arbitrária.
    """

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, str_strip_whitespace=True)
    q: str | None = Field(default=None, max_length=120)
    uf: str | None = None
    cod_ibge: int | None = Field(default=None, ge=1000000, le=9999999)
    bioma: str | None = None
    area_min_ha: float | None = Field(default=None, ge=0, le=1e12)
    area_max_ha: float | None = Field(default=None, ge=0, le=1e12)
    caminho_terra: str | None = None
    situacao_terra: str | None = None
    credito_min: float | None = Field(default=None, ge=0, le=1e15)
    credito_max: float | None = Field(default=None, ge=0, le=1e15)
    risco: str | None = None

    @field_validator("q", "uf", "bioma", "caminho_terra", "situacao_terra", "risco", mode="before")
    @classmethod
    def vazio_nulo(cls, valor):
        return None if isinstance(valor, str) and not valor.strip() else valor

    @field_validator("q")
    @classmethod
    def tamanho_busca(cls, valor):
        if valor is not None and len(normalizar_codigo(valor)) < 3:
            raise ValueError("Digite ao menos três letras ou números para buscar.")
        return valor

    @field_validator("uf")
    @classmethod
    def uf_valida(cls, valor):
        if valor is not None and valor.upper() not in UFS:
            raise ValueError("Estado inválido.")
        return valor.upper() if valor else None

    @field_validator("bioma")
    @classmethod
    def bioma_valido(cls, valor):
        if valor is not None and normalizar_nome(valor) not in BIOMAS:
            raise ValueError("Bioma inválido.")
        return BIOMAS[normalizar_nome(valor)] if valor else None

    @field_validator("caminho_terra", "situacao_terra", "risco")
    @classmethod
    def categoria_valida(cls, valor, info):
        permitidos = {
            "caminho_terra": (*CAMINHOS, "sem_dados"),
            "situacao_terra": SITUACOES_TERRA,
            "risco": (*RISCOS, "sem_dados"),
        }
        if valor is not None and valor not in permitidos[info.field_name]:
            raise ValueError("Categoria de terra ou risco inválida.")
        return valor

    @model_validator(mode="after")
    def intervalos_validos(self):
        for menor, maior in ((self.area_min_ha, self.area_max_ha), (self.credito_min, self.credito_max)):
            if menor is not None and maior is not None and menor > maior:
                raise ValueError("O mínimo não pode superar o máximo.")
        return self


def _numero_json(coluna: str) -> str:
    """Expressão interna (nunca entrada do cliente), tolerante a coluna nova malformada.

    O contrato permite valores numéricos em texto. O limite de algarismos/expoente
    impede overflow ao converter; NaN, infinito, bool e objetos ficam sem dado.
    """
    return (
        f"case when a ->> '{coluna}' ~ '^[+]?[0-9]{{1,25}}([.][0-9]{{1,25}})?([eE][+-]?[0-9]{{1,2}})?$' "
        f"then cast(a ->> '{coluna}' as double precision) end"
    )


def _texto_normalizado_sql(coluna: str) -> str:
    return f"translate(lower(trim({coluna})), 'áàâãäéèêëíìîïóòôõöúùûüç', 'aaaaaeeeeiiiiooooouuuuc')"


def _consulta_prospeccao(filtros: FiltrosProspeccao, cliente_id: int | None) -> tuple[str, dict]:
    """Consulta só da rodada vigente; seleção ocorre no Postgres, antes de paginar."""
    par: dict = {"cliente_id": cliente_id}
    iniciais = [
        "not exists (select 1 from negocio.reserva_fazenda rf join negocio.reserva rs on rs.id = rf.reserva_id "
        "where rf.cod_imovel = v.cod_imovel and rf.ativa "
        "and rs.cliente_id <> coalesce(cast(:cliente_id as bigint), -1))"
    ]
    for nome, coluna in (("uf", "v.uf"), ("cod_ibge", "v.cod_municipio_ibge")):
        valor = getattr(filtros, nome)
        if valor is not None:
            iniciais.append(f"{coluna} = :{nome}")
            par[nome] = valor
    if filtros.q:
        if parece_codigo(filtros.q):
            iniciais.append("v.cod_busca like :q")
            par["q"] = normalizar_codigo(filtros.q) + "%"
            if filtros.q.isdigit() and len(filtros.q) == 7:
                iniciais[-1] = "v.cod_municipio_ibge = :q_municipio"
                par["q_municipio"] = int(filtros.q)
        else:
            # Percentual e sublinhado são texto literal; não ampliam a seleção.
            iniciais.append(f"{_texto_normalizado_sql('r.municipio')} like :q escape '!' ")
            par["q"] = "%" + normalizar_nome(filtros.q).replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%"
    finais = []
    for nome, coluna, operador in (
        ("area_min_ha", "area_ha", ">="),
        ("area_max_ha", "area_ha", "<="),
        ("credito_min", "credito_p50", ">="),
        ("credito_max", "credito_p50", "<="),
        ("caminho_terra", "caminho_terra", "="),
        ("situacao_terra", "situacao_terra", "="),
        ("risco", "risco", "="),
    ):
        valor = getattr(filtros, nome)
        if valor is not None:
            finais.append(f"{coluna} {operador} :{nome}")
            par[nome] = valor
    if filtros.bioma:
        iniciais.append(f"{_texto_normalizado_sql('r.bioma')} = :bioma")
        par["bioma"] = normalizar_nome(filtros.bioma)
    area = _numero_json("restauracao_area_ha")
    c10, c50, c90 = (_numero_json(f"credito_liquido_tco2_ha_contrato_{q}") for q in ("p10", "p50", "p90"))
    caminhos_sql = ",".join(f"'{c}'" for c in CAMINHOS)
    sql = f"""with origem as (
        select v.cod_imovel as codigo_car, v.uf, v.cod_municipio_ibge as cod_ibge,
               r.municipio, r.bioma, r.ha, r.m_fiscal, r.tipo_imovel, r.carbono_ha, ro.data_corte,
               coalesce(d.atributos, '{{}}'::jsonb) || coalesce(f.atributos, '{{}}'::jsonb)
                   || coalesce(t.atributos, '{{}}'::jsonb) || r.atributos as a
        from funil.vigente v
        join funil.resultado_imovel r on r.rodada_id = v.rodada_id and r.cod_imovel = v.cod_imovel
        join funil.rodada ro on ro.id = v.rodada_id
        left join funil.complemento_imovel d on d.rodada_id = v.rodada_id
             and d.cod_imovel = v.cod_imovel and d.tipo = 'desenvolvedor'
        left join funil.complemento_imovel f on f.rodada_id = v.rodada_id
             and f.cod_imovel = v.cod_imovel and f.tipo = 'ficha'
        left join funil.complemento_imovel t on t.rodada_id = v.rodada_id
             and t.cod_imovel = v.cod_imovel and t.tipo = 'terra'
        where {" and ".join(iniciais)}
    ), medidas as (
        select codigo_car, uf, cod_ibge, municipio, bioma, data_corte,
               case when ha >= 0 and ha < 'Infinity'::float8 then ha end as area_ha,
               coalesce({area}, case when carbono_ha >= 0 and carbono_ha < 'Infinity'::float8
                                    then carbono_ha end) as area_restauravel_ha,
               {area} * ({c10}) as credito_p10, {area} * ({c50}) as credito_p50,
               {area} * ({c90}) as credito_p90,
               case when a ->> 'caminho_terra' in ({caminhos_sql})
                    then a ->> 'caminho_terra' else 'sem_dados' end as caminho_terra,
               case when a ->> 'risco_terra' in ('baixo', 'medio', 'alto')
                    then a ->> 'risco_terra' else 'sem_dados' end as risco,
               coalesce(m_fiscal >= 0 and m_fiscal <= 4, a ->> 'porte' = 'pequeno', false) as pequena,
               upper(coalesce(tipo_imovel, '')) = 'AST' or a ->> 'caminho_terra' = 'assentamento' as assentamento
        from origem
    ), classificadas as (
        select *, case when caminho_terra in ('privada_matricula', 'publica_concessao') then 'pronta_agora'
                       when caminho_terra in ('posse_em_titulacao', 'assentamento') then 'em_espera'
                       when caminho_terra = 'sem_dados' then 'sem_dados' else 'so_mostrar' end as situacao_terra,
               pequena or coalesce(assentamento, false) as agrupar
        from medidas
    ), selecionadas as (select * from classificadas where {" and ".join(finais) or "true"})
    """
    return sql, par


def buscar_prospeccao(
    engine: Engine,
    filtros: FiltrosProspeccao | dict | None = None,
    cliente_id: int | None = None,
    *,
    pagina: int = 1,
    limite: int = 20,
    incluir_imoveis: bool = False,
) -> dict:
    """Agregado nacional aberto e, somente quando autorizado pelo chamador, resumo paginado.

    A API aplica sessão, cobrança e limite de requisições. Este leitor não revela
    atributos livres: todo campo da resposta está na lista explícita do SELECT.
    Totais e agrupamentos consideram toda a seleção, não só a página retornada.
    P10/P90 agregados são somas de quantis, não o intervalo simulado de um lote.
    """
    filtros = filtros if isinstance(filtros, FiltrosProspeccao) else FiltrosProspeccao.model_validate(filtros or {})
    if isinstance(pagina, bool) or isinstance(limite, bool) or not (1 <= pagina <= 200 and 1 <= limite <= 50):
        raise ValueError("Página deve estar entre 1 e 200 e limite entre 1 e 50.")
    if not isinstance(pagina, int) or not isinstance(limite, int):
        raise ValueError("Página e limite devem ser inteiros.")
    if incluir_imoveis and cliente_id is None:
        raise ValueError("A lista de fazendas exige um cliente autenticado.")
    if not incluir_imoveis:
        validar_agregado_publico(filtros)
    sql, par = _consulta_prospeccao(filtros, cliente_id)
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as con:
        totais = dict(
            con.execute(
                text(
                    sql
                    + """
            select count(*) as fazendas, sum(area_ha) as area_ha,
                   sum(area_restauravel_ha) as area_restauravel_ha,
                   sum(credito_p10) as credito_p10, sum(credito_p50) as credito_p50, sum(credito_p90) as credito_p90,
                   count(credito_p50) as com_credito, count(*) filter (where pequena) as pequenas,
                   count(area_ha) as n_area_ha, count(area_restauravel_ha) as n_area_restauravel_ha,
                   count(credito_p10) as n_credito_p10, count(credito_p50) as n_credito_p50,
                   count(credito_p90) as n_credito_p90,
                   min(data_corte) as data_corte_min, max(data_corte) as data_corte_max
            from selecionadas"""
                ),
                par,
            )
            .mappings()
            .one()
        )
        grupos = [
            dict(r)
            for r in con.execute(
                text(
                    sql
                    + """
            select uf, cod_ibge, municipio, bioma, count(*) as fazendas, sum(area_ha) as area_ha,
                   sum(credito_p50) as credito_p50, min(data_corte) as data_corte_min,
                   count(area_ha) as n_area_ha, count(credito_p50) as n_credito_p50,
                   max(data_corte) as data_corte_max, count(*) over () as total_agrupamentos
            from selecionadas where agrupar
            group by uf, cod_ibge, municipio, bioma having count(*) >= :minimo_grupo
            order by count(*) desc, uf, cod_ibge, bioma nulls last limit 100"""
                ),
                {**par, "minimo_grupo": 2 if incluir_imoveis else 5},
            ).mappings()
        ]
        imoveis = []
        if incluir_imoveis:
            imoveis = [
                dict(r)
                for r in con.execute(
                    text(
                        sql
                        + """
                select codigo_car, uf, cod_ibge, municipio, bioma, area_ha, area_restauravel_ha,
                       caminho_terra, situacao_terra, risco, pequena, agrupar,
                       credito_p10, credito_p50, credito_p90, data_corte
                from selecionadas order by credito_p50 desc nulls last, codigo_car
                limit :limite offset :inicio"""
                    ),
                    {**par, "limite": limite, "inicio": (pagina - 1) * limite},
                ).mappings()
            ]
    for dado in [totais, *grupos, *imoveis]:
        for chave in ("data_corte", "data_corte_min", "data_corte_max"):
            if dado.get(chave) is not None:
                dado[chave] = dado[chave].isoformat()
        dado["fonte"] = FONTE_PROSPECCAO
        dado["credito_unidade"] = UNIDADE_CREDITO
    n_grupos = grupos[0]["total_agrupamentos"] if grupos else 0
    for grupo in grupos:
        grupo.pop("total_agrupamentos", None)
        grupo["criterio"] = CRITERIO_AGRUPAMENTO
    total = totais["fazendas"]
    for resumo in [totais, *grupos]:
        for campo in ("area_ha", "area_restauravel_ha", "credito_p10", "credito_p50", "credito_p90"):
            n = resumo.pop(f"n_{campo}", None)
            if not incluir_imoveis and n is not None and n < 5:
                resumo[campo] = None
        if not incluir_imoveis:
            for campo in ("fazendas", "pequenas", "com_credito"):
                if 0 < (resumo.get(campo) or 0) < 5:
                    resumo[campo] = None
    resposta = {
        "filtros": filtros.model_dump(exclude_none=True, exclude=set() if incluir_imoveis else {"q"}),
        "pagina": pagina,
        "limite": limite,
        "total": totais["fazendas"],
        "contagem": "menos de 5" if totais["fazendas"] is None else str(total),
        "tem_mais": incluir_imoveis and pagina < 200 and pagina * limite < total,
        "totais": totais,
        "agrupamentos": grupos,
        "total_agrupamentos": n_grupos,
        "agrupamentos_limitados": n_grupos > len(grupos),
        "credito_unidade": UNIDADE_CREDITO,
        "aviso": "Cobertura restrita às fazendas já processadas, de qualquer estado. Datas são cortes da rodada, "
        "não datas de observação de cada fonte. Crédito e área restaurável são estimativas; ausências "
        "não viram zero. P10/P90 somados não são uma simulação conjunta de lote. "
        "Agrupamento sugere análise conjunta; vizinhança ainda precisa ser conferida. "
        "Filtros de terra usam a classificação já processada. No agregado aberto, valores com menos de cinco "
        "fazendas são omitidos para proteger a ficha individual.",
    }
    if incluir_imoveis:
        resposta["imoveis"] = imoveis
    return resposta


def validar_agregado_publico(filtros: FiltrosProspeccao) -> None:
    """Evita transformar a soma pública em consulta de uma fazenda conhecida.

    Dimensões geográficas e categorias são abertas. Intervalos livres e código
    individual ficam na busca autenticada, junto do limite contra raspagem.
    """
    if filtros.q and parece_codigo(filtros.q):
        raise ValueError("Busca por CAR exige entrada na conta. No agregado, selecione o município.")
    if any(getattr(filtros, k) is not None for k in ("area_min_ha", "area_max_ha", "credito_min", "credito_max")):
        raise ValueError("Filtros por tamanho e crédito exigem entrada na conta.")
