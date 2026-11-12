"""Achados de título no formato do CFPB e confirmações (E5 passos 1 e 3).

titulo.achado: um achado por (rodada, imóvel, fase, regra): registro (CAR + parcelas SIGEF + matrícula + CNS), regra,
campo, valor, situação (ok, falta, impede, conferir, nao_se_aplica), gravidade (reprova, confirmar, info), fase
(formato, geometria, coerencia, referencia, cadeia, regularizacao), mensagem, fonte, base legal e versão da regra.
titulo.confirmacao: quem confirmou, descartou ou corrigiu cada achado e quando. "quem" é o identificador do operador
(ex.: fundador, conferente-02), nunca nome; a confirmação vale para a mesma regra do mesmo imóvel nas rodadas
seguintes enquanto o valor não mudar.

Revision ID: 0021
Revises: 0020
Create Date: 2026-11-12
"""

from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE titulo.achado (
        id bigserial PRIMARY KEY,
        rodada_id bigint REFERENCES funil.rodada(id) ON DELETE CASCADE,
        registro text NOT NULL,
        cod_imovel text NOT NULL,
        fase text NOT NULL CHECK (fase IN ('formato', 'geometria', 'coerencia', 'referencia', 'cadeia',
                                           'regularizacao')),
        regra text NOT NULL,
        campo text,
        valor text,
        situacao text NOT NULL CHECK (situacao IN ('ok', 'falta', 'impede', 'conferir', 'nao_se_aplica')),
        gravidade text NOT NULL CHECK (gravidade IN ('reprova', 'confirmar', 'info')),
        mensagem text NOT NULL,
        fonte text,
        base text,
        regra_versao text,
        criado_em timestamptz NOT NULL DEFAULT now()
    )""")
    op.execute("CREATE INDEX achado_imovel_idx ON titulo.achado (cod_imovel, fase, regra)")
    op.execute("CREATE INDEX achado_rodada_idx ON titulo.achado (rodada_id)")
    op.execute("""
    CREATE TABLE titulo.confirmacao (
        id bigserial PRIMARY KEY,
        achado_id bigint NOT NULL REFERENCES titulo.achado(id) ON DELETE CASCADE,
        cod_imovel text NOT NULL,
        regra text NOT NULL,
        valor text,
        decisao text NOT NULL CHECK (decisao IN ('confirmado', 'descartado', 'corrigido')),
        quem text NOT NULL,
        nota text,
        em timestamptz NOT NULL DEFAULT now()
    )""")
    op.execute("CREATE INDEX confirmacao_imovel_idx ON titulo.confirmacao (cod_imovel, regra)")
    op.execute(
        "COMMENT ON COLUMN titulo.confirmacao.quem IS 'identificador do operador (fundador, conferente-02); nunca nome'"
    )
    # a confirmação só cresce: corrigir = confirmar de novo (vale a mais nova)
    op.execute("""
    CREATE FUNCTION titulo.nao_muda() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN RAISE EXCEPTION 'titulo.confirmacao só recebe linhas novas'; END $$""")
    op.execute("""CREATE TRIGGER confirmacao_nao_muda BEFORE UPDATE OR DELETE ON titulo.confirmacao
                  FOR EACH ROW EXECUTE FUNCTION titulo.nao_muda()""")
    # último achado de cada (imóvel, fase, regra), com a confirmação mais nova que ainda vale para o mesmo valor
    op.execute("""
    CREATE VIEW titulo.achado_vigente AS
    SELECT DISTINCT ON (a.cod_imovel, a.fase, a.regra) a.*,
           c.decisao AS confirmacao_decisao, c.quem AS confirmado_por, c.em AS confirmado_em, c.nota AS confirmacao_nota
    FROM titulo.achado a
    LEFT JOIN LATERAL (
        SELECT * FROM titulo.confirmacao c
        WHERE c.cod_imovel = a.cod_imovel AND c.regra = a.regra AND c.valor IS NOT DISTINCT FROM a.valor
        ORDER BY c.em DESC, c.id DESC LIMIT 1
    ) c ON true
    ORDER BY a.cod_imovel, a.fase, a.regra, a.rodada_id DESC NULLS LAST, a.id DESC""")


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS titulo.achado_vigente")
    op.execute("DROP TRIGGER IF EXISTS confirmacao_nao_muda ON titulo.confirmacao")
    op.execute("DROP FUNCTION IF EXISTS titulo.nao_muda()")
    op.execute("DROP TABLE IF EXISTS titulo.confirmacao, titulo.achado")
