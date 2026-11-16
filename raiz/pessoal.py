"""Dado pessoal necessário à operação (telefone e BSUID do WhatsApp), sempre cifrado.

- Cifra: Fernet (AES-128-CBC + HMAC-SHA256, biblioteca cryptography). RAIZ_CHAVE_PESSOAL aceita várias chaves
  separadas por vírgula: a primeira cifra, todas decifram (troca de chave sem perder nada).
- Busca: HMAC-SHA256 do valor normalizado, com chave derivada da primeira chave; o banco nunca vê o número.
- Sem RAIZ_CHAVE_PESSOAL nada pessoal é gravado (SemChavePessoal).
- O nome de perfil do WhatsApp não é guardado.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from sqlalchemy import Connection, text

from raiz.config import config


class SemChavePessoal(RuntimeError):
    pass


def gerar_chave() -> str:
    return Fernet.generate_key().decode()


def _chaves(chave: str | None = None) -> list[bytes]:
    bruta = chave or (config().chave_pessoal.get_secret_value() if config().chave_pessoal else "")
    ks = [k.strip().encode() for k in bruta.split(",") if k.strip()]
    if not ks:
        raise SemChavePessoal("defina RAIZ_CHAVE_PESSOAL no .env (raiz pessoal gerar-chave); nada pessoal é gravado")
    return ks


class Cofre:
    def __init__(self, chave: str | None = None):
        ks = _chaves(chave)
        self._f = MultiFernet([Fernet(k) for k in ks])
        self._hmac = hashlib.sha256(b"raiz-indice-pessoal|" + base64.urlsafe_b64decode(ks[0])).digest()

    def cifrar(self, valor: str) -> bytes:
        return self._f.encrypt(valor.encode("utf-8"))

    def decifrar(self, dado: bytes | memoryview) -> str:
        try:
            return self._f.decrypt(bytes(dado)).decode("utf-8")
        except InvalidToken as ex:
            raise SemChavePessoal("chave não abre este dado (chave trocada sem manter a antiga?)") from ex

    def cifrar_bytes(self, dado: bytes) -> bytes:
        return self._f.encrypt(dado)

    def decifrar_bytes(self, dado: bytes | memoryview) -> bytes:
        try:
            return self._f.decrypt(bytes(dado))
        except InvalidToken as ex:
            raise SemChavePessoal("chave não abre este dado (chave trocada sem manter a antiga?)") from ex

    def indice(self, valor: str) -> str:
        return hmac.new(self._hmac, valor.encode("utf-8"), hashlib.sha256).hexdigest()


def normalizar_telefone(t: str) -> str:
    """Só dígitos, com código do país (o WhatsApp manda assim: 5591...). Número brasileiro sem 55 ganha o 55."""
    d = re.sub(r"\D", "", t or "")
    if len(d) in (10, 11):
        d = "55" + d
    if not 12 <= len(d) <= 15:
        raise ValueError("telefone com tamanho inválido")
    return d


def _por(con: Connection, coluna: str, h: str):
    return con.execute(text(f"select id from pessoal.contato where {coluna} = :h"), {"h": h}).scalar()


def registrar_contato_whatsapp(
    con: Connection,
    bsuid: str,
    wa_id: str | None = None,
    parent_bsuid: str | None = None,
    username: str | None = None,
    cofre: Cofre | None = None,
) -> int:
    """Grava ou completa o contato que escreveu no WhatsApp. Junta pelo BSUID ou pelo telefone; quem já existia
    pelo telefone ganha o BSUID (e vice-versa). Devolve o id do contato."""
    cofre = cofre or Cofre()
    hb = cofre.indice(bsuid)
    tel = normalizar_telefone(wa_id) if wa_id else None
    ht = cofre.indice(tel) if tel else None
    pais = bsuid.split(".")[0] if "." in bsuid else None
    id_b = _por(con, "bsuid_hmac", hb)
    id_t = _por(con, "telefone_hmac", ht) if ht else None
    campos = {
        "pb": cofre.cifrar(parent_bsuid) if parent_bsuid else None,
        "un": cofre.cifrar(username) if username else None,
        "pais": pais,
    }
    if id_b is None and id_t is None:
        return con.execute(
            text("""
            insert into pessoal.contato (bsuid_hmac, bsuid_cifrado, parent_bsuid_cifrado, telefone_hmac,
                telefone_cifrado, username_cifrado, pais, origem)
            values (:hb, :bc, :pb, :ht, :tc, :un, :pais, 'whatsapp') returning id"""),
            dict(hb=hb, bc=cofre.cifrar(bsuid), ht=ht, tc=cofre.cifrar(tel) if tel else None, **campos),
        ).scalar_one()
    alvo = id_b if id_b is not None else id_t
    sets = [
        "parent_bsuid_cifrado = coalesce(:pb, parent_bsuid_cifrado)",
        "username_cifrado = coalesce(:un, username_cifrado)",
        "pais = coalesce(:pais, pais)",
        "atualizado_em = now()",
    ]
    params = dict(id=alvo, **campos)
    if id_b is None:  # existia pelo telefone: ganha o BSUID
        sets += ["bsuid_hmac = :hb", "bsuid_cifrado = :bc"]
        params.update(hb=hb, bc=cofre.cifrar(bsuid))
    if ht and id_t is None:  # existia pelo BSUID e o telefone é novo: guarda junto
        sets += ["telefone_hmac = :ht", "telefone_cifrado = :tc"]
        params.update(ht=ht, tc=cofre.cifrar(tel))
    con.execute(text(f"update pessoal.contato set {', '.join(sets)} where id = :id"), params)
    return alvo


def achar_por_bsuid(con: Connection, bsuid: str, cofre: Cofre | None = None) -> int | None:
    return _por(con, "bsuid_hmac", (cofre or Cofre()).indice(bsuid))


def achar_por_telefone(con: Connection, telefone: str, cofre: Cofre | None = None) -> int | None:
    return _por(con, "telefone_hmac", (cofre or Cofre()).indice(normalizar_telefone(telefone)))


def destino_whatsapp(con: Connection, contato_id: int, cofre: Cofre | None = None) -> str:
    """Para quem mandar a mensagem: o BSUID quando existe (prioridade do PyWa), senão o telefone."""
    cofre = cofre or Cofre()
    r = con.execute(
        text("select bsuid_cifrado, telefone_cifrado from pessoal.contato where id = :i"), {"i": contato_id}
    ).one()
    return cofre.decifrar(r.bsuid_cifrado) if r.bsuid_cifrado else cofre.decifrar(r.telefone_cifrado)


def vincular_imovel(con: Connection, contato_id: int, cod_imovel: str, papel: str = "dono") -> None:
    con.execute(
        text("""insert into pessoal.contato_imovel (contato_id, cod_imovel, papel) values (:c, :i, :p)
                        on conflict do nothing"""),
        {"c": contato_id, "i": cod_imovel, "p": papel},
    )


def registrar_consentimento(con: Connection, contato_id: int) -> None:
    con.execute(
        text("update pessoal.contato set consentimento_em = now(), atualizado_em = now() where id = :i"),
        {"i": contato_id},
    )


def apagar_contato(con: Connection, contato_id: int) -> None:
    """Pedido de exclusão do titular (LGPD, art. 18): apaga o contato e os vínculos."""
    con.execute(text("delete from pessoal.contato where id = :i"), {"i": contato_id})
