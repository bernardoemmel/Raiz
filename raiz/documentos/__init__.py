"""Documentos da Raíz: lê certidões de matrícula, busca registros e editais novos, gera os documentos do produto e
guarda cada leitura com a versão do modelo para aprender com os acertos e erros.

Partes:
- certidao/  leitor de certidão de matrícula (PDF) pela API da Anthropic, conferido com o certidoes_<mun>.csv do
             motor. Resultado por matrícula: conferida, divergente ou cancelada (revisar quando o documento não deixa
             ler). Saída por município: matricula_<mun>.csv com a coluna matricula_conferida que o front já lê.
- busca/     registros e editais novos (Verra, SFB, Ideflor-Bio, Diário Oficial da União), uma vez por semana.
- gerados/   documentos em .docx (docxtpl): folha de 3 páginas para o dono, relatório do lote com faixa P10 a P90 e
             checklist do edital.
- aprendizado.py  marca quando a certidão real confirma ou desmente a leitura; placar por modelo e versão;
                  exportação no formato do aprendizado (E8).

Regra que vale para tudo aqui: nome e CPF nunca vão para log, treino ou repositório. O leitor pede ao modelo que troque
cada pessoa por um rótulo (P1, P2...), mascara CPF e CNPJ e passa os textos livres por uma segunda tranca de nomes antes
de gravar. Os PDFs das certidões não são copiados: só o sha256 deles fica guardado.

Uso: python -m raiz.documentos --help
"""

__version__ = "0.1.0"
