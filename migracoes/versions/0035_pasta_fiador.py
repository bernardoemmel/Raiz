"""Pasta privada do lote: retificações e referências imutáveis das previsões.

Revision ID: 0035
Revises: 0034
"""

from alembic import op

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE negocio.pasta_fiador (
            id uuid PRIMARY KEY,
            pedido_id uuid NOT NULL REFERENCES negocio.pedido(id),
            opcao text NOT NULL CHECK(opcao IN ('barata','segura','compacta')),
            UNIQUE(pedido_id, opcao)
        );
        CREATE TABLE negocio.pasta_fiador_versao (
            id uuid PRIMARY KEY,
            pasta_id uuid NOT NULL REFERENCES negocio.pasta_fiador(id),
            numero integer NOT NULL CHECK(numero>0),
            anterior_id uuid REFERENCES negocio.pasta_fiador_versao(id),
            tipo text NOT NULL CHECK(tipo IN ('inclusao','correcao','substituicao','retirada','nova_previsao')),
            motivo text NOT NULL,
            dados jsonb NOT NULL CHECK(jsonb_typeof(dados)='object'),
            validacao jsonb NOT NULL CHECK(jsonb_typeof(validacao)='object'),
            assinatura text NOT NULL CHECK(assinatura ~ '^[a-f0-9]{64}$'),
            registrada_em timestamptz NOT NULL DEFAULT clock_timestamp(),
            UNIQUE(pasta_id,numero),
            UNIQUE(pasta_id,id),
            FOREIGN KEY(pasta_id,anterior_id) REFERENCES negocio.pasta_fiador_versao(pasta_id,id)
        );
        CREATE INDEX pasta_fiador_atual ON negocio.pasta_fiador_versao(pasta_id,numero DESC);
        CREATE TABLE negocio.pasta_previsao_serie (
            id uuid PRIMARY KEY,
            pasta_id uuid NOT NULL REFERENCES negocio.pasta_fiador(id),
            codigo_car text NOT NULL,
            metodo text NOT NULL,
            UNIQUE(pasta_id,codigo_car,metodo),
            UNIQUE(pasta_id,id,codigo_car,metodo)
        );
        CREATE TABLE negocio.pasta_previsao_referencia (
            id uuid PRIMARY KEY,
            serie_id uuid NOT NULL,
            pasta_id uuid NOT NULL REFERENCES negocio.pasta_fiador(id),
            pasta_versao_id uuid NOT NULL REFERENCES negocio.pasta_fiador_versao(id),
            codigo_car text NOT NULL,
            metodo text NOT NULL,
            anterior_id uuid REFERENCES negocio.pasta_previsao_referencia(id),
            assinatura text NOT NULL CHECK(assinatura ~ '^[a-f0-9]{64}$'),
            dados jsonb NOT NULL,
            registrada_em timestamptz NOT NULL DEFAULT clock_timestamp(),
            UNIQUE(pasta_versao_id,serie_id),
            UNIQUE(pasta_id,serie_id,id),
            FOREIGN KEY(pasta_id,pasta_versao_id) REFERENCES negocio.pasta_fiador_versao(pasta_id,id),
            FOREIGN KEY(pasta_id,serie_id,codigo_car,metodo)
                REFERENCES negocio.pasta_previsao_serie(pasta_id,id,codigo_car,metodo),
            FOREIGN KEY(pasta_id,serie_id,anterior_id)
                REFERENCES negocio.pasta_previsao_referencia(pasta_id,serie_id,id)
        );
        CREATE INDEX pasta_previsao_por_serie ON negocio.pasta_previsao_referencia(serie_id,registrada_em DESC);
        CREATE TRIGGER pasta_fiador_versao_imutavel BEFORE UPDATE OR DELETE
            ON negocio.pasta_fiador_versao FOR EACH ROW EXECUTE FUNCTION negocio.proteger_versao_terra();
        CREATE TRIGGER pasta_previsao_imutavel BEFORE UPDATE OR DELETE
            ON negocio.pasta_previsao_referencia FOR EACH ROW EXECUTE FUNCTION negocio.proteger_versao_terra();
        CREATE TRIGGER pasta_previsao_serie_imutavel BEFORE UPDATE OR DELETE
            ON negocio.pasta_previsao_serie FOR EACH ROW EXECUTE FUNCTION negocio.proteger_versao_terra();
    """)


def downgrade() -> None:
    op.execute("""
        DROP TABLE negocio.pasta_previsao_referencia;
        DROP TABLE negocio.pasta_previsao_serie;
        DROP TABLE negocio.pasta_fiador_versao;
        DROP TABLE negocio.pasta_fiador;
    """)
