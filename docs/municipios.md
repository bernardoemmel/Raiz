# Municípios: o que estava errado e o que falta rodar

Conferido em 27/11/2026 contra a [Divisão Territorial Brasileira 2025](https://geoftp.ibge.gov.br/organizacao_do_territorio/estrutura_territorial/divisao_territorial/2025/DTB_2025.zip) (5.571 municípios, a edição mais recente no FTP do IBGE). Não há DTB 2026.

## O que estava errado

O mapa nasceu na malha do TerraBrasilis. O código do município existia, mas a divisa podia ser a anterior: município novo (Boa Esperança do Norte, `5101837`) e os que cederam território ficavam com o contorno velho. O código só trocava a UF inteira quando um código publicado **faltava** na malha. As outras UFs continuavam na divisa antiga.

À parte, a lista de nomes que veio com o produto (`raiz/executor/municipios.csv`, espelho de kelvins/municipios-brasileiros) divergia da grafia oficial em 30 municípios. Os códigos, não: os 5.571 do motor e os 5.571 do front (`front/compartilhado/ibge-municipios.ts`) são os mesmos da DTB 2025.

Cerca de 0,6% das fazendas do Pará têm no código do CAR um município e o polígono no vizinho. A busca já procura nos dois lugares (`car_<UF>.json` e `car_fronteira.json`). Isso não se corrige renomeando a lista; é a posição do imóvel.

## O que este repositório já corrigiu

- Os 30 nomes da lista do motor foram alinhados à DTB 2025.
- `front/scripts/geo.py` aplica a Malha Municipal do IBGE a **toda UF que tenha município publicado**, não só à UF com código faltando. O ZIP conferido fica em cache e a rodada seguinte não baixa de novo. O desenho do CAR não é apagado.

## O que ainda precisa rodar

Não rodei a troca da malha aqui: ela baixa a geometria oficial de cada UF e só vale no build do site, com a pasta do Release `dados`.

1. **Malha no mapa (recomendado, assim que este PR entrar).** O workflow **Publicar o site** já chama `front/scripts/geo.py --dados`. Na primeira publicação depois do merge ele baixa os ZIPs do IBGE. **Cerca de 15 a 40 minutos**, dentro do job de 180 minutos. Não reprocessa o funil e não usa API paga. Para repetir à mão, com a pasta pública já baixada:

   ```bash
   python3 front/scripts/geo.py --dados dados/publicos --sem-base
   ```

2. **Nomes nos resumos já publicados (pode esperar).** O Release `dados` guarda o nome que o motor gravou. A lista nova só aparece quando o estado for reprocessado pelo workflow **Processar estados (motor)**. Estados grandes levam várias horas por fatia. A demo não depende disso: o mapa e o pedido usam o código IBGE.

3. **Conferir de novo no futuro:**

   ```bash
   python3 scripts/conferir_municipios.py           # sem rede
   python3 scripts/conferir_municipios.py --baixar  # baixa a DTB e compara código e nome
   ```
