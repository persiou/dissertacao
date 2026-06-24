"""
Extração de precipitação por coroas circulares concêntricas clipadas com a bacia.

Para cada reservatório, cria 5 coroas circulares (1 disco + 4 anéis) centradas
nas coordenadas da barragem, com raios igualmente espaçados (R/5, 2R/5, ..., R).
As coroas são intersectadas com o
polígono da bacia para extrair apenas precipitação dentro da área de drenagem.

Resultado: 5 variáveis de precipitação por reservatório (150 colunas total).

Uso:
   py extract_precipitation_coroas.py --merge-dir ./dados/merge --shapefile-dir ./dados/bacias --inicio 2000-06-01 --fim 2026-01-31 --output ./dados/precipitacao_coroas_30res.csv
"""

import os
import sys
import glob
import argparse
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import geopandas as gpd
import xarray as xr
from shapely.geometry import Point
from tqdm import tqdm

warnings.filterwarnings('ignore', category=FutureWarning)


# =============================================================================
# Primitivas de leitura do MERGE e recorte por shapefile
# =============================================================================

def ler_merge_grib2(filepath):
    """
    Lê um arquivo MERGE GRIB2 e retorna o DataArray de precipitação.
    O MERGE tem resolução de 0.1° (~10 km) sobre a América do Sul.

    Returns:
        xr.DataArray com dims (latitude, longitude) e valores em mm/dia
    """
    try:
        ds = xr.open_dataset(filepath, engine='cfgrib')
        # O campo de precipitação pode ter nomes diferentes dependendo da versão
        # Geralmente: 'tp' (total precipitation) ou 'prec' ou 'unknown'
        var_names = list(ds.data_vars)
        if len(var_names) == 1:
            da = ds[var_names[0]]
        elif 'tp' in var_names:
            da = ds['tp']
        elif 'prec' in var_names:
            da = ds['prec']
        else:
            da = ds[var_names[0]]
        ds.close()
        return da
    except Exception as e:
        # Fallback: tentar com diferentes backends
        try:
            ds = xr.open_dataset(filepath, engine='cfgrib',
                                 backend_kwargs={'indexpath': ''})
            var_names = list(ds.data_vars)
            da = ds[var_names[0]]
            ds.close()
            return da
        except Exception as e2:
            print(f"  Erro ao ler {filepath}: {e2}")
            return None


def extrair_data_do_filename(filename):
    """Extrai a data do nome do arquivo MERGE_CPTEC_YYYYMMDD.grib2"""
    basename = os.path.basename(filename)
    # MERGE_CPTEC_20000601.grib2
    try:
        date_str = basename.replace("MERGE_CPTEC_", "").replace(".grib2", "")
        return datetime.strptime(date_str, "%Y%m%d")
    except ValueError:
        return None


def carregar_shapefiles_bacias(shapefile_dir: Path, reservatorios_df: pd.DataFrame):
    """
    Carrega shapefiles das áreas de drenagem.

    Espera encontrar arquivos no formato:
      {shapefile_dir}/{NOME_RESERVATORIO}.shp
    ou um único shapefile com uma coluna 'nome' identificando cada bacia.

    Returns:
        dict: {nome_reservatorio: GeoDataFrame}
    """
    bacias = {}

    # Opção 1: Arquivo único com todas as bacias
    arquivo_unico = shapefile_dir / "bacias_contribuicao.shp"
    if arquivo_unico.exists():
        gdf = gpd.read_file(arquivo_unico)
        # Tentar encontrar coluna de nome
        nome_col = None
        for col in ['nome', 'NOME', 'name', 'NAME', 'NM_USINA', 'nm_usina']:
            if col in gdf.columns:
                nome_col = col
                break

        if nome_col:
            for _, res in reservatorios_df.iterrows():
                match = gdf[gdf[nome_col].str.upper().str.contains(res['nome'].upper())]
                if len(match) > 0:
                    bacias[res['nome']] = match.iloc[0:1]
                else:
                    print(f"  AVISO: Bacia não encontrada para {res['nome']}")
        else:
            print("AVISO: Coluna de nome não encontrada no shapefile unificado.")
        return bacias

    # Opção 2: Shapefiles individuais
    for _, res in reservatorios_df.iterrows():
        nome_clean = res['nome'].replace(' ', '_').replace(',', '').replace('.', '')
        possiveis = [
            shapefile_dir / f"{nome_clean}.shp",
            shapefile_dir / f"{res['nome']}.shp",
            shapefile_dir / f"{nome_clean.lower()}.shp",
        ]
        for shp_path in possiveis:
            if shp_path.exists():
                bacias[res['nome']] = gpd.read_file(shp_path)
                break
        else:
            print(f"  AVISO: Shapefile não encontrado para {res['nome']}")

    return bacias


def extrair_precip_shapefile(da, geometria, all_touched=True):
    """
    Extrai precipitação média dentro de um polígono usando rioxarray.

    Args:
        da: DataArray do MERGE com CRS definido
        geometria: geometria shapely do polígono da bacia
        all_touched: incluir pixels parcialmente cobertos

    Returns:
        float: precipitação média em mm/dia
    """
    import rioxarray  # noqa

    try:
        # Definir CRS se não estiver definido
        if not hasattr(da, 'rio') or da.rio.crs is None:
            da = da.rio.write_crs("EPSG:4326")

        # Ajustar nomes das dimensões espaciais
        if 'latitude' in da.dims and 'longitude' in da.dims:
            da = da.rio.set_spatial_dims(x_dim='longitude', y_dim='latitude')

        # Recortar pelo polígono
        clipped = da.rio.clip([geometria], all_touched=all_touched)

        if clipped.size == 0:
            return np.nan

        # Média ponderada por cos(lat) para maior precisão
        if 'latitude' in clipped.dims:
            weights = np.cos(np.deg2rad(clipped.latitude))
            precip = float(clipped.weighted(weights).mean(skipna=True).values)
        else:
            precip = float(clipped.mean(skipna=True).values)

        return max(0.0, precip) if not np.isnan(precip) else np.nan

    except Exception as e:
        return np.nan


def ajustar_longitude_360_para_180(da):
    """
    Converte longitudes de 0-360 para -180 a 180 se necessário.
    Necessário porque os GRIB2 do MERGE usam 0-360 mas os shapefiles usam -180-180.
    """
    if 'longitude' in da.dims and float(da.longitude.max()) > 180:
        da = da.assign_coords(longitude=(da.longitude + 180) % 360 - 180)
        da = da.sortby('longitude')
    return da


def calcular_geometrias_coroas(geometria_bacia, lat_dam, lon_dam, n_coroas=5):
    """
    Gera N coroas circulares concêntricas clipadas com o polígono da bacia.

    O raio R é a maior distância entre o reservatório e qualquer ponto da bacia.
    Os raios são igualmente espaçados (R/n, 2R/n, ..., R).

    Args:
        geometria_bacia: geometria shapely da bacia (EPSG:4326)
        lat_dam: latitude da barragem
        lon_dam: longitude da barragem
        n_coroas: número de coroas (default 5)

    Returns:
        list de geometrias shapely (EPSG:4326), uma por coroa.
        Pode conter None para coroas sem interseção com a bacia.
    """
    # Criar GeoSeries para projetar
    ponto = Point(lon_dam, lat_dam)
    gs_bacia = gpd.GeoSeries([geometria_bacia], crs="EPSG:4326")
    gs_ponto = gpd.GeoSeries([ponto], crs="EPSG:4326")

    # Estimar CRS UTM adequado
    utm_crs = gs_bacia.estimate_utm_crs()

    # Projetar bacia e ponto para UTM
    bacia_utm = gs_bacia.to_crs(utm_crs).iloc[0]
    ponto_utm = gs_ponto.to_crs(utm_crs).iloc[0]

    # R = maior distância entre o reservatório e qualquer ponto da bacia
    boundary = bacia_utm.boundary
    if boundary.geom_type == 'MultiLineString':
        all_coords = [c for line in boundary.geoms for c in line.coords]
    else:
        all_coords = list(boundary.coords)
    R = max(ponto_utm.distance(Point(c)) for c in all_coords)

    # Raios das coroas: r_k = R * k/n (raios igualmente espaçados)
    raios = [R * k / n_coroas for k in range(1, n_coroas + 1)]

    # Gerar coroas em UTM
    coroas_utm = []
    for k in range(n_coroas):
        circulo_externo = ponto_utm.buffer(raios[k])
        if k == 0:
            anel = circulo_externo  # disco central
        else:
            circulo_interno = ponto_utm.buffer(raios[k - 1])
            anel = circulo_externo.difference(circulo_interno)

        # Clipar com a bacia
        intersecao = anel.intersection(bacia_utm)
        coroas_utm.append(intersecao)

    # Reprojetar para EPSG:4326
    gs_coroas = gpd.GeoSeries(coroas_utm, crs=utm_crs)
    gs_coroas_4326 = gs_coroas.to_crs("EPSG:4326")

    # Retornar lista, com None para geometrias vazias
    resultado = []
    for geom in gs_coroas_4326:
        if geom is None or geom.is_empty:
            resultado.append(None)
        else:
            resultado.append(geom)

    return resultado


def processar_coroas(merge_dir: Path, shapefile_dir: Path,
                     data_inicio: datetime, data_fim: datetime,
                     df_res, n_coroas: int = 5):
    """
    Processa todos os arquivos MERGE extraindo precipitação por coroas.

    Args:
        df_res: DataFrame de reservatórios (schema nome/lat_dam/lon_dam).

    Returns:
        pd.DataFrame com colunas {NOME}_coroa1 ... {NOME}_coroa5
    """
    import rioxarray  # noqa

    # Carregar shapefiles das bacias
    print("Carregando shapefiles das bacias...")
    bacias = carregar_shapefiles_bacias(shapefile_dir, df_res)
    print(f"Bacias carregadas: {len(bacias)}/{len(df_res)}")

    if len(bacias) == 0:
        print("ERRO: Nenhum shapefile encontrado!")
        sys.exit(1)

    # Gerar geometrias das coroas para cada reservatório
    print(f"\nGerando {n_coroas} coroas por reservatório...")
    coroas_por_reservatorio = {}

    for _, res in df_res.iterrows():
        nome = res['nome']
        if nome not in bacias:
            print(f"  AVISO: Sem shapefile para {nome}, pulando.")
            continue

        geometria_bacia = bacias[nome].geometry.union_all()
        coroas = calcular_geometrias_coroas(
            geometria_bacia, res['lat_dam'], res['lon_dam'], n_coroas
        )

        coroas_por_reservatorio[nome] = coroas

        # Info de diagnóstico
        n_validas = sum(1 for c in coroas if c is not None)
        print(f"  {nome}: {n_validas}/{n_coroas} coroas com interseção")

    # Listar e filtrar arquivos MERGE (busca recursiva: merge/ANO/MES/*.grib2)
    arquivos = sorted(glob.glob(str(merge_dir / "**" / "MERGE_CPTEC_*.grib2"),
                                recursive=True))
    if not arquivos:  # fallback: arquivos diretamente no merge_dir
        arquivos = sorted(glob.glob(str(merge_dir / "MERGE_CPTEC_*.grib2")))
    arquivos_periodo = []
    for arq in arquivos:
        data = extrair_data_do_filename(arq)
        if data and data_inicio <= data <= data_fim:
            arquivos_periodo.append((data, arq))

    arquivos_periodo.sort(key=lambda x: x[0])
    print(f"\nProcessando {len(arquivos_periodo)} arquivos MERGE...")

    # Definir nomes das colunas
    colunas = []
    for _, res in df_res.iterrows():
        nome = res['nome']
        if nome in coroas_por_reservatorio:
            for k in range(1, n_coroas + 1):
                colunas.append(f"{nome}_coroa{k}")

    # Processar
    resultados = []

    for data, filepath in tqdm(arquivos_periodo, desc="Processando MERGE"):
        da = ler_merge_grib2(filepath)
        if da is None:
            row = {"data": data}
            for col in colunas:
                row[col] = np.nan
            resultados.append(row)
            continue

        # Ajustar longitude de 0-360 para -180-180
        da = ajustar_longitude_360_para_180(da)

        row = {"data": data}
        for nome, coroas in coroas_por_reservatorio.items():
            for k, geom_coroa in enumerate(coroas):
                col_name = f"{nome}_coroa{k+1}"
                if geom_coroa is None:
                    row[col_name] = np.nan
                else:
                    row[col_name] = extrair_precip_shapefile(da, geom_coroa)

        resultados.append(row)

    df = pd.DataFrame(resultados)
    df['data'] = pd.to_datetime(df['data'])
    df = df.set_index('data').sort_index()

    return df


def main():
    parser = argparse.ArgumentParser(
        description="Extração de precipitação por coroas circulares clipadas com a bacia"
    )
    parser.add_argument("--merge-dir", type=str, required=True,
                        help="Diretório com arquivos MERGE GRIB2")
    parser.add_argument("--shapefile-dir", type=str, default="./dados/bacias",
                        help="Diretório com shapefiles das bacias")
    parser.add_argument("--output", type=str,
                        default="./dados/precipitacao_coroas_30res.csv",
                        help="Arquivo CSV de saída")
    parser.add_argument("--inicio", type=str, default="2000-06-01",
                        help="Data início (YYYY-MM-DD)")
    parser.add_argument("--fim", type=str, default="2026-01-31",
                        help="Data fim (YYYY-MM-DD)")
    parser.add_argument("--n-coroas", type=int, default=5,
                        help="Número de coroas concêntricas (default: 5)")
    parser.add_argument("--reservatorios-csv", type=str,
                        default="./dados/coordenadasUHEs_clustering.csv",
                        help="CSV com a lista de reservatórios (nome_uhe,lat,long)")

    args = parser.parse_args()

    from reservatorios_clustering import get_reservatorios_df
    df_res = get_reservatorios_df(args.reservatorios_csv)
    print(f"Reservatórios carregados do CSV: {len(df_res)} ({args.reservatorios_csv})")

    merge_dir = Path(args.merge_dir)
    output_path = Path(args.output)
    data_inicio = datetime.strptime(args.inicio, "%Y-%m-%d")
    data_fim = datetime.strptime(args.fim, "%Y-%m-%d")

    if not merge_dir.exists():
        print(f"ERRO: Diretório {merge_dir} não encontrado!")
        sys.exit(1)

    print("=" * 60)
    print(f"EXTRAÇÃO POR COROAS CIRCULARES ({args.n_coroas} coroas)")
    print(f"Período: {args.inicio} a {args.fim}")
    print("=" * 60)

    df = processar_coroas(merge_dir, Path(args.shapefile_dir),
                          data_inicio, data_fim, df_res=df_res,
                          n_coroas=args.n_coroas)

    # Salvar
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, float_format="%.2f")
    print(f"\nDados salvos em: {output_path}")
    print(f"Dimensões: {df.shape[0]} dias × {df.shape[1]} colunas")

    # Resumo
    n_res = len(set(c.rsplit('_coroa', 1)[0] for c in df.columns))
    print(f"Reservatórios: {n_res}")
    print(f"Coroas por reservatório: {args.n_coroas}")
    print(f"NaN total: {df.isna().sum().sum()} "
          f"({100*df.isna().sum().sum()/(df.shape[0]*df.shape[1]):.1f}%)")


if __name__ == "__main__":
    main()
