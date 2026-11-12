"""Fundação: esquemas e tabelas do funil (resultado do motor por rodada).

Revision ID: 0001
Revises:
Create Date: 2026-11-12
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

ESQUEMAS = ["coleta", "bruto", "funil", "regras", "titulo", "negocio", "aprendizado", "pessoal", "operacao"]

SQL_TIPO = {"texto": "text", "num": "double precision", "int": "bigint", "bool": "boolean", "data_hora": "timestamptz"}

# Cópia congelada do contrato (raiz/contrato.py) em 12/11/2026. Coluna nova do motor NÃO precisa de migração:
# vai para `atributos`. Só vira coluna tipada numa migração nova, quando o produto passar a usar.
IMOVEIS = {
    "id": "texto", "status_imovel": "texto", "dat_criacao": "data_hora", "data_atualizacao": "data_hora",
    "area": "num", "condicao": "texto", "uf": "texto", "municipio": "texto", "cod_municipio_ibge": "int",
    "m_fiscal": "num", "tipo_imovel": "texto", "ha": "num", "desm_pos2008_ha": "num", "desm_pos2016_ha": "num",
    "desm_pos2020_ha": "num", "desm_total_ha": "num", "nao_floresta_ha": "num", "floresta_rem_ha": "num",
    "embargo_ha": "num", "ti_ha": "num", "uc_ha": "num", "sigef_ha": "num", "matricula_ha": "num",
    "assentamento_ha": "num", "f_matricula": "num", "projeto_carbono_ha": "num", "alerta_ha": "num",
    "alerta_pos2020_ha": "num", "alerta_ultimo_ano": "num", "app_desmatada_ha": "num", "app_escadinha_ha": "num",
    "app_recompor_ha": "num", "bioma": "texto", "pct_rl": "num", "pct_rl_alem": "num", "deficit_rl_ha": "num",
    "deficit_rl_alem_ha": "num", "deficit_rl80_ha": "num", "deficit_rl50_ha": "num", "alem_rl_ha": "num",
    "problema": "bool", "frente": "texto", "cota_reserva": "bool", "redd_excedente_ha": "num",
    "frigorifico_remocao_ha": "num", "compensacao_restauravel_ha": "num", "eudr_ok": "bool",
    "credito_rural_ok": "bool", "compra_arrendamento": "bool", "pasto_ha": "num", "secundaria_ha": "num",
    "pasto_ate1km_ha": "num", "carbono_ha": "num", "regiao_carbono": "texto", "taxa_tco2_ha_ano": "num",
    "carbono_tco2_ano": "num", "cacau_aptidao": "texto", "carbono_solo_ha": "num", "rebanho_cabecas": "num",
    "psa_elegivel": "bool", "biodiversidade_score": "num",
}  # fmt: skip
FILTROS = {
    "quilombo_ha": "num", "ti_funai_ha": "num", "ti_fase": "texto", "uc_protecao_integral_ha": "num",
    "uc_uso_sustentavel_ha": "num", "uc_apa_ha": "num", "filtro_territorial": "texto",
}  # fmt: skip
RESUMO = {
    "municipio": "texto", "imoveis": "num", "sem_problema": "num", "def_rl": "num", "aptas_carbono": "num",
    "ha_carbono": "num", "tco2_ano_aptas": "num", "aptas_com_matricula": "num", "ha_carbono_matricula": "num",
    "cota_reserva": "num", "redd_imoveis": "num", "redd_ha": "num", "app_imoveis": "num", "app_ha": "num",
    "frigorifico_imoveis": "num", "frigorifico_ha": "num", "compensacao_ha": "num", "eudr_ok": "num",
    "credito_rural_ok": "num", "compra_arrendamento": "num", "alerta_pos2020_imoveis": "num",
}  # fmt: skip


def _colunas(d: dict) -> str:
    return ",\n    ".join(f"{c} {SQL_TIPO[t]}" for c, t in d.items())


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    for e in ESQUEMAS:
        op.execute(f"CREATE SCHEMA IF NOT EXISTS {e}")
    op.execute(
        "COMMENT ON SCHEMA pessoal IS 'Dado pessoal cifrado (telefone, BSUID). Nunca em log, exportação ou treino.'"
    )

    op.execute("""
    CREATE TABLE funil.rodada (
        id bigserial PRIMARY KEY,
        tipo text NOT NULL CHECK (tipo IN ('municipio', 'resumo_uf')),
        uf text NOT NULL,
        cod_municipio integer,
        origem text NOT NULL,
        arquivos jsonb NOT NULL,
        hash_entradas text NOT NULL UNIQUE,
        motor_versao text NOT NULL,
        motor_versao_confirmada boolean NOT NULL DEFAULT false,
        motor_commit text,
        regras_versao text NOT NULL,
        data_corte date NOT NULL,
        colunas_novas text[] NOT NULL DEFAULT '{}',
        colunas_faltando text[] NOT NULL DEFAULT '{}',
        avisos text[] NOT NULL DEFAULT '{}',
        imoveis integer,
        carregada_em timestamptz NOT NULL DEFAULT now(),
        CHECK ((tipo = 'municipio') = (cod_municipio IS NOT NULL))
    )""")
    op.execute(
        "COMMENT ON COLUMN funil.rodada.motor_versao_confirmada IS "
        "'true só quando a própria Raíz rodou o motor; false quando carregou saída pronta'"
    )
    op.execute("COMMENT ON COLUMN funil.rodada.data_corte IS 'dados como estavam até esta data (nada depois dela)'")

    op.execute("""
    CREATE TABLE funil.imovel (
        cod_imovel text PRIMARY KEY,
        uf text,
        cod_municipio_ibge bigint,
        geom geometry(MultiPolygon, 4674),
        geom_hash text,
        atualizado_em timestamptz NOT NULL DEFAULT now()
    )""")
    op.execute("CREATE INDEX imovel_geom_idx ON funil.imovel USING gist (geom)")
    op.execute("CREATE INDEX imovel_municipio_idx ON funil.imovel (cod_municipio_ibge)")

    op.execute(f"""
    CREATE TABLE funil.resultado_imovel (
        rodada_id bigint NOT NULL REFERENCES funil.rodada(id) ON DELETE CASCADE,
        cod_imovel text NOT NULL,
        {_colunas(IMOVEIS)},
        atributos jsonb NOT NULL DEFAULT '{{}}',
        PRIMARY KEY (rodada_id, cod_imovel)
    )""")
    op.execute("CREATE INDEX resultado_imovel_cod_idx ON funil.resultado_imovel (cod_imovel)")
    op.execute("CREATE INDEX resultado_imovel_frente_idx ON funil.resultado_imovel (frente)")

    op.execute(f"""
    CREATE TABLE funil.filtro_imovel (
        rodada_id bigint NOT NULL REFERENCES funil.rodada(id) ON DELETE CASCADE,
        cod_imovel text NOT NULL,
        {_colunas(FILTROS)},
        atributos jsonb NOT NULL DEFAULT '{{}}',
        PRIMARY KEY (rodada_id, cod_imovel)
    )""")

    op.execute("""
    CREATE TABLE funil.complemento_imovel (
        rodada_id bigint NOT NULL REFERENCES funil.rodada(id) ON DELETE CASCADE,
        tipo text NOT NULL,
        cod_imovel text NOT NULL,
        atributos jsonb NOT NULL,
        PRIMARY KEY (rodada_id, tipo, cod_imovel)
    )""")

    op.execute(f"""
    CREATE TABLE funil.resumo_municipio (
        rodada_id bigint NOT NULL REFERENCES funil.rodada(id) ON DELETE CASCADE,
        cod_ibge bigint NOT NULL,
        {_colunas(RESUMO)},
        atributos jsonb NOT NULL DEFAULT '{{}}',
        PRIMARY KEY (rodada_id, cod_ibge)
    )""")

    op.execute("""
    CREATE TABLE titulo.certidao_alvo (
        rodada_id bigint NOT NULL REFERENCES funil.rodada(id) ON DELETE CASCADE,
        cod_imovel text NOT NULL,
        registro_cns text,
        registro_matricula text,
        ha_sobre_car double precision,
        parcelas double precision,
        atributos jsonb NOT NULL DEFAULT '{}'
    )""")
    op.execute("CREATE INDEX certidao_alvo_cod_idx ON titulo.certidao_alvo (cod_imovel)")
    op.execute(
        "COMMENT ON TABLE titulo.certidao_alvo IS "
        "'cartório (CNS) e matrícula das parcelas SIGEF sobre cada imóvel, para pedir certidão'"
    )

    # versão vigente: a rodada com a data de corte mais nova (empate: a carregada por último)
    op.execute("""
    CREATE VIEW funil.resultado_vigente AS
    SELECT DISTINCT ON (r.cod_imovel) r.*, ro.data_corte, ro.motor_versao, ro.regras_versao
    FROM funil.resultado_imovel r JOIN funil.rodada ro ON ro.id = r.rodada_id
    ORDER BY r.cod_imovel, ro.data_corte DESC, ro.id DESC""")


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS funil.resultado_vigente")
    for t in [
        "titulo.certidao_alvo",
        "funil.resumo_municipio",
        "funil.complemento_imovel",
        "funil.filtro_imovel",
        "funil.resultado_imovel",
        "funil.imovel",
        "funil.rodada",
    ]:
        op.execute(f"DROP TABLE IF EXISTS {t}")
    for e in reversed(ESQUEMAS):
        op.execute(f"DROP SCHEMA IF EXISTS {e} CASCADE")  # bruto e pessoal têm tabelas do dlt e do LangGraph
