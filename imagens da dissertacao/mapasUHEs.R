# Código para elaboração de mapas temáticos com atributos das UHEs brasileiras
# Data: 20 fev. 2026
# Versão 2: melhorias no mapa_base (escala, norte, legenda interna, linewidth)

# install.packages(c("sf", "tidyverse", "dplyr", "tidyr", "lubridate",
#                    "patchwork", "ggspatial", "rnaturalearth", "rnaturalearthdata"))

# Pacotes utilizados:
library(here)              # para estruturação de pastas e subpastas
library(sf)                # para lidar com objetos espaciais (mapas)
library(tidyverse)         # para gráficos (ggplot2)
library(dplyr)             # para manipulação de dados
library(tidyr)             # para manipulação de dados
library(lubridate)         # para manipulação de datas
library(patchwork)         # para múltiplos gráficos em um mesmo plot
library(ggspatial)         # para escala gráfica e seta norte
library(rnaturalearth)     # para dados geográficos globais (rios)
library(rnaturalearthdata) # dados de suporte ao rnaturalearth
library(showtext)          # para uso de fontes do sistema (Times New Roman) no ggplot2

# Registro da fonte Arial (instalada no Windows)
font_add(family = "Arial",
         regular    = "C:/Windows/Fonts/arial.ttf",
         bold       = "C:/Windows/Fonts/arialbd.ttf",
         italic     = "C:/Windows/Fonts/ariali.ttf",
         bolditalic = "C:/Windows/Fonts/arialbi.ttf")
showtext_auto()                    # ativa renderização via showtext
showtext_opts(dpi = 300)           # alinha DPI com o ggsave

# Downloads do rnaturalearth costumam estourar o timeout padrão (60s)
# quando a conexão está lenta. Aumenta a folga.
options(timeout = max(600, getOption("timeout")))


# MAPA BASE ---------------------------------------------------------------

# --- Leitura dos dados necessários
# Códigos UHE
# Usa apenas as UHEs sorteadas no clustering (clustering-sin.ipynb -> df_mapa).
# O CSV é gerado pelo notebook na pasta do projeto de clustering.
# Para voltar a usar todas as UHEs, troque por here("coordenadasUHEs.csv").
coordUHEs <- readr::read_csv(
  "C:/Users/PersioPuertasGarciaL/Documents/Codigos/trabalhando/merge teste/dados/coordenadasUHEs_clustering.csv",
  show_col_types = FALSE)

# Contornos bacias hidrográficas
bacias <- st_read(
  "C:/Users/PersioPuertasGarciaL/Documents/Codigos/trabalhando/teste arima/R/data/external/shapefiles bacias/SNIRH_RegioesHidrograficas.shp")

# Espacialização das coordenadas (pacote 'sf')
coordUHEs_sf <- st_as_sf(
  coordUHEs,
  coords = c("long", "lat"),
  crs = 4326)

# Mapas do Brasil e estados (rnaturalearth)
# Só a geometria é usada aqui, então as fronteiras do Natural Earth servem bem.
brasil <- ne_countries(country = "Brazil", scale = 50, returnclass = "sf")

# ne_states() depende de 'rnaturalearthhires' (não está no CRAN).
# Instala sem prompt para não travar o script quando rodado via source().
if (!requireNamespace("rnaturalearthhires", quietly = TRUE)) {
  install.packages("rnaturalearthhires",
                   repos = "https://ropensci.r-universe.dev")
}
estados <- ne_states(country = "Brazil", returnclass = "sf")

# Rios principais (escala 1:10.000.000 - rnaturalearth)
# O ne_download pode falhar com "crs not found" quando o zip baixa
# incompleto. Em caso de erro, baixa o shapefile manualmente e força o CRS.
rios <- tryCatch(
  ne_download(scale = 10, type = "rivers_lake_centerlines",
              category = "physical", returnclass = "sf"),
  error = function(e) {
    url <- paste0("https://naciscdn.org/naturalearth/10m/physical/",
                  "ne_10m_rivers_lake_centerlines.zip")
    tmp <- tempfile(fileext = ".zip")
    download.file(url, tmp, mode = "wb")
    ex <- tempfile()
    unzip(tmp, exdir = ex)
    shp <- list.files(ex, pattern = "\\.shp$", full.names = TRUE)[1]
    r <- sf::st_read(shp, quiet = TRUE)
    if (is.na(sf::st_crs(r))) sf::st_crs(r) <- 4326
    r
  })

# Assimilação das projeções geográficas
coordUHEs_sf <- st_transform(coordUHEs_sf, st_crs(brasil))
bacias_sf    <- st_transform(bacias, st_crs(brasil))
rios_sf      <- st_transform(rios, st_crs(brasil))

# Recorte dos rios dentro do território brasileiro
rios_sf <- st_intersection(rios_sf, st_union(brasil))

# Conversão dos nomes das bacias para título (ex: AMAZÔNICA -> Amazônica)
bacias_sf <- bacias_sf %>%
  mutate(RHI_NM = stringr::str_to_title(RHI_NM))

# Cores
# cores_ <- c(
#   "#8DD3C7",
#   "#8a7979",
#   "#a97aaa",
#   "#a29fe7",
#   "#fff8bc",
#   "#ffb055",
#   "#B3DE69",
#   "#ccc8ce",
#   "#665ea0",
#   "#80B1D3",
#   "#CCEBC5",
#   "#ffda94"
# )
cores_ <- c(
  "Amazônica"                    = "#8DD3C7",
  "Atlântico Leste"              = "#8a7979",
  "Atlântico Nordeste Ocidental" = "#fff8bc",
  "Atlântico Nordeste Oriental"  = "#ffb055",
  "Atlântico Sudeste"            = "#a97aaa",
  "Atlântico Sul"                = "#665ea0",
  "Paraguai"                     = "#B3DE69",
  "Paraná"                       = "#80B1D3",
  "Parnaíba"                     = "#ffda94",
  "São Francisco"                = "#ccc8ce",
  "Tocantins-Araguaia"           = "#CCEBC5",
  "Uruguai"                      = "#a29fe7"
)

# Obtenção do mapa base
mapa_base <- ggplot() +
  # Inserção dos estados
  geom_sf(data = estados, fill = "gray95", color = "black",
          linewidth = 0.4, linetype = "dotted") +

  # Inserção das bacias
  geom_sf(data = bacias_sf, aes(fill = RHI_NM), color = "black",
          linewidth = 0.3, alpha = 0.7) +

  # Inserção do contorno do Brasil
  geom_sf(data = brasil, fill = NA, color = "black", linewidth = 0.5) +

  # Inserção dos rios principais
  geom_sf(data = rios_sf, color = "steelblue", linewidth = 0.2, alpha = 0.7) +

  # Coordenadas das UHEs
  geom_sf(data = coordUHEs_sf, shape = 21, fill = "white",
          color = "black", size = 1, stroke = 0.5) +

  # Escala gráfica (canto inferior direito)
  annotation_scale(location = "br", width_hint = 0.3,
                   text_cex = 0.45, line_width = 0.5) +

  # Seta norte (canto superior direito)
  annotation_north_arrow(
    location = "tr",
    style = north_arrow_fancy_orienteering(text_family = "Arial", text_size = 5),
    height = unit(0.5, "cm"),
    width  = unit(0.5, "cm")) +

  # Paleta de cores para as bacias
  #scale_fill_brewer(palette = "Set3", name = "Região hidrográfica") +

  scale_fill_manual(values = cores_, name = "Regiões hidrográficas") +
  guides(fill = guide_legend(ncol = 1)) +

  # Centralização do mapa na janela de plotagem
  coord_sf(
    xlim = c(-75, -33),  # longitude
    ylim = c(-35, 7),    # latitude
    expand = FALSE) +

  # Remover labels dos eixos
  labs(x = NULL, y = NULL) +

  # Estética final
  theme_bw(base_family = "Arial") +
  theme(
    legend.position = "right",
    legend.title    = element_text(size = 10, family = "Arial"),
    legend.text     = element_text(size = 9,  family = "Arial"),
    legend.key.size = unit(0.35, "cm"),
    axis.text       = element_text(size = 8,  family = "Arial"))

# Salvar
ggsave(
  filename = here("figuras", "mapa.png"),
  plot = mapa_base,
  width = 16,
  height = 8,
  units = "cm",
  dpi = 300)
