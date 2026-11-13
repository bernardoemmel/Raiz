"""Entrada privada da primeira certidão: original cifrado, previsão congelada e revisão humana.

Nada é publicado nem enviado por este fluxo. Cada empresa tem um armazém próprio;
nomes de arquivo, erros do provedor e texto bruto do PDF não viram metadados.
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import io
import json
import re
import uuid
from contextlib import contextmanager
from pathlib import Path

import pandas as pd
from pypdf import PdfReader
from sqlalchemy import text

from raiz.documentos import aprendizado, config, tabelas
from raiz.documentos.armazem import Armazem, agora
from raiz.documentos.certidao import leitor
from raiz.documentos.claude import LeitorClaude
from raiz.pessoal import Cofre, SemChavePessoal
from raiz.privacidade import varrer_texto

MAX_BYTES = 20 * 1024 * 1024
MAX_PAGINAS = 100
MAX_ARMAZENAMENTO = 512 * 1024 * 1024
CAR = re.compile(r"[A-Z]{2}-[0-9]{7}-[0-9A-F]{32}\Z")
COLUNAS_MOTOR = ("cod_imovel", "registro_cns", "registro_matricula", "ha_sobre_car")
COLUNAS_IMOVEL = ("cod_imovel", "municipio")

SQL = """
create table if not exists entrada_certidao (
 id text primary key, pedido_id text not null, cod_imovel text not null,
 chave_hash text not null unique, arquivo_sha256 text not null, tamanho integer not null,
 paginas integer not null, recebido_em text not null, estado text not null,
 conteudo_cifrado blob not null, leitura_id integer, erro text,
 tentativa text, tentativa_em text, tentativa_ate text,
 unique(pedido_id, cod_imovel, arquivo_sha256)
);
create table if not exists entrada_revisao (
 chave_hash text primary key, documento_id text not null, corpo_hash text not null,
 criado_em text not null, resultado_json text not null
);
create table if not exists entrada_chave (
 chave_hash text primary key, documento_id text not null references entrada_certidao(id)
);
insert or ignore into entrada_chave select chave_hash, id from entrada_certidao;
"""


class ErroEntrada(ValueError):
    def __init__(self, status: int, codigo: str):
        super().__init__(codigo)
        self.status = status


def _uuid(valor: str) -> str:
    try:
        return str(uuid.UUID(str(valor)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ErroEntrada(422, "identificador_invalido") from exc


def _hash(dado: bytes | str) -> str:
    return hashlib.sha256(dado.encode() if isinstance(dado, str) else dado).hexdigest()


def _json(dado) -> str:
    return json.dumps(dado, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _campo_seguro(campo: str, valor) -> bool:
    """Projeção fechada: nenhum texto livre, número inválido ou documento pessoal."""
    padroes = {
        "area_ha": r"[0-9]{1,12}(?:[.,][0-9]{1,8})?",
        "onus_ativos": r"[0-9]{1,8}",
        "n_transmissoes": r"[0-9]{1,8}",
        "cns": r"[0-9]{2}\.?[0-9]{3}-?[0-9]",
        "matricula": r"[0-9][0-9.-]{0,15}[a-z]?",
        "onus_graves": r"(?:true|false|sim|nao|não|0|1)",
        "quebra_cadeia": r"(?:true|false|sim|nao|não|0|1)",
        "situacao_documento": r"(?:ativa|cancelada|bloqueada|ilegivel|nao_e_certidao)",
    }
    s = str(valor).lower()
    return bool(re.fullmatch(padroes[campo], s)) and not varrer_texto(s)


def validar_pdf(pdf: bytes) -> int:
    if len(pdf) > MAX_BYTES:
        raise ErroEntrada(413, "pdf_acima_de_20_mb")
    if not pdf.startswith(b"%PDF-"):
        raise ErroEntrada(422, "arquivo_nao_e_pdf")
    try:
        p = PdfReader(io.BytesIO(pdf), strict=True)
        if p.is_encrypted:
            raise ErroEntrada(422, "pdf_protegido_por_senha")
        paginas = len(p.pages)
        if not 1 <= paginas <= MAX_PAGINAS:
            raise ErroEntrada(422, "pdf_deve_ter_1_a_100_paginas")
        raiz = p.trailer["/Root"]
        if any(k in raiz for k in ("/OpenAction", "/AA")) or any(
            k in raiz.get("/Names", {}) for k in ("/JavaScript", "/EmbeddedFiles")
        ):
            raise ErroEntrada(422, "pdf_com_conteudo_ativo")
        for pagina in p.pages:
            if "/AA" in pagina:
                raise ErroEntrada(422, "pdf_com_conteudo_ativo")
            for anotacao in pagina.get("/Annots", []):
                a = anotacao.get_object()
                if "/AA" in a or "/A" in a or a.get("/Subtype") == "/FileAttachment":
                    raise ErroEntrada(422, "pdf_com_conteudo_ativo")
        return paginas
    except ErroEntrada:
        raise
    except Exception as exc:  # o parser pode incluir trechos do PDF na mensagem
        raise ErroEntrada(422, "pdf_invalido") from exc


def capturar_previsao(cod_imovel: str) -> dict:
    """Somente o CAR solicitado, de cópia local autenticada; a amostra nunca é previsão real."""
    municipio = config.municipio_do_imovel(cod_imovel)
    uf = config.uf_do_municipio(municipio)
    amostra = (config.REPO / "dados" / "amostra").resolve()
    saida = {"capturada_em": agora(), "motor": [], "imoveis": [], "fontes": {}}
    for tabela, colunas, destino in (("certidoes", COLUNAS_MOTOR, "motor"), ("imoveis", COLUNAS_IMOVEL, "imoveis")):
        for base in config.pastas_entrada():
            for arquivo in (base / (uf or "") / f"{tabela}_{municipio}.csv", base / f"{tabela}_{municipio}.csv"):
                if not arquivo.is_file() or arquivo.resolve().is_relative_to(amostra):
                    continue
                df = tabelas.ler_csv(arquivo)
                if "cod_imovel" not in df:
                    continue
                linhas = df.loc[df.cod_imovel == cod_imovel, [c for c in colunas if c in df]]
                if linhas.empty:
                    continue
                # to_json converte numpy/NaN; o envelope cifrado só retém as colunas necessárias.
                saida[destino] = json.loads(linhas.to_json(orient="records"))
                saida["fontes"][tabela] = _hash(arquivo.read_bytes())
                break
            if saida[destino]:
                break
    return saida


def capturar_previsao_banco(engine, cod_imovel: str) -> dict:
    """Na API, a previsão vem da rodada vigente do PostGIS privado, sem varrer outros CARs."""
    with engine.connect() as con:
        linhas = (
            con.execute(
                text("""select c.cod_imovel, c.registro_cns, c.registro_matricula,
            c.ha_sobre_car, c.rodada_id from funil.vigente v join titulo.certidao_alvo c
            on c.cod_imovel=v.cod_imovel and c.rodada_id=v.rodada_id
            where v.cod_imovel=:car order by c.registro_cns, c.registro_matricula"""),
                {"car": cod_imovel},
            )
            .mappings()
            .all()
        )
    motor = [{k: r[k] for k in COLUNAS_MOTOR} for r in linhas]
    return {
        "capturada_em": agora(),
        "motor": motor,
        "imoveis": [],
        "fontes": {"rodadas": sorted({r["rodada_id"] for r in linhas}), "tipo": "postgis_vigente"},
    }


class _LeitorSemErroPessoal:
    """Falhas do provedor não são evidência e não entram no armazém com texto livre."""

    def __init__(self, base):
        self.base = base
        self.modelo, self.esforco, self._cliente = base.modelo, base.esforco, base._cliente

    def ler_pdf(self, *args):
        r = self.base.ler_pdf(*args)
        if not r.ok:
            r.erro = "leitura_recusada" if r.recusou else "leitura_indisponivel"
        return r


class _ArmazemNaTransacao(Armazem):
    """Revisão e recibo idempotente precisam confirmar juntos na mesma transação."""

    def __init__(self, armazem: Armazem, conexao):
        self.caminho, self.conexao = armazem.caminho, conexao

    @contextmanager
    def con(self):
        yield self.conexao


class EntradaCertidao:
    def __init__(self, cliente_id: int, *, pasta: Path | None = None, cofre: Cofre | None = None):
        if isinstance(cliente_id, bool) or not isinstance(cliente_id, int) or cliente_id <= 0:
            raise ErroEntrada(422, "empresa_invalida")
        self.cliente_id = cliente_id
        self.cofre = cofre or Cofre()  # falhar fechado antes de criar qualquer arquivo
        self.pasta = (pasta or config.pasta_dados()) / "empresas" / str(cliente_id)
        self.pasta.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.pasta.chmod(0o700)
        self.armazem = Armazem(self.pasta / "documentos.sqlite")
        self.armazem.caminho.chmod(0o600)
        with self.armazem.con() as con:
            con.executescript(SQL)

    def _linha(self, documento_id: str, con=None) -> dict:
        documento_id = _uuid(documento_id)
        if con is None:
            with self.armazem.con() as c:
                return self._linha(documento_id, c)
        r = con.execute("select * from entrada_certidao where id = ?", (documento_id,)).fetchone()
        if r is None:
            raise ErroEntrada(404, "certidao_nao_encontrada")
        return dict(r)

    def _abrir(self, linha: dict) -> dict:
        d = json.loads(self.cofre.decifrar(linha["conteudo_cifrado"]))
        if d["cliente_id"] != self.cliente_id or d["id"] != linha["id"] or d["cod_imovel"] != linha["cod_imovel"]:
            raise ErroEntrada(409, "envelope_incompativel")
        return d

    def receber(self, pdf: bytes, *, pedido_id: str, cod_imovel: str, chave: str, previsao: dict | None = None) -> dict:
        pedido_id, chave = _uuid(pedido_id), _hash(_uuid(chave))
        cod_imovel = cod_imovel.upper()
        if not CAR.fullmatch(cod_imovel):
            raise ErroEntrada(422, "car_invalido")
        paginas, sha = validar_pdf(pdf), _hash(pdf)
        with self.armazem.con() as con:
            con.execute("begin immediate")
            anterior = con.execute(
                """select e.* from entrada_certidao e join entrada_chave k
                on k.documento_id=e.id where k.chave_hash=?""",
                (chave,),
            ).fetchone()
            if anterior:
                if (anterior["pedido_id"], anterior["cod_imovel"], anterior["arquivo_sha256"]) != (
                    pedido_id,
                    cod_imovel,
                    sha,
                ):
                    raise ErroEntrada(409, "chave_reutilizada_com_outro_documento")
                return self.obter(anterior["id"])
            anterior = con.execute(
                "select id from entrada_certidao where pedido_id = ? and cod_imovel = ? and arquivo_sha256 = ?",
                (pedido_id, cod_imovel, sha),
            ).fetchone()
            if anterior:
                con.execute("insert into entrada_chave values (?, ?)", (chave, anterior["id"]))
                return self.obter(anterior["id"])
            usado = con.execute("select coalesce(sum(tamanho), 0) from entrada_certidao").fetchone()[0]
            if usado + len(pdf) > MAX_ARMAZENAMENTO:
                raise ErroEntrada(413, "limite_de_armazenamento_da_empresa")
            documento_id = str(uuid.uuid4())
            envelope = dict(
                id=documento_id,
                cliente_id=self.cliente_id,
                cod_imovel=cod_imovel,
                pdf=base64.b64encode(pdf).decode(),
                previsao=previsao or capturar_previsao(cod_imovel),
            )
            con.execute(
                """insert into entrada_certidao (id, pedido_id, cod_imovel, chave_hash, arquivo_sha256, tamanho,
                    paginas, recebido_em, estado, conteudo_cifrado) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    documento_id,
                    pedido_id,
                    cod_imovel,
                    chave,
                    sha,
                    len(pdf),
                    paginas,
                    agora(),
                    "recebida",
                    self.cofre.cifrar(_json(envelope)),
                ),
            )
            con.execute("insert into entrada_chave values (?, ?)", (chave, documento_id))
        return self.obter(documento_id)

    def obter(self, documento_id: str) -> dict:
        r = self._linha(documento_id)
        previsao = self._abrir(r)["previsao"]
        saida = {
            k: r[k]
            for k in (
                "id",
                "pedido_id",
                "cod_imovel",
                "arquivo_sha256",
                "tamanho",
                "paginas",
                "recebido_em",
                "estado",
                "erro",
            )
        }
        saida["previsao"] = dict(
            disponivel=bool(previsao["motor"]), capturada_em=previsao["capturada_em"], sha256=_hash(_json(previsao))
        )
        saida["leitura"] = None
        saida["comparacao"] = []
        saida["gabaritos"] = []
        if r["leitura_id"]:
            lt = self.armazem.leitura(r["leitura_id"])
            saida["leitura"] = {
                k: getattr(lt, k)
                for k in (
                    "id",
                    "modelo",
                    "prompt_versao",
                    "esquema_versao",
                    "registro_hash",
                    "lido_em",
                    "custo_usd",
                    "tokens_entrada",
                    "tokens_saida",
                    "duracao_ms",
                )
            }
            # Mesmo um campo estruturado pode vir com texto pessoal por erro do
            # modelo. A consulta devolve somente valores da projeção técnica.
            saida["leitura"]["campos"] = {
                k: v if _campo_seguro(k, v := f(lt)) else None for k, f in aprendizado.CAMPOS.items()
            }
            for c in self.armazem.conferencias_por_leitura(lt.id) if previsao["motor"] else []:
                saida["comparacao"].append(
                    {
                        "situacao": c["situacao"],
                        "precisa_confirmar": bool(c["precisa_confirmar"]),
                        "motivos": [
                            {"codigo": m["codigo"], "gravidade": m["gravidade"]} for m in json.loads(c["motivos_json"])
                        ],
                    }
                )
            saida["gabaritos"] = [
                {k: g[k] for k in ("alvo", "valor_real", "confirma", "fonte", "observado_em", "registrado_em")}
                for g in self.armazem.gabaritos(lt.id)
            ]
        return saida

    def original(self, documento_id: str) -> bytes:
        """Só o revisor interno acessa o PDF; nenhuma cópia descriptografada é gravada em disco."""
        r = self._linha(documento_id)
        pdf = base64.b64decode(self._abrir(r)["pdf"], validate=True)
        if _hash(pdf) != r["arquivo_sha256"]:
            raise ErroEntrada(409, "pdf_divergente")
        return pdf

    def processar(self, documento_id: str, *, chave: str, leitor_modelo=None) -> dict:
        chave = _hash(_uuid(chave))
        with self.armazem.con() as con:
            con.execute("begin immediate")
            r = self._linha(documento_id, con)
            if r["estado"] in {"lida", "aguardando_previsao", "conferida_por_pessoa"} or (
                r["tentativa"] == chave and r["estado"] != "processando"
            ):
                return self.obter(documento_id)
            if r["estado"] == "processando" and r["tentativa_ate"] > agora():
                raise ErroEntrada(409, "leitura_em_andamento")
            con.execute(
                """update entrada_certidao set estado='processando', tentativa=?, tentativa_em=?,
                tentativa_ate=?, erro=null where id=?""",
                (chave, agora(), (dt.datetime.now(dt.UTC) + dt.timedelta(minutes=30)).isoformat(), r["id"]),
            )
        try:
            envelope = self._abrir(r)
            previsao = envelope["previsao"]
            pdf = base64.b64decode(envelope["pdf"], validate=True)
            if _hash(pdf) != r["arquivo_sha256"]:
                raise ErroEntrada(409, "pdf_divergente")
            fonte = "sha256:" + _hash(_json(previsao))
            lid = None
            if r["estado"] == "processando" and r["tentativa_em"]:
                # Processo interrompido depois da gravação imutável: aproveita o
                # recibo desta previsão, sem cobrar outra chamada do modelo.
                with self.armazem.con() as con:
                    salvo = con.execute(
                        """select l.id from leitura l join conferencia c on c.leitura_id=l.id
                        where l.arquivo_sha256=? and l.erro is null and l.lido_em>=?
                        and c.cod_imovel=? and c.motor_arquivo=? order by l.id desc limit 1""",
                        (r["arquivo_sha256"], r["tentativa_em"], r["cod_imovel"], fonte),
                    ).fetchone()
                lid = salvo[0] if salvo else None
            if lid is None:
                modelo = _LeitorSemErroPessoal(leitor_modelo or LeitorClaude())
                resultado = leitor.ler_certidao(
                    pdf,
                    cod_imovel=r["cod_imovel"],
                    leitor=modelo,
                    armazem=self.armazem,
                    forcar_releitura=True,
                    comparacao=(pd.DataFrame(previsao["motor"]), pd.DataFrame(previsao["imoveis"]), fonte),
                    comparacao_capturada_em=previsao["capturada_em"],
                )
                erro, lid = resultado.erro, resultado.leitura.id
            else:
                erro = None
            estado = "falha" if erro else "lida" if previsao["motor"] else "aguardando_previsao"
        except Exception as exc:  # nunca salvar mensagem, caminho, resposta ou texto do provedor
            estado, lid = "falha", None
            erro = "chave_de_cifra_indisponivel" if isinstance(exc, SemChavePessoal) else "leitura_indisponivel"
        with self.armazem.con() as con:
            con.execute(
                "update entrada_certidao set estado=?, leitura_id=?, erro=? where id=? and tentativa=?",
                (estado, lid, erro, r["id"], chave),
            )
        return self.obter(documento_id)

    def revisar(
        self,
        documento_id: str,
        *,
        chave: str,
        fonte: str,
        observado_em: str,
        situacao_real: str | None = None,
        campos: dict | None = None,
        leitura_integral: bool | None = None,
    ) -> dict:
        chave = _hash(_uuid(chave))
        if fonte not in {"conferencia_humana", "cartorio", "onr"}:
            raise ErroEntrada(422, "fonte_de_gabarito_invalida")
        try:
            data = dt.date.fromisoformat(observado_em)
            if data > dt.datetime.now(dt.UTC).date():
                raise ValueError
        except ValueError as exc:
            raise ErroEntrada(422, "data_de_observacao_invalida") from exc
        campos = campos or {}
        if set(campos) - aprendizado.CAMPOS.keys() or varrer_texto(_json(campos)):
            raise ErroEntrada(422, "campos_de_gabarito_invalidos")
        if any(not _campo_seguro(campo, valor) for campo, valor in campos.items()):
            raise ErroEntrada(422, "campos_de_gabarito_invalidos")
        corpo = dict(
            fonte=fonte,
            observado_em=observado_em,
            situacao_real=situacao_real,
            campos=campos,
            leitura_integral=leitura_integral,
        )
        corpo_hash = _hash(_json(corpo))
        with self.armazem.con() as con:
            con.execute("begin immediate")
            anterior = con.execute("select * from entrada_revisao where chave_hash = ?", (chave,)).fetchone()
            if anterior:
                if anterior["documento_id"] != documento_id or anterior["corpo_hash"] != corpo_hash:
                    raise ErroEntrada(409, "chave_de_revisao_reutilizada")
                return self.obter(documento_id)
            r = self._linha(documento_id, con)
            if r["estado"] not in {"lida", "aguardando_previsao", "conferida_por_pessoa"} or not r["leitura_id"]:
                raise ErroEntrada(409, "certidao_ainda_nao_lida")
            if not self._abrir(r)["previsao"]["motor"] and situacao_real is not None:
                raise ErroEntrada(409, "comparacao_sem_previsao_nao_e_gabarito_do_motor")
            resultado = aprendizado.marcar(r["leitura_id"], armazem=_ArmazemNaTransacao(self.armazem, con), **corpo)
            con.execute(
                "insert into entrada_revisao values (?, ?, ?, ?, ?)",
                (chave, documento_id, corpo_hash, agora(), _json(resultado)),
            )
            con.execute("update entrada_certidao set estado='conferida_por_pessoa' where id=?", (documento_id,))
        return self.obter(documento_id)
