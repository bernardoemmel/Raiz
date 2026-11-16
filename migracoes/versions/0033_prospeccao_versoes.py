"""Versões imutáveis da terra e baselines privados de consulta e monitoramento.

Revision ID: 0033
Revises: 0032
"""

from alembic import op

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE negocio.prospeccao_ficha_versao (
            id bigserial PRIMARY KEY,
            cod_imovel text NOT NULL,
            hash_conteudo text NOT NULL CHECK (hash_conteudo ~ '^[a-f0-9]{64}$'),
            documento jsonb NOT NULL CHECK (jsonb_typeof(documento) = 'object'),
            registrada_em timestamptz NOT NULL DEFAULT clock_timestamp(),
            UNIQUE(cod_imovel, hash_conteudo)
        );
        CREATE INDEX prospeccao_versao_car ON negocio.prospeccao_ficha_versao(cod_imovel, id DESC);
        CREATE TABLE negocio.prospeccao_ficha_observacao (
            id bigserial PRIMARY KEY,
            cod_imovel text NOT NULL,
            versao_id bigint NOT NULL REFERENCES negocio.prospeccao_ficha_versao(id),
            anterior_id bigint REFERENCES negocio.prospeccao_ficha_versao(id),
            origem text NOT NULL,
            mudancas jsonb NOT NULL CHECK (jsonb_typeof(mudancas) = 'array'),
            registrada_em timestamptz NOT NULL DEFAULT clock_timestamp()
        );
        CREATE INDEX prospeccao_observacao_car ON negocio.prospeccao_ficha_observacao(cod_imovel, id);
        CREATE TABLE negocio.prospeccao_ficha_atual (
            cod_imovel text PRIMARY KEY,
            versao_id bigint REFERENCES negocio.prospeccao_ficha_versao(id),
            observacao_id bigint REFERENCES negocio.prospeccao_ficha_observacao(id)
        );
        CREATE TABLE negocio.prospeccao_ficha_consulta (
            cliente_id bigint NOT NULL REFERENCES negocio.cliente(id) ON DELETE CASCADE,
            cod_imovel text NOT NULL,
            versao_id bigint NOT NULL REFERENCES negocio.prospeccao_ficha_versao(id),
            consultada_em timestamptz NOT NULL DEFAULT clock_timestamp(),
            lotes jsonb NOT NULL DEFAULT '[]',
            PRIMARY KEY(cliente_id, cod_imovel)
        );
        CREATE FUNCTION negocio.proteger_versao_terra() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'O histórico global da terra é imutável'; END; $$;
        CREATE TRIGGER prospeccao_versao_imutavel BEFORE UPDATE OR DELETE
            ON negocio.prospeccao_ficha_versao FOR EACH ROW EXECUTE FUNCTION negocio.proteger_versao_terra();
        CREATE TRIGGER prospeccao_observacao_imutavel BEFORE UPDATE OR DELETE
            ON negocio.prospeccao_ficha_observacao FOR EACH ROW EXECUTE FUNCTION negocio.proteger_versao_terra();
        ALTER TABLE negocio.prospeccao_busca_vista
            ADD COLUMN observacao_id bigint REFERENCES negocio.prospeccao_ficha_observacao(id),
            ADD COLUMN corresponde boolean NOT NULL DEFAULT true,
            ADD COLUMN transicao bigint NOT NULL DEFAULT 0,
            ADD COLUMN lotes jsonb NOT NULL DEFAULT '[]';
        ALTER TABLE negocio.prospeccao_busca_aviso
            DROP CONSTRAINT prospeccao_busca_aviso_busca_id_cod_imovel_key,
            ADD COLUMN tipo text NOT NULL DEFAULT 'nova_fazenda',
            ADD COLUMN evento_chave text NOT NULL DEFAULT 'primeira',
            ADD COLUMN detalhes jsonb NOT NULL DEFAULT '[]',
            ADD COLUMN observacao_id bigint REFERENCES negocio.prospeccao_ficha_observacao(id),
            ADD CONSTRAINT prospeccao_aviso_evento UNIQUE(busca_id, cod_imovel, evento_chave);
        CREATE INDEX prospeccao_busca_vista_car ON negocio.prospeccao_busca_vista(cod_imovel, busca_id);
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE negocio.prospeccao_busca_aviso
            DROP CONSTRAINT prospeccao_aviso_evento,
            DROP COLUMN observacao_id, DROP COLUMN detalhes, DROP COLUMN evento_chave, DROP COLUMN tipo;
        DELETE FROM negocio.prospeccao_busca_aviso a USING negocio.prospeccao_busca_aviso b
            WHERE a.busca_id=b.busca_id AND a.cod_imovel=b.cod_imovel AND a.id>b.id;
        ALTER TABLE negocio.prospeccao_busca_aviso ADD UNIQUE(busca_id, cod_imovel);
        DROP INDEX negocio.prospeccao_busca_vista_car;
        ALTER TABLE negocio.prospeccao_busca_vista DROP COLUMN observacao_id,
            DROP COLUMN corresponde, DROP COLUMN transicao, DROP COLUMN lotes;
        DROP TABLE negocio.prospeccao_ficha_consulta;
        DROP TABLE negocio.prospeccao_ficha_atual;
        DROP TABLE negocio.prospeccao_ficha_observacao;
        DROP TABLE negocio.prospeccao_ficha_versao;
        DROP FUNCTION negocio.proteger_versao_terra();
    """)
