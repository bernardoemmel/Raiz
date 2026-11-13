# Reprodução das referências ecológicas

Código próprio usado nas sete referências de `raiz/regras/padroes/ecologia_referencias_abertas.json`,
preservado byte a byte para conservar `calculo_versao`. Não contém código de autores nem dados de fazendas.
São quantis descritivos de parcelas com esforço conhecido; não contam espécies ou árvores totais por imóvel.

Copie os dois scripts para uma pasta de pesquisa e coloque nela os CSV públicos abaixo. Execute
`python analisar_ecologia.py` e `python analisar_densidade_giles.py` nessa pasta. Os scripts conferem hashes,
usam bootstrap com semente fixa e gravam a versão junto dos quantis. Não fazem download nem enviam informações.

| Arquivo local | Fonte | Licença | SHA256 |
|---|---|---|---|
| Boeschoten_etal_2026_GCB_reforestation.csv | https://zenodo.org/records/18244528 | CC-BY-4.0 | 54ee5ffe92b95718498a21417bbd7ee5e10295b4d4feaa979d85565b5fb5333b |
| rozendaal2019_CC0.csv | https://doi.org/10.17026/dans-xh8-gh92 | CC0-1.0 | ff060d7f969a1a25882b1f3ee526a4686ebf4e522fdc9bb0945c2763b7ac1201 |
| giles2024_CC-BY4.csv | https://zenodo.org/records/13970371 | CC-BY-4.0 | 977eb5df8e0b71854877103de7d22d9897981fffd2025d89b182d2801d8d88b0 |

O recorte Tefé/Alvarães conserva a diferença entre fustes e árvores distintas, a ambiguidade DAP >5 versus
≥5 e as três parcelas ausentes na coorte publicada. A validação por comunidade mede transferência dentro
desse estudo; não valida extrapolação ao Pará. O número de espécies é por 900 m² ou rarefeito a 25 fustes,
conforme a fonte, e nunca é multiplicado pela área da fazenda.
