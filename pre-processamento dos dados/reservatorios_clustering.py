"""
Loader dos reservatórios usados no agrupamento (spectral clustering).

Lê a lista nova de reservatórios a partir de um CSV (coordenadasUHEs_clustering.csv)
e devolve um DataFrame no MESMO schema esperado pelo restante do pipeline
(extract_precipitation.py, extract_precipitation_coroas.py, gerar_bacias_ottobacias.py):

    nome, rio, uf, lat_dam, lon_dam, buffer_deg

O CSV de entrada precisa ter, no mínimo, colunas de nome e coordenadas. São aceitos
vários nomes de coluna (nome_uhe/nome, lat, long/lon/lon_dam). Colunas ausentes
(rio, uf, buffer_deg) são preenchidas com valores padrão — rio/uf vazios fazem a
geração de bacias cair no trecho de drenagem mais próximo, e buffer_deg só é usado
como fallback quando não há shapefile da bacia.
"""

from pathlib import Path

import pandas as pd

# CSV padrão (copiado para dentro de ./dados para o pipeline ficar autossuficiente)
CSV_PADRAO = Path(__file__).parent / "dados" / "coordenadasUHEs_clustering.csv"

# Buffer padrão (graus) usado apenas como fallback se faltar shapefile da bacia
BUFFER_DEG_PADRAO = 1.0


def get_reservatorios_df(csv_path: Path = CSV_PADRAO) -> pd.DataFrame:
    """Retorna DataFrame dos reservatórios no schema do pipeline."""
    csv_path = Path(csv_path)
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV de reservatórios não encontrado: {csv_path}")

    df = pd.read_csv(csv_path)

    # Normalizar nomes de coluna
    rename = {}
    for col in df.columns:
        c = col.strip().lower()
        if c in ("nome_uhe", "nome", "nm_usina", "usina"):
            rename[col] = "nome"
        elif c in ("lat", "latitude", "lat_dam"):
            rename[col] = "lat_dam"
        elif c in ("long", "lon", "longitude", "lon_dam"):
            rename[col] = "lon_dam"
        elif c == "rio":
            rename[col] = "rio"
        elif c in ("uf", "estado"):
            rename[col] = "uf"
    df = df.rename(columns=rename)

    faltando = {"nome", "lat_dam", "lon_dam"} - set(df.columns)
    if faltando:
        raise ValueError(
            f"CSV {csv_path.name} não tem colunas obrigatórias: {faltando}. "
            f"Colunas encontradas: {list(df.columns)}"
        )

    # Preencher colunas opcionais
    if "rio" not in df.columns:
        df["rio"] = ""
    if "uf" not in df.columns:
        df["uf"] = ""
    if "buffer_deg" not in df.columns:
        df["buffer_deg"] = BUFFER_DEG_PADRAO

    df["nome"] = df["nome"].astype(str).str.strip()
    df["rio"] = df["rio"].fillna("").astype(str)
    df["uf"] = df["uf"].fillna("").astype(str)

    return df[["nome", "rio", "uf", "lat_dam", "lon_dam", "buffer_deg"]].reset_index(drop=True)


def print_reservatorios(csv_path: Path = CSV_PADRAO):
    """Imprime tabela formatada dos reservatórios."""
    df = get_reservatorios_df(csv_path)
    print(f"\n{'='*70}")
    print(f"{'RESERVATÓRIO':<30} {'LAT':>10} {'LON':>10} {'BUFFER':>7}")
    print(f"{'='*70}")
    for _, row in df.iterrows():
        print(f"{row['nome']:<30} {row['lat_dam']:>10.4f} {row['lon_dam']:>10.4f} {row['buffer_deg']:>7.1f}")
    print(f"{'='*70}")
    print(f"Total: {len(df)} reservatórios\n")


if __name__ == "__main__":
    print_reservatorios()
