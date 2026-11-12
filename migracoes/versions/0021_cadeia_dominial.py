"""Cadeia dominial no Postgres (E5 passo 6), no molde do ACRIS: documento (matrícula lida), atos, partes e imóveis.

titulo.matricula: uma linha por leitura de certidão (CNS + matrícula + hash da leitura): situação, origem (título
público, matrícula ou transcrição anterior, usucapião, desconhecida) e a matrícula de origem normalizada (a referência
ao registro anterior), área, destino, georreferenciamento, versões do modelo e das regras.
titulo.ato: cada ato da matrícula, na ordem da certidão, com o ato de transmissão anterior na cadeia (referência ao
ato anterior), quem o cancela e a quebra de continuidade quando há.
titulo.ato_parte: quem transmite e quem recebe, só com rótulo (P1, P2), tipo e documento mascarado; nome só de órgão
público e banco. O banco recusa documento sem máscara.
titulo.matricula_imovel: o imóvel de cada matrícula (CAR), pelo certidao_alvo da rodada vigente, com as chaves
normalizadas pelas mesmas regras do Python (titulo.norm_cns e titulo.norm_matricula).
titulo.cadeia_origem: segue a matrícula de origem até onde houver leitura (até 12 saltos) e diz onde a cadeia para.

Revision ID: 0021
Revises: 0020
Create Date: 2026-11-12
"""

from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # as mesmas regras de raiz/documentos/certidao/regras.py (normalizar_cns e normalizar_matricula)
    op.execute(r"""
    CREATE FUNCTION titulo.norm_cns(x text) RETURNS text LANGUAGE sql IMMUTABLE AS $$
        SELECT CASE WHEN d = '' THEN NULL WHEN length(d) < 6 THEN lpad(d, 6, '0') ELSE d END
        FROM (SELECT regexp_replace(coalesce(x, ''), '\D', '', 'g') AS d) s $$""")
    op.execute(r"""
    CREATE FUNCTION titulo.norm_matricula(x text) RETURNS text LANGUAGE sql IMMUTABLE AS $$
        SELECT CASE WHEN s = '' THEN NULL
                    WHEN s ~ '^0*\d+[A-Z]*$' THEN regexp_replace(s, '^0*(\d+)([A-Z]*)$', '\1\2')
                    ELSE s END
        FROM (SELECT regexp_replace(
                     regexp_replace(upper(regexp_replace(coalesce(x, ''), '^(\d+)\.0$', '\1')),
                                    'MATR[IÍí]CULA|N[º°O]\.?|N\.', ' ', 'g'),
                     '[^0-9A-Z]', '', 'g') AS s) t $$""")

    op.execute("""
    CREATE TABLE titulo.matricula (
        cns text NOT NULL,
        matricula text NOT NULL,
        leitura_hash text NOT NULL,
        leitura_id bigint,
        lido_em timestamptz,
        modelo text,
        leitor_versao text,
        regras_versao text,
        situacao text,
        conferencia text,
        origem text,
        origem_referencia text,
        origem_matricula text,
        data_abertura date,
        area_ha double precision,
        matricula_destino text,
        georreferenciado boolean,
        n_transmissoes integer,
        quebras integer,
        onus_graves boolean,
        carregado_em timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (cns, matricula, leitura_hash)
    )""")
    op.execute("""
    CREATE TABLE titulo.ato (
        id bigserial PRIMARY KEY,
        cns text NOT NULL,
        matricula text NOT NULL,
        leitura_hash text NOT NULL,
        ordem integer NOT NULL,
        numero text NOT NULL,
        tipo text,
        natureza text,
        afeta text,
        data date,
        fracao_pct double precision,
        pagina integer,
        transmissao boolean NOT NULL DEFAULT false,
        anterior_numero text,
        cancelado_por text,
        quebra boolean NOT NULL DEFAULT false,
        quebra_motivo text,
        resumo text,
        FOREIGN KEY (cns, matricula, leitura_hash) REFERENCES titulo.matricula ON DELETE CASCADE,
        UNIQUE (cns, matricula, leitura_hash, ordem)
    )""")
    op.execute("""
    CREATE TABLE titulo.ato_parte (
        ato_id bigint NOT NULL REFERENCES titulo.ato(id) ON DELETE CASCADE,
        papel text NOT NULL CHECK (papel IN ('transmitente', 'adquirente')),
        rotulo text,
        tipo text,
        documento text CHECK (documento IS NULL OR documento LIKE '%*%'),
        instituicao text CHECK (instituicao IS NULL OR tipo IN ('orgao_publico', 'instituicao_financeira'))
    )""")
    op.execute("CREATE INDEX ato_parte_ato_idx ON titulo.ato_parte (ato_id)")
    op.execute(
        "COMMENT ON TABLE titulo.ato_parte IS 'parte do ato só com rótulo, tipo e documento mascarado; nunca nome'"
    )
    op.execute("""
    CREATE VIEW titulo.matricula_vigente AS
    SELECT DISTINCT ON (cns, matricula) * FROM titulo.matricula
    ORDER BY cns, matricula, lido_em DESC NULLS LAST, carregado_em DESC""")
    op.execute("""
    CREATE VIEW titulo.matricula_imovel AS
    SELECT DISTINCT ON (c.cod_imovel, titulo.norm_cns(c.registro_cns), titulo.norm_matricula(c.registro_matricula))
           c.cod_imovel, titulo.norm_cns(c.registro_cns) AS cns,
           titulo.norm_matricula(c.registro_matricula) AS matricula, c.ha_sobre_car, c.rodada_id
    FROM titulo.certidao_alvo c JOIN funil.rodada r ON r.id = c.rodada_id
    WHERE c.registro_matricula IS NOT NULL
    ORDER BY c.cod_imovel, titulo.norm_cns(c.registro_cns), titulo.norm_matricula(c.registro_matricula),
             r.data_corte DESC, r.id DESC""")
    op.execute("""
    CREATE VIEW titulo.cadeia_origem AS
    WITH RECURSIVE passo AS (
        SELECT m.cns, m.matricula, m.cns AS cns_atual, m.matricula AS matricula_atual, m.origem, m.origem_referencia,
               m.origem_matricula, 0 AS saltos, ARRAY[m.matricula] AS caminho
        FROM titulo.matricula_vigente m
        UNION ALL
        SELECT p.cns, p.matricula, o.cns, o.matricula, o.origem, o.origem_referencia, o.origem_matricula,
               p.saltos + 1, p.caminho || o.matricula
        FROM passo p JOIN titulo.matricula_vigente o ON o.cns = p.cns_atual AND o.matricula = p.origem_matricula
        WHERE p.saltos < 12 AND NOT o.matricula = ANY (p.caminho)
    )
    SELECT DISTINCT ON (cns, matricula) cns, matricula, matricula_atual AS para_em, origem, origem_referencia,
           saltos, caminho,
           CASE WHEN origem IN ('titulo_publico', 'usucapiao') THEN 'chega_a_origem'
                WHEN origem IN ('matricula_anterior', 'transcricao_anterior') THEN 'falta_ler_origem'
                ELSE 'origem_desconhecida' END AS situacao
    FROM passo ORDER BY cns, matricula, saltos DESC""")


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS titulo.cadeia_origem, titulo.matricula_imovel, titulo.matricula_vigente")
    op.execute("DROP TABLE IF EXISTS titulo.ato_parte, titulo.ato, titulo.matricula")
    op.execute("DROP FUNCTION IF EXISTS titulo.norm_matricula(text), titulo.norm_cns(text)")
