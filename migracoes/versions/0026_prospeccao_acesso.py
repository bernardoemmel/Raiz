"""Créditos pagos de consulta, desbloqueio da ficha e pedido interno de contato.

Revision ID: 0026
Revises: 0025
"""

from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE negocio.prospeccao_carteira (
            cliente_id bigint PRIMARY KEY REFERENCES negocio.cliente(id) ON DELETE CASCADE,
            creditos integer NOT NULL DEFAULT 0 CHECK (creditos >= 0)
        )
    """)
    op.execute("""
        CREATE TABLE negocio.prospeccao_compra (
            id uuid PRIMARY KEY,
            cliente_id bigint NOT NULL REFERENCES negocio.cliente(id) ON DELETE CASCADE,
            chave_idempotencia text NOT NULL,
            plano text NOT NULL,
            creditos integer NOT NULL CHECK (creditos > 0),
            valor_rs numeric(14,2) NOT NULL CHECK (valor_rs > 0),
            externo_id text NOT NULL UNIQUE,
            modo text NOT NULL CHECK (modo IN ('teste', 'producao')),
            estado text NOT NULL CHECK (estado IN ('pendente', 'paga', 'expirada', 'cancelada')),
            pix_copia_cola text NOT NULL,
            expira_em timestamptz NOT NULL,
            criada_em timestamptz NOT NULL DEFAULT now(),
            paga_em timestamptz,
            UNIQUE(cliente_id, chave_idempotencia)
        )
    """)
    op.execute("""
        CREATE TABLE negocio.prospeccao_desbloqueio (
            cliente_id bigint NOT NULL REFERENCES negocio.cliente(id) ON DELETE CASCADE,
            cod_imovel text NOT NULL,
            criado_em timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY(cliente_id, cod_imovel)
        )
    """)
    op.execute("""
        CREATE TABLE negocio.prospeccao_movimento (
            id bigserial PRIMARY KEY,
            cliente_id bigint NOT NULL REFERENCES negocio.cliente(id) ON DELETE CASCADE,
            quantidade integer NOT NULL CHECK (quantidade <> 0),
            compra_id uuid UNIQUE REFERENCES negocio.prospeccao_compra(id),
            cod_imovel text,
            criado_em timestamptz NOT NULL DEFAULT now(),
            CHECK ((compra_id IS NOT NULL AND cod_imovel IS NULL AND quantidade > 0)
                OR (compra_id IS NULL AND cod_imovel IS NOT NULL AND quantidade = -1)),
            UNIQUE(cliente_id, cod_imovel)
        )
    """)
    op.execute("""
        CREATE TABLE negocio.prospeccao_contato (
            id uuid PRIMARY KEY,
            cliente_id bigint NOT NULL,
            cod_imovel text NOT NULL,
            estado text NOT NULL DEFAULT 'recebido' CHECK (estado IN ('recebido', 'em_analise', 'concluido')),
            criado_em timestamptz NOT NULL DEFAULT now(),
            UNIQUE(cliente_id, cod_imovel),
            FOREIGN KEY(cliente_id, cod_imovel)
                REFERENCES negocio.prospeccao_desbloqueio(cliente_id, cod_imovel) ON DELETE CASCADE
        )
    """)
    op.execute("""
        CREATE TABLE negocio.prospeccao_limite (
            chave_hash text NOT NULL,
            acao text NOT NULL,
            janela_s integer NOT NULL CHECK (janela_s > 0),
            quantidade integer NOT NULL CHECK (quantidade > 0),
            expira_em timestamptz NOT NULL,
            PRIMARY KEY(chave_hash, acao, janela_s)
        )
    """)
    op.execute("CREATE INDEX prospeccao_limite_expira ON negocio.prospeccao_limite(expira_em)")


def downgrade() -> None:
    for tabela in ("limite", "contato", "movimento", "desbloqueio", "compra", "carteira"):
        op.execute(f"DROP TABLE IF EXISTS negocio.prospeccao_{tabela}")
