from raiz.licencas import Pacote, avaliar, classificar, falhas


def test_classifica_proibidas():
    for lic in [
        "AGPL-3.0-only",
        "GNU Affero General Public License v3",
        "EUPL-1.2",
        "SSPL-1.0",
        "BUSL-1.1",
        "BSL",
        "Non Commercial",
        "CC BY NC 4.0",
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


def test_expressao_preserva_parenteses_e_rejeita_termos_desconhecidos():
    # Antes, retirar parênteses transformava em MIT OR (... AND AGPL) e autorizava.
    assert classificar("(MIT OR Apache-2.0) AND AGPL-3.0-only")[0] == "proibida"
    assert classificar("MIT AND (BSD-3-Clause OR SSPL-1.0)")[0] == "ok"
    assert classificar("(MIT OR Apache-2.0")[0] == "desconhecida"
    assert classificar("MIT OR")[0] == "desconhecida"
    assert classificar("LicencaComercialInventada")[0] == "desconhecida"
    assert classificar("SEE LICENSE IN COPYING")[0] == "desconhecida"
    assert classificar("MIT AND LicenseRef-Desconhecida")[0] == "desconhecida"
    assert classificar("MIT/Apache-2.0")[0] == "ok"
    # Boost não é Business Source.
    assert classificar("BSL-1.0")[0] == "ok"
    assert classificar("BSL-1.1")[0] == "proibida"


def test_registro_nao_libera_proibida_nem_gpl_distribuida():
    ps = avaliar(
        [
            Pacote("mudoulicenca", "2", "AGPL-3.0-only", "python"),
            Pacote("biblioteca", "1", "GPL-3.0-only", "npm"),
            Pacote("extensao", "1", "GPL-3.0-only", "cargo"),
        ],
        {
            "conferidas": {"mudoulicenca": "MIT (conferido no repositório)"},
            "gpl_no_servidor": {"biblioteca": "worker", "extensao": "worker"},
        },
    )
    assert [p.situacao for p in ps] == ["proibida", "gpl_sem_registro", "gpl_sem_registro"]
    assert len(falhas(ps)) == 3


def test_npm_lock_inclui_pacote_aninhado_proibido(tmp_path):
    import json

    from raiz.licencas import pacotes_npm

    lock = tmp_path / "package-lock.json"
    lock.write_text(
        json.dumps(
            {
                "lockfileVersion": 3,
                "packages": {
                    "": {"name": "app"},
                    "node_modules/a": {"version": "1", "license": "MIT"},
                    "node_modules/a/node_modules/@exemplo/b": {"version": "2", "license": "SSPL-1.0"},
                    "node_modules/semlicenca": {"version": "1"},
                },
            }
        )
    )
    ps = avaliar(pacotes_npm(lock), {"conferidas": {}, "gpl_no_servidor": {}})
    assert {p.nome for p in falhas(ps)} == {"@exemplo/b", "semlicenca"}


def test_npm_falha_se_inventario_nao_pode_ser_conferido(tmp_path):
    import pytest

    from raiz.licencas import pacotes_npm

    lock = tmp_path / "package-lock.json"
    with pytest.raises(FileNotFoundError):
        pacotes_npm(lock)
    lock.write_text('{"lockfileVersion": 1, "dependencies": {}}')
    with pytest.raises(ValueError, match="incompatível"):
        pacotes_npm(lock)
    lock.write_text('{"lockfileVersion": 3, "packages": {"": {}}}')
    with pytest.raises(ValueError, match="vazio"):
        pacotes_npm(lock)
    lock.write_text("incompleto")
    with pytest.raises(ValueError):
        pacotes_npm(lock)


def test_cargo_falha_se_ferramenta_ausente_ou_com_erro(tmp_path, monkeypatch):
    import shutil
    import subprocess

    import pytest

    from raiz.licencas import pacotes_cargo

    manifesto = tmp_path / "Cargo.toml"
    manifesto.write_text('[package]\nname = "app"\n')
    monkeypatch.setattr(shutil, "which", lambda _: None)
    with pytest.raises(RuntimeError, match="cargo não encontrado"):
        pacotes_cargo(manifesto)
    monkeypatch.setattr(shutil, "which", lambda _: "/cargo")
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess(a, 1))
    with pytest.raises(RuntimeError, match="cargo metadata falhou"):
        pacotes_cargo(manifesto)


def test_cargo_usa_lock_e_nao_ignora_dependencia_local(tmp_path, monkeypatch):
    import json
    import shutil
    import subprocess

    from raiz.licencas import pacotes_cargo

    manifesto = tmp_path / "Cargo.toml"
    manifesto.write_text('[package]\nname = "raiz_iov"\n')
    monkeypatch.setattr(shutil, "which", lambda _: "/cargo")

    def rodar(args, **kw):
        assert "--locked" in args
        return subprocess.CompletedProcess(
            args,
            0,
            stdout=json.dumps(
                {
                    "packages": [
                        {"name": "raiz_iov", "version": "1", "source": None},
                        {"name": "externa", "version": "1", "source": None, "license": "EUPL-1.2"},
                    ]
                }
            ),
        )

    monkeypatch.setattr(subprocess, "run", rodar)
    ps = avaliar(pacotes_cargo(manifesto), {"conferidas": {}, "gpl_no_servidor": {}})
    assert [p.nome for p in falhas(ps)] == ["externa"]
