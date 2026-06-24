"""
Extração de evapotranspiração (ERA5-Land) por coroas circulares concêntricas
clipadas com a bacia — espelha extrair_precip_coroas.py para o MERGE.

A geometria das coroas e o recorte/média ponderada por cos(lat) são REUTILIZADOS
de extrair_precip_coroas (mesma grade 0.1°, EPSG:4326). A única diferença é o I/O:
o ERA5-Land vem em NetCDF ANUAL com dimensão `time`, então iteramos sobre os dias
de cada arquivo (em vez de "1 arquivo GRIB2 = 1 dia" do MERGE).

Resultado: 5 colunas de ET por reservatório (180 colunas), em mm/dia.

Uso:
   py extrair_et_coroas.py --era5-dir ./dados/era5land --shapefile-dir ./dados/bacias_clustering --inicio 2000-01-01 --fim 2025-12-31 --output ./dados/evapotranspiracao_coroas.csv
"""

import sys
import glob
import argparse
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr
from tqdm import tqdm

# Reaproveita toda a lógica geométrica e de recorte do pipeline de precipitação
from extrair_precip_coroas import (
    carregar_shapefiles_bacias,
    extrair_precip_shapefile,
    ajustar_longitude_360_para_180,
    calcular_geometrias_coroas,
)

warnings.filterwarnings('ignore', category=FutureWarning)


def ler_era5land_netcdf(filepath, variavel=None):
    """
    Lê um NetCDF do ERA5-Land (passo 00:00) e retorna o DataArray de ET em mm/dia.

    - Seleciona a variável (pev por padrão; 'e' para ET real).
    - Normaliza o nome da coordenada temporal (valid_time -> time).
    - REETIQUETA o tempo em -1 dia: no ERA5-Land o campo às 00:00 UTC do dia D é o
      total ACUMULADO do dia D-1 (ver download_era5land.py). Assim a data passa a
      identificar corretamente o dia ao qual o total se refere.
    - Converte de m de água equivalente para mm e torna o valor positivo:
      pev/e são acumulações de sinal NEGATIVO, então usamos abs()*1000.
    - Ajusta longitude 0-360 -> -180-180 se necessário (reuso do MERGE).

    Returns:
        xr.DataArray com dims (time, latitude, longitude) em mm/dia (>= 0).
    """
    ds = xr.open_dataset(filepath)

    # Normalizar coordenada temporal (CDS novo costuma usar 'valid_time')
    for tname in ("valid_time", "time"):
        if tname in ds.coords and tname != "time":
            ds = ds.rename({tname: "time"})
            break

    # Selecionar variável
    if variavel and variavel in ds.data_vars:
        da = ds[variavel]
    elif 'pev' in ds.data_vars:
        da = ds['pev']
    elif 'e' in ds.data_vars:
        da = ds['e']
    else:
        da = ds[list(ds.data_vars)[0]]

    # 00:00 do dia D = total do dia D-1 -> reetiquetar para o dia correto
    if 'time' in da.coords:
        da = da.assign_coords(time=da['time'] - pd.Timedelta(days=1))

    # m -> mm. Convenção ECMWF: fluxo positivo p/ baixo, então evaporação (e/pev) é
    # NEGATIVA. A ET é a perda evaporativa = -e; valores positivos (condensação) -> 0.
    da = (-1000.0 * da).clip(min=0)

    # Mesmo ajuste de longitude usado no MERGE
    da = ajustar_longitude_360_para_180(da)

    return da


def _gerar_coroas_por_reservatorio(shapefile_dir, df_res, n_coroas):
    """Carrega bacias e gera as coroas por reservatório (idêntico ao pipeline MERGE)."""
    print("Carregando shapefiles das bacias...")
    bacias = carregar_shapefiles_bacias(shapefile_dir, df_res)
    print(f"Bacias carregadas: {len(bacias)}/{len(df_res)}")
    if len(bacias) == 0:
        print("ERRO: Nenhum shapefile encontrado!")
        sys.exit(1)

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
        n_validas = sum(1 for c in coroas if c is not None)
        print(f"  {nome}: {n_validas}/{n_coroas} coroas com interseção")
    return coroas_por_reservatorio


def processar_coroas_et(era5_dir: Path, shapefile_dir: Path,
                        data_inicio: datetime, data_fim: datetime,
                        df_res, n_coroas: int = 5, variavel=None):
    """
    Processa os NetCDF anuais do ERA5-Land extraindo ET por coroas.

    Returns:
        pd.DataFrame indexado por data, colunas {NOME}_coroa1 ... {NOME}_coroa5 (mm/dia).
    """
    import rioxarray  # noqa

    coroas_por_reservatorio = _gerar_coroas_por_reservatorio(
        shapefile_dir, df_res, n_coroas
    )

    # Listar NetCDF (busca recursiva; fallback flat)
    arquivos = sorted(glob.glob(str(era5_dir / "**" / "*.nc"), recursive=True))
    if not arquivos:
        arquivos = sorted(glob.glob(str(era5_dir / "*.nc")))
    print(f"\nArquivos NetCDF encontrados: {len(arquivos)}")

    resultados = []
    for fp in tqdm(arquivos, desc="Processando ERA5-Land"):
        try:
            da_ano = ler_era5land_netcdf(fp, variavel).load()
        except Exception as e:
            print(f"  Erro ao ler {fp}: {e}")
            continue

        if 'time' not in da_ano.dims:
            # arquivo com um único passo de tempo
            da_ano = da_ano.expand_dims('time')

        for i in range(da_ano.sizes['time']):
            da_dia = da_ano.isel(time=i)
            data = pd.Timestamp(da_dia['time'].values).to_pydatetime().replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            if not (data_inicio <= data <= data_fim):
                continue

            row = {"data": data}
            for nome, coroas in coroas_por_reservatorio.items():
                for k, geom_coroa in enumerate(coroas):
                    col_name = f"{nome}_coroa{k+1}"
                    if geom_coroa is None:
                        row[col_name] = np.nan
                    else:
                        row[col_name] = extrair_precip_shapefile(da_dia, geom_coroa)
            resultados.append(row)

    df = pd.DataFrame(resultados)
    if df.empty:
        print("AVISO: nenhum dia processado no período informado.")
        return df
    df['data'] = pd.to_datetime(df['data'])
    df = df.set_index('data').sort_index()
    return df


def main():
    # Evita UnicodeEncodeError no Windows ao redirecionar o stdout p/ arquivo (cp1252)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    parser = argparse.ArgumentParser(
        description="Extração de evapotranspiração (ERA5-Land) por coroas clipadas com a bacia"
    )
    parser.add_argument("--era5-dir", type=str, default="./dados/era5land",
                        help="Diretório com os NetCDF anuais do ERA5-Land")
    parser.add_argument("--shapefile-dir", type=str, default="./dados/bacias_clustering",
                        help="Diretório com shapefiles das bacias")
    parser.add_argument("--output", type=str,
                        default="./dados/evapotranspiracao_coroas.csv",
                        help="Arquivo CSV de saída")
    parser.add_argument("--inicio", type=str, default="2000-01-01",
                        help="Data início (YYYY-MM-DD)")
    parser.add_argument("--fim", type=str, default="2025-12-31",
                        help="Data fim (YYYY-MM-DD)")
    parser.add_argument("--n-coroas", type=int, default=5,
                        help="Número de coroas concêntricas (default: 5)")
    parser.add_argument("--variavel", type=str, default=None,
                        help="Nome da variável no NetCDF (pev por padrão; 'e' p/ ET real)")
    parser.add_argument("--reservatorios-csv", type=str,
                        default="./dados/coordenadasUHEs_clustering.csv",
                        help="CSV com a lista de reservatórios")
    args = parser.parse_args()

    from reservatorios_clustering import get_reservatorios_df
    df_res = get_reservatorios_df(args.reservatorios_csv)
    print(f"Reservatórios carregados do CSV: {len(df_res)} ({args.reservatorios_csv})")

    era5_dir = Path(args.era5_dir)
    output_path = Path(args.output)
    data_inicio = datetime.strptime(args.inicio, "%Y-%m-%d")
    data_fim = datetime.strptime(args.fim, "%Y-%m-%d")

    if not era5_dir.exists():
        print(f"ERRO: Diretório {era5_dir} não encontrado! Rode download_era5land.py antes.")
        sys.exit(1)

    print("=" * 60)
    print(f"EXTRAÇÃO DE ET POR COROAS CIRCULARES ({args.n_coroas} coroas)")
    print(f"Período: {args.inicio} a {args.fim}")
    print("=" * 60)

    df = processar_coroas_et(era5_dir, Path(args.shapefile_dir),
                             data_inicio, data_fim, df_res=df_res,
                             n_coroas=args.n_coroas, variavel=args.variavel)

    if df.empty:
        sys.exit(1)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, float_format="%.2f")
    print(f"\nDados salvos em: {output_path}")
    print(f"Dimensões: {df.shape[0]} dias × {df.shape[1]} colunas")

    n_res = len(set(c.rsplit('_coroa', 1)[0] for c in df.columns))
    print(f"Reservatórios: {n_res}")
    print(f"Coroas por reservatório: {args.n_coroas}")
    print(f"NaN total: {df.isna().sum().sum()} "
          f"({100*df.isna().sum().sum()/(df.shape[0]*df.shape[1]):.1f}%)")
    print(f"ET média (mm/dia): {df.mean().mean():.2f}")


if __name__ == "__main__":
    main()