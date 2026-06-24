"""
Download ERA5-Land (evapotranspiração diária) via Copernicus CDS.

Produto único e homogêneo cobrindo 2000-2025, na mesma grade 0.1° do MERGE.
Variável padrão: potential_evaporation (pev) — análoga ao ETo de referência.
Para ET "real" use --variavel total_evaporation (e).

Baixa um NetCDF por ANO do produto horário `reanalysis-era5-land`, pegando APENAS
o passo das 00:00 UTC de cada dia (1 campo/dia → arquivos leves).

--- IMPORTANTE: acumulação, passo 00:00 e sinal ---
pev é uma variável ACUMULADA. No ERA5-Land a acumulação reinicia a cada dia (00 UTC),
e a convenção é: o campo às 00:00 UTC do dia D contém o TOTAL ACUMULADO do dia D-1.
Por isso baixamos só o passo 00:00 (total diário pronto) e o leitor
(extrair_et_coroas.ler_era5land_netcdf) reetiqueta o tempo em -1 dia e aplica
abs()*1000 → mm/dia > 0.
(O serviço derived-era5-land-daily-statistics NÃO suporta variáveis acumuladas,
por isso não é usado aqui.)

Obs. de cobertura: o campo 00:00 de 01/jan/(ano+1) é o total de 31/dez/(ano). Por isso,
para fechar o último dia do período, baixamos também 01/jan do ano seguinte ao --fim.

--- Pré-requisitos (uma vez) ---
1. Conta gratuita no Copernicus CDS: https://cds.climate.copernicus.eu/
2. Arquivo ~/.cdsapirc com:
       url: https://cds.climate.copernicus.eu/api
       key: <SEU_TOKEN>
3. Aceitar a licença do dataset reanalysis-era5-land na página do CDS (uma vez).
4. pip install cdsapi

Uso:
  py download_era5land.py --inicio 2000 --fim 2025 --destino ./dados/era5land
  py download_era5land.py --inicio 2010 --fim 2010 --destino ./dados/era5land   # 1 ano de teste
"""

import argparse
from pathlib import Path

# Bounding box do Brasil (com folga): [Norte, Oeste, Sul, Leste]
AREA_BRASIL = [6.0, -75.0, -35.0, -33.0]

DATASET = "reanalysis-era5-land"

MESES = [f"{m:02d}" for m in range(1, 13)]
DIAS = [f"{d:02d}" for d in range(1, 32)]


def _tag(variavel: str) -> str:
    return "eto" if variavel == "potential_evaporation" else "et"


def baixar_ano(client, ano: int, destino: Path, variavel: str, area) -> Path | None:
    """Baixa um NetCDF anual (passo 00:00 de cada dia). Retorna o caminho ou None."""
    filepath = destino / f"era5land_{_tag(variavel)}_{ano}.nc"
    if filepath.exists() and filepath.stat().st_size > 1000:
        print(f"  {ano}: já existe ({filepath.name}), pulando.")
        return filepath

    request = {
        "variable": [variavel],
        "year": str(ano),
        "month": MESES,
        "day": DIAS,
        "time": ["00:00"],
        "area": area,
        "data_format": "netcdf",
        "download_format": "unarchived",
    }
    try:
        client.retrieve(DATASET, request).download(str(filepath))
        print(f"  {ano}: OK -> {filepath.name}")
        return filepath
    except Exception as e:
        print(f"  {ano}: ERRO -> {e}")
        if filepath.exists():
            filepath.unlink()
        return None


def baixar_dia_fronteira(client, ano: int, destino: Path, variavel: str, area) -> Path | None:
    """Baixa o campo 00:00 de 01/jan/ano (= total de 31/dez/ano-1) para fechar a série."""
    filepath = destino / f"era5land_{_tag(variavel)}_fronteira_{ano}0101.nc"
    if filepath.exists() and filepath.stat().st_size > 1000:
        print(f"  fronteira {ano}-01-01: já existe, pulando.")
        return filepath

    request = {
        "variable": [variavel],
        "year": str(ano),
        "month": ["01"],
        "day": ["01"],
        "time": ["00:00"],
        "area": area,
        "data_format": "netcdf",
        "download_format": "unarchived",
    }
    try:
        client.retrieve(DATASET, request).download(str(filepath))
        print(f"  fronteira {ano}-01-01: OK -> {filepath.name}")
        return filepath
    except Exception as e:
        print(f"  fronteira {ano}-01-01: ERRO -> {e}")
        if filepath.exists():
            filepath.unlink()
        return None


def main():
    parser = argparse.ArgumentParser(description="Download ERA5-Land ET diária via CDS")
    parser.add_argument("--destino", type=str, default="./dados/era5land")
    parser.add_argument("--inicio", type=int, default=2000, help="Ano inicial")
    parser.add_argument("--fim", type=int, default=2025, help="Ano final")
    parser.add_argument("--variavel", type=str, default="total_evaporation",
                        choices=["potential_evaporation", "total_evaporation"],
                        help="e = total_evaporation (ET real, padrão) ou pev (ET potencial; "
                             "superestima muito no ERA5-Land)")
    args = parser.parse_args()

    try:
        import cdsapi
    except ImportError:
        raise SystemExit("Falta a lib cdsapi. Rode: pip install cdsapi")

    destino = Path(args.destino)
    destino.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("DOWNLOAD ERA5-Land (ET diária, passo 00:00) via CDS")
    print(f"Dataset: {DATASET} | variável: {args.variavel}")
    print(f"Período: {args.inicio} a {args.fim} | área: {AREA_BRASIL}")
    print("=" * 60)

    client = cdsapi.Client()

    ok, falhas = 0, []
    for ano in range(args.inicio, args.fim + 1):
        res = baixar_ano(client, ano, destino, args.variavel, AREA_BRASIL)
        if res is not None:
            ok += 1
        else:
            falhas.append(ano)

    # Fecha o último dia do período (31/dez/fim) via 01/jan/(fim+1)
    baixar_dia_fronteira(client, args.fim + 1, destino, args.variavel, AREA_BRASIL)

    print(f"\nConcluído! Anos OK: {ok} | Falhas: {falhas if falhas else 'nenhuma'}")
    if falhas:
        print("Anos com falha podem ainda não estar consolidados ou exigir nova "
              "execução (fila do CDS). Rode novamente — anos já baixados são pulados.")


if __name__ == "__main__":
    main()