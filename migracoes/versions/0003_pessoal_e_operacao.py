"""Esquema pessoal (telefone e BSUID do WhatsApp, cifrados) e operação dos modelos (chamadas, cascata, revisão).

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-12
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nada aqui é legível sem a chave (RAIZ_CHAVE_PESSOAL). A busca usa HMAC (não dá para voltar ao número).
    # O BSUID é o identificador do usuário por empresa do WhatsApp; quando o usuário adota nome de usuário,
    # o webhook pode vir sem telefone, só com o BSUID: por isso os dois ficam juntos.
    op.execute("""
    CREATE TABLE pessoal.contato (
        id bigserial PRIMARY KEY,
        bsuid_hmac text UNIQUE,
        bsuid_cifrado bytea,
        parent_bsuid_cifrado bytea,
        telefone_hmac text UNIQUE,
        telefone_cifrado bytea,
        username_cifrado bytea,
        pais text,
        origem text NOT NULL,
        consentimento_em timestamptz,
        criado_em timestamptz NOT NULL DEFAULT now(),
        atualizado_em timestamptz NOT NULL DEFAULT now(),
        CHECK (bsuid_hmac IS NOT NULL OR telefone_hmac IS NOT NULL),
        CHECK ((bsuid_hmac IS NULL) = (bsuid_cifrado IS NULL)),
        CHECK ((telefone_hmac IS NULL) = (telefone_cifrado IS NULL))
    )""")
    op.execute("""
    CREATE TABLE pessoal.contato_imovel (
        contato_id bigint NOT NULL REFERENCES pessoal.contato(id) ON DELETE CASCADE,
        cod_imovel text NOT NULL,
        papel text NOT NULL DEFAULT 'dono' CHECK (papel IN ('dono', 'representante', 'tecnico')),
        criado_em timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (contato_id, cod_imovel)
    )""")
    op.execute("CREATE INDEX contato_imovel_cod_idx ON pessoal.contato_imovel (cod_imovel)")
    op.execute("REVOKE ALL ON SCHEMA pessoal FROM PUBLIC")

    op.execute("""
    CREATE TABLE operacao.chamada_modelo (
        id bigserial PRIMARY KEY,
        tarefa text NOT NULL,
        cod_imovel text,
        cod_municipio bigint,
        provedor text NOT NULL,
        modelo text NOT NULL,
        papel text,
        tokens_entrada integer,
        tokens_saida integer,
        tokens_cache_leitura integer,
        tokens_cache_escrita integer,
        custo_usd numeric(14, 8),
        custo_fonte text,
        duracao_ms integer,
        ok boolean NOT NULL,
        erro text,
        rastro_id text,
        criado_em timestamptz NOT NULL DEFAULT now()
    )""")
    op.execute("CREATE INDEX chamada_modelo_imovel_idx ON operacao.chamada_modelo (cod_imovel)")
    op.execute("CREATE INDEX chamada_modelo_tarefa_idx ON operacao.chamada_modelo (tarefa, criado_em)")

    op.execute("""
    CREATE TABLE operacao.fila_revisao (
        id bigserial PRIMARY KEY,
        tarefa text NOT NULL,
        chave text,
        motivo text NOT NULL,
        conteudo jsonb NOT NULL,
        estado text NOT NULL DEFAULT 'aberta' CHECK (estado IN ('aberta', 'resolvida', 'descartada')),
        resposta jsonb,
        resolvida_por text,
        resolvida_em timestamptz,
        criado_em timestamptz NOT NULL DEFAULT now()
    )""")
    op.execute("CREATE INDEX fila_revisao_aberta_idx ON operacao.fila_revisao (tarefa) WHERE estado = 'aberta'")

    op.execute("""
    CREATE TABLE operacao.decisao_cascata (
        id bigserial PRIMARY KEY,
        tarefa text NOT NULL,
        chave text,
        entrada_hash text NOT NULL,
        via text NOT NULL CHECK (via IN ('acordo', 'juiz', 'revisao')),
        respostas jsonb,
        decisao jsonb,
        revisao_id bigint REFERENCES operacao.fila_revisao(id),
        custo_usd numeric(14, 8),
        criado_em timestamptz NOT NULL DEFAULT now()
    )""")
    op.execute("CREATE INDEX decisao_cascata_tarefa_idx ON operacao.decisao_cascata (tarefa, criado_em)")
    op.execute(
        "COMMENT ON COLUMN operacao.decisao_cascata.respostas IS "
        "'resposta de cada modelo (A, B, C), já mascarada; nula quando a tarefa lida com dado pessoal'"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS operacao.decisao_cascata, operacao.fila_revisao, operacao.chamada_modelo")
    op.execute("DROP TABLE IF EXISTS pessoal.contato_imovel, pessoal.contato")
