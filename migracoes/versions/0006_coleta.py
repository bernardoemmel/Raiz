"""Coleta (E1 passo 1): fontes do manifesto, estado de replicação por recorte, checagens HTTP e eventos de mudança.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-12
"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE coleta.fonte (
        id text PRIMARY KEY,
        nome text NOT NULL,
        orgao text NOT NULL,
        tipo text NOT NULL,
        url text,
        recorte text NOT NULL,
        sinal jsonb NOT NULL,
        calendario jsonb NOT NULL,
        licenca text NOT NULL,
        pode_treinar boolean NOT NULL,
        pendente text,
        definicao jsonb NOT NULL,
        manifesto_versao text NOT NULL,
        manifesto_hash text NOT NULL,
        atualizado_em timestamptz NOT NULL DEFAULT now()
    )""")

    # Uma linha por fonte e recorte (ex.: sicar_imoveis + PA/1504950): o que já se sabe sem baixar de novo.
    op.execute("""
    CREATE TABLE coleta.replicacao (
        fonte text NOT NULL REFERENCES coleta.fonte(id),
        recorte text NOT NULL,
        cursor text,
        etag text,
        last_modified text,
        contagem bigint,
        assinatura text,
        hash_conteudo text,
        sujo boolean NOT NULL DEFAULT true,
        tentativas integer NOT NULL DEFAULT 0,
        ultimo_erro text,
        verificado_em timestamptz,
        coletado_em timestamptz,
        atualizado_em timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (fonte, recorte)
    )""")
    op.execute("CREATE INDEX replicacao_sujo_idx ON coleta.replicacao (fonte) WHERE sujo")
    op.execute(
        "COMMENT ON COLUMN coleta.replicacao.assinatura IS "
        "'assinatura barata (contagem + data mais nova, ETag...) tirada antes de baixar'"
    )

    op.execute("""
    CREATE TABLE coleta.checagem_http (
        id bigserial PRIMARY KEY,
        fonte text NOT NULL,
        url text NOT NULL,
        status integer,
        bytes bigint,
        etag text,
        last_modified text,
        mudou boolean,
        erro text,
        verificado_em timestamptz NOT NULL DEFAULT now()
    )""")
    op.execute("CREATE INDEX checagem_http_url_idx ON coleta.checagem_http (url, verificado_em DESC)")

    # O que mudou em cada coleta (base do 'diff da semana' e da fila de municípios sujos da E8)
    op.execute("""
    CREATE TABLE coleta.evento (
        id bigserial PRIMARY KEY,
        fonte text NOT NULL,
        recorte text NOT NULL,
        tipo text NOT NULL CHECK (tipo IN ('novos', 'mudaram', 'sumiram', 'sem_mudanca', 'falha', 'alerta')),
        quantidade integer,
        detalhe jsonb NOT NULL DEFAULT '{}',
        em timestamptz NOT NULL DEFAULT now()
    )""")
    op.execute("CREATE INDEX evento_fonte_idx ON coleta.evento (fonte, em DESC)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS coleta.evento, coleta.checagem_http, coleta.replicacao, coleta.fonte")
