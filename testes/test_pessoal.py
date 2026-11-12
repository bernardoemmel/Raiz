import pytest
from sqlalchemy import create_engine, text

from raiz import pessoal as P

CHAVE = P.gerar_chave()


def test_cofre_cifra_e_indice_estavel():
    c = P.Cofre(CHAVE)
    d = c.cifrar("5591988887777")
    assert b"5591988887777" not in d and c.decifrar(d) == "5591988887777"
    assert c.indice("5591988887777") == P.Cofre(CHAVE).indice("5591988887777")
    assert c.indice("5591988887777") != P.Cofre(P.gerar_chave()).indice("5591988887777")


def test_troca_de_chave_mantem_dados_antigos():
    velha = P.Cofre(CHAVE)
    d = velha.cifrar("BR.abc")
    nova = P.Cofre(P.gerar_chave() + "," + CHAVE)
    assert nova.decifrar(d) == "BR.abc"
    with pytest.raises(P.SemChavePessoal):
        P.Cofre(P.gerar_chave()).decifrar(d)


def test_sem_chave_nao_grava(monkeypatch):
    monkeypatch.setattr(P, "config", lambda: type("C", (), {"chave_pessoal": None})())
    with pytest.raises(P.SemChavePessoal):
        P.Cofre()


def test_normaliza_telefone():
    assert P.normalizar_telefone("(91) 98888-7777") == "5591988887777"
    assert P.normalizar_telefone("+55 91 98888-7777") == "5591988887777"
    with pytest.raises(ValueError):
        P.normalizar_telefone("123")


@pytest.mark.banco
def test_contato_whatsapp_junta_bsuid_e_telefone(banco_url):
    eng = create_engine(banco_url)
    cofre = P.Cofre(CHAVE)
    with eng.begin() as con:
        con.execute(text("truncate pessoal.contato cascade"))
        # 1) chega só com BSUID (usuário com nome de usuário, sem telefone no webhook)
        a = P.registrar_contato_whatsapp(con, "BR.111aaa", None, cofre=cofre)
        # 2) a mesma pessoa aparece com telefone: o mesmo contato ganha o telefone
        b = P.registrar_contato_whatsapp(con, "BR.111aaa", "5591988887777", cofre=cofre)
        assert a == b
        assert P.achar_por_telefone(con, "(91) 98888-7777", cofre) == a
        # 3) contato cadastrado antes só pelo telefone ganha o BSUID quando escreve
        con.execute(text("insert into pessoal.contato (telefone_hmac, telefone_cifrado, origem) "
                         "values (:h, :c, 'cadastro')"),
                    {"h": cofre.indice("5594977776666"), "c": cofre.cifrar("5594977776666")})  # fmt: skip
        c = P.registrar_contato_whatsapp(con, "BR.222bbb", "5594977776666", cofre=cofre)
        assert P.achar_por_bsuid(con, "BR.222bbb", cofre) == c != a
        assert P.destino_whatsapp(con, c, cofre) == "BR.222bbb"
        # nada legível no banco
        bruto = con.execute(text("select string_agg(encode(telefone_cifrado, 'escape'), '') from pessoal.contato"))
        assert "98888" not in (bruto.scalar() or "")
        P.vincular_imovel(con, a, "PA-1504950-X")
        P.apagar_contato(con, a)
        assert P.achar_por_bsuid(con, "BR.111aaa", cofre) is None
        assert con.execute(text("select count(*) from pessoal.contato_imovel")).scalar() == 0
    eng.dispose()
