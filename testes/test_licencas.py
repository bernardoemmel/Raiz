from raiz.licencas import Pacote, avaliar, classificar, falhas


def test_classifica_proibidas():
    for lic in [
        "AGPL-3.0-only",
        "GNU Affero General Public License v3",
        "EUPL-1.2",
        "SSPL-1.0",
        "BUSL-1.1",
        "CC-BY-NC-4.0",
        "CC-BY-NC-SA-4.0",
        "Elastic License 2.0",
        "RSALv2",
        "Apache-2.0 with Commons Clause",
    ]:
        assert classificar(lic)[0] == "proibida", lic


def test_classifica_permitidas():
    for lic in ["MIT", "BSD-3-Clause", "Apache-2.0", "MIT License", "PostgreSQL", "CC-BY-4.0", "ISC", "0BSD"]:
        assert classificar(lic)[0] == "ok", lic
    assert classificar("LGPL-3.0-only")[0] == "lgpl"
    assert classificar("GNU Lesser General Public License v2 or later (LGPLv2+)")[0] == "lgpl"
    assert classificar("GPL-2.0-or-later")[0] == "gpl"


def test_expressao_spdx():
    assert classificar("MIT OR GPL-3.0")[0] == "ok"  # dá para escolher a MIT
    assert classificar("MIT AND AGPL-3.0")[0] == "proibida"
    assert classificar("(Apache-2.0 OR MIT)")[0] == "ok"
    # Redis 8: tripla escolha, todas proibidas pelo CLAUDE.md
    assert classificar("RSALv2 OR SSPL-1.0 OR AGPL-3.0")[0] == "proibida"
    assert classificar("")[0] == "desconhecida"


def test_registro_gpl_e_conferidas():
    reg = {"conferidas": {"semlic": "MIT (conferido no repositório)"}, "gpl_no_servidor": {"gplzinho": "worker"}}
    ps = avaliar(
        [
            Pacote("gplzinho", "1", "GPL-3.0", "python"),
            Pacote("gplsolto", "1", "GPL-3.0", "python"),
            Pacote("semlic", "1", "", "npm"),
            Pacote("outra", "1", "", "npm"),
        ],
        reg,
    )
    assert [p.situacao for p in ps] == ["gpl_servidor", "gpl_sem_registro", "conferida", "desconhecida"]
    assert {p.nome for p in falhas(ps)} == {"gplsolto", "outra"}
