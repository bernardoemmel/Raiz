"""Operações duráveis, eventos e aprovação humana dos agentes.

Revision ID: 0028
Revises: 0027
"""

from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE negocio.trabalho_api (
    id uuid PRIMARY KEY,
    cliente_id bigint NOT NULL REFERENCES negocio.cliente(id) ON DELETE CASCADE,
    ferramenta text NOT NULL CHECK (ferramenta IN (
        'pedir_lote', 'preparar_reserva', 'consultar_disponibilidade', 'comparar_lotes', 'acompanhar_contato')),
    chave_hash char(64) NOT NULL,
    corpo_hash char(64) NOT NULL,
    corpo jsonb NOT NULL,
    estado text NOT NULL CHECK (estado IN (
        'submitted', 'working', 'input-required', 'completed', 'failed', 'canceled')),
    lancamento_id bigint UNIQUE REFERENCES negocio.lancamento_api(id),
    negocio_pedido_id uuid,
    resultado jsonb,
    erro jsonb,
    executor_token uuid,
    lease_ate timestamptz,
    tentativas integer NOT NULL DEFAULT 0 CHECK (tentativas >= 0),
    criado_em timestamptz NOT NULL DEFAULT now(),
    atualizado_em timestamptz NOT NULL DEFAULT now(),
    iniciado_em timestamptz,
    concluido_em timestamptz,
    UNIQUE (cliente_id, ferramenta, chave_hash)
);
CREATE INDEX trabalho_api_fila ON negocio.trabalho_api (criado_em)
    WHERE estado IN ('submitted', 'working');
CREATE INDEX trabalho_api_cliente ON negocio.trabalho_api (cliente_id, criado_em DESC);

CREATE TABLE negocio.cancelamento_api (
 cliente_id bigint NOT NULL REFERENCES negocio.cliente(id) ON DELETE CASCADE,
 chave_hash char(64) NOT NULL,
 pedido_id uuid NOT NULL,
 resposta jsonb NOT NULL,
 criada_em timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY (cliente_id, chave_hash)
);

CREATE TABLE negocio.webhook_inscricao (
 id uuid PRIMARY KEY,
 cliente_id bigint NOT NULL REFERENCES negocio.cliente(id) ON DELETE CASCADE,
 url_cifrada bytea NOT NULL,
 segredo_cifrado bytea NOT NULL,
 ativa boolean NOT NULL DEFAULT true,
 criada_em timestamptz NOT NULL DEFAULT now(),
 UNIQUE (id, cliente_id)
);
CREATE TABLE negocio.webhook_entrega (
 id uuid PRIMARY KEY,
 cliente_id bigint NOT NULL REFERENCES negocio.cliente(id) ON DELETE CASCADE,
 inscricao_id uuid NOT NULL,
 corpo bytea NOT NULL,
 estado text NOT NULL DEFAULT 'pendente' CHECK (estado IN ('pendente', 'enviando', 'entregue', 'falhou', 'cancelada')),
 tentativas integer NOT NULL DEFAULT 0 CHECK (tentativas >= 0),
 disponivel_em timestamptz NOT NULL DEFAULT now(),
 lease_id uuid,
 lease_ate timestamptz,
 http_status integer,
 criada_em timestamptz NOT NULL DEFAULT now(),
 entregue_em timestamptz,
 FOREIGN KEY (inscricao_id, cliente_id) REFERENCES negocio.webhook_inscricao(id, cliente_id) ON DELETE CASCADE
);
CREATE INDEX webhook_entrega_fila ON negocio.webhook_entrega(cliente_id, disponivel_em)
 WHERE estado IN ('pendente', 'enviando');

ALTER TABLE negocio.conta_api ADD COLUMN reservar_habilitado boolean NOT NULL DEFAULT false;
CREATE TABLE negocio.permissao_reserva_evento (
 id bigserial PRIMARY KEY, cliente_id bigint NOT NULL REFERENCES negocio.cliente(id),
 habilitado boolean NOT NULL, administrador_hash text NOT NULL,
 criado_em timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE negocio.reserva ADD COLUMN recibo_aprovacao text;
ALTER TABLE negocio.reserva ADD COLUMN confirmacao_token_cifrado bytea;
ALTER TABLE negocio.reserva ADD COLUMN preco_valido_ate timestamptz;
ALTER TABLE negocio.cobranca ADD COLUMN expira_em timestamptz;
ALTER TABLE negocio.cobranca ADD COLUMN pix_qr_svg text;
    """)


def downgrade() -> None:
    for coluna in ("pix_qr_svg", "expira_em"):
        op.execute(f"ALTER TABLE negocio.cobranca DROP COLUMN {coluna}")
    for coluna in ("preco_valido_ate", "confirmacao_token_cifrado", "recibo_aprovacao"):
        op.execute(f"ALTER TABLE negocio.reserva DROP COLUMN {coluna}")
    for tabela in (
        "permissao_reserva_evento",
        "webhook_entrega",
        "webhook_inscricao",
        "cancelamento_api",
        "trabalho_api",
    ):
        op.execute(f"DROP TABLE negocio.{tabela}")
    op.execute("ALTER TABLE negocio.conta_api DROP COLUMN reservar_habilitado")
