"""Previsões congeladas e gabarito (E8 passo 1): sem isso a Raíz não aprende com o que já roda.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-12
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE aprendizado.lote_previsao (
        lote_hash text PRIMARY KEY,
        tipo text NOT NULL CHECK (tipo IN ('ao_vivo', 'backtest')),
        modelo text NOT NULL,
        modelo_versao text NOT NULL,
        entradas_versao text NOT NULL,
        regras_versao text,
        data_corte date NOT NULL,
        rodada_id bigint,
        n_previsoes integer NOT NULL,
        descricao text,
        criado_em timestamptz NOT NULL DEFAULT now()
    )""")
    op.execute(
        "COMMENT ON TABLE aprendizado.lote_previsao IS "
        "'um lote = previsões congeladas juntas; lote_hash é o sha256 das linhas (confere integridade)'"
    )

    # rodada_id sem chave estrangeira de propósito: a previsão sobrevive à rodada que a gerou
    op.execute("""
    CREATE TABLE aprendizado.previsao (
        id bigserial PRIMARY KEY,
        lote_hash text NOT NULL REFERENCES aprendizado.lote_previsao(lote_hash),
        tipo text NOT NULL DEFAULT 'ao_vivo' CHECK (tipo IN ('ao_vivo', 'backtest')),
        cod_imovel text NOT NULL,
        alvo text NOT NULL,
        valor_num double precision,
        valor_texto text,
        p10 double precision,
        p50 double precision,
        p90 double precision,
        distribuicao jsonb,
        data_corte date NOT NULL,
        horizonte_dias integer NOT NULL CHECK (horizonte_dias > 0),
        horizonte_em date GENERATED ALWAYS AS (data_corte + horizonte_dias) STORED,
        modelo text NOT NULL,
        modelo_versao text NOT NULL,
        entradas_versao text NOT NULL,
        regras_versao text,
        receita_hash text,
        rodada_id bigint,
        criada_em timestamptz NOT NULL DEFAULT now(),
        CHECK (valor_num IS NOT NULL OR valor_texto IS NOT NULL OR p50 IS NOT NULL),
        CHECK (p10 IS NULL OR p90 IS NULL OR p10 <= p90),
        UNIQUE (cod_imovel, alvo, modelo_versao, entradas_versao, data_corte, horizonte_dias, tipo)
    )""")
    op.execute("CREATE INDEX previsao_imovel_alvo_idx ON aprendizado.previsao (cod_imovel, alvo)")
    op.execute("CREATE INDEX previsao_lote_idx ON aprendizado.previsao (lote_hash)")
    op.execute("CREATE INDEX previsao_horizonte_idx ON aprendizado.previsao (horizonte_em)")

    op.execute("""
    CREATE TABLE aprendizado.gabarito (
        id bigserial PRIMARY KEY,
        cod_imovel text NOT NULL,
        alvo text NOT NULL,
        valor_num double precision,
        valor_texto text,
        observado_em date NOT NULL,
        fonte text NOT NULL,
        referencia text,
        registrado_em timestamptz NOT NULL DEFAULT now(),
        CHECK (valor_num IS NOT NULL OR valor_texto IS NOT NULL)
    )""")
    op.execute("CREATE INDEX gabarito_imovel_alvo_idx ON aprendizado.gabarito (cod_imovel, alvo, observado_em)")
    op.execute(
        "COMMENT ON COLUMN aprendizado.gabarito.referencia IS 'documento ou consulta de origem; nunca dado pessoal'"
    )

    # congelado: previsão, lote e gabarito só recebem linhas novas (correção = gabarito novo, registrado depois)
    op.execute("""
    CREATE FUNCTION aprendizado.congelado() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        RAISE EXCEPTION 'aprendizado.% é congelada: só aceita linhas novas (operação %)', TG_TABLE_NAME, TG_OP;
    END $$""")
    for t in ("previsao", "lote_previsao", "gabarito"):
        op.execute(f"""CREATE TRIGGER {t}_congelada BEFORE UPDATE OR DELETE ON aprendizado.{t}
                       FOR EACH ROW EXECUTE FUNCTION aprendizado.congelado()""")
        op.execute(f"""CREATE TRIGGER {t}_sem_truncate BEFORE TRUNCATE ON aprendizado.{t}
                       FOR EACH STATEMENT EXECUTE FUNCTION aprendizado.congelado()""")

    # tabela única previsão contra gabarito: para cada previsão, o gabarito observado DEPOIS da data de corte
    # mais perto do horizonte (empate: o mais novo; correção: o registrado por último)
    op.execute("""
    CREATE VIEW aprendizado.previsao_contra_gabarito AS
    SELECT p.id AS previsao_id, p.lote_hash, p.tipo, p.cod_imovel, p.alvo, p.modelo, p.modelo_versao,
           p.entradas_versao, p.regras_versao, p.data_corte, p.horizonte_dias, p.horizonte_em,
           p.valor_num, p.valor_texto, p.p10, p.p50, p.p90,
           g.id AS gabarito_id, g.valor_num AS real_num, g.valor_texto AS real_texto, g.observado_em,
           g.fonte AS gabarito_fonte,
           current_date >= p.horizonte_em AS maturou,
           g.valor_num - coalesce(p.valor_num, p.p50) AS erro,
           abs(g.valor_num - coalesce(p.valor_num, p.p50)) AS erro_abs,
           CASE WHEN p.valor_texto IS NOT NULL AND g.valor_texto IS NOT NULL
                THEN p.valor_texto = g.valor_texto END AS acertou,
           CASE WHEN p.p10 IS NOT NULL AND p.p90 IS NOT NULL AND g.valor_num IS NOT NULL
                THEN g.valor_num BETWEEN p.p10 AND p.p90 END AS dentro_p10_p90
    FROM aprendizado.previsao p
    LEFT JOIN LATERAL (
        SELECT * FROM aprendizado.gabarito g
        WHERE g.cod_imovel = p.cod_imovel AND g.alvo = p.alvo AND g.observado_em > p.data_corte
        ORDER BY abs(g.observado_em - p.horizonte_em), g.observado_em DESC, g.registrado_em DESC
        LIMIT 1
    ) g ON true""")


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS aprendizado.previsao_contra_gabarito")
    op.execute("DROP TABLE IF EXISTS aprendizado.gabarito, aprendizado.previsao, aprendizado.lote_previsao")
    op.execute("DROP FUNCTION IF EXISTS aprendizado.congelado()")
