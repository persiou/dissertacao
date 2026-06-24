"""
Download MERGE (precipitação diária)

Uso:
  py download_merge_https.py --inicio 2025-01-01 --fim 2026-01-31 --destino ./dados/merge
  py download_merge_https.py --verificar --inicio 2000-06-01 --fim 2026-01-31 --destino ./dados/merge
"""

import os
import argparse
import requests
from datetime import datetime, timedelta
from pathlib import Path
from tqdm import tqdm

BASE_URL = "https://ftp.cptec.inpe.br/modelos/tempo/MERGE/GPM/DAILY"


def download_arquivo(url, filepath):
    """Baixa um arquivo via HTTPS. Retorna True se sucesso."""
    try:
        resp = requests.get(url, timeout=60, stream=True)
        if resp.status_code == 200:
            with open(filepath, 'wb') as f:
                for chunk in resp.iter_content(chunk_size=1024 * 64):
                    if chunk:
                        f.write(chunk)
            # Verificar se não é uma página HTML de erro
            if filepath.stat().st_size < 1000:
                with open(filepath, 'rb') as f:
                    inicio = f.read(20)
                if b'<' in inicio or b'html' in inicio.lower():
                    filepath.unlink()
                    return False
            return True
        return False
    except Exception:
        if filepath.exists():
            filepath.unlink()
        return False


def download_incremental(destino, data_inicio, data_fim):
    """Baixa arquivos diários do MERGE via HTTPS."""
    destino = Path(destino)
    destino.mkdir(parents=True, exist_ok=True)

    # Gerar lista de datas
    datas = []
    dt = data_inicio
    while dt <= data_fim:
        datas.append(dt)
        dt += timedelta(days=1)

    # Verificar quais já existem
    faltantes = []
    for dt in datas:
        fname = f"MERGE_CPTEC_{dt:%Y%m%d}.grib2"
        if not (destino / fname).exists():
            faltantes.append(dt)

    print(f"Periodo: {data_inicio:%Y-%m-%d} a {data_fim:%Y-%m-%d}")
    print(f"Total de dias: {len(datas)}")
    print(f"Ja baixados: {len(datas) - len(faltantes)}")
    print(f"Faltam: {len(faltantes)}")

    if not faltantes:
        print("Tudo ja baixado!")
        return

    baixados = 0
    erros = []

    for dt in tqdm(faltantes, desc="Baixando MERGE"):
        fname = f"MERGE_CPTEC_{dt:%Y%m%d}.grib2"
        filepath = destino / fname

        # Tentar URL direta (flat) e com subdiretório por ano/mes
        urls_tentativas = [
            f"{BASE_URL}/{fname}",
            f"{BASE_URL}/{dt.year}/{dt:%m}/{fname}",
            f"{BASE_URL}/{dt.year}/{fname}",
        ]

        sucesso = False
        for url in urls_tentativas:
            if download_arquivo(url, filepath):
                baixados += 1
                sucesso = True
                break

        if not sucesso:
            erros.append(dt)

    print(f"\nConcluido! Baixados: {baixados} | Erros: {len(erros)}")
    if erros and len(erros) <= 20:
        print(f"Datas com erro: {[d.strftime('%Y-%m-%d') for d in erros]}")
    elif erros:
        print(f"Primeiros erros: {[d.strftime('%Y-%m-%d') for d in erros[:10]]}...")


def verificar_completude(destino, data_inicio, data_fim):
    """Verifica quais datas estão faltando."""
    destino = Path(destino)
    faltando = []
    dt = data_inicio
    total = 0
    while dt <= data_fim:
        total += 1
        fname = f"MERGE_CPTEC_{dt:%Y%m%d}.grib2"
        if not (destino / fname).exists():
            faltando.append(dt)
        dt += timedelta(days=1)

    print(f"\nVerificacao de completude:")
    print(f"  Periodo: {data_inicio:%Y-%m-%d} a {data_fim:%Y-%m-%d}")
    print(f"  Esperados: {total}")
    print(f"  Presentes: {total - len(faltando)}")
    print(f"  Faltando:  {len(faltando)}")

    if faltando and len(faltando) <= 30:
        print(f"  Datas: {[d.strftime('%Y-%m-%d') for d in faltando]}")
    elif faltando:
        print(f"  Primeiras: {[d.strftime('%Y-%m-%d') for d in faltando[:15]]}...")


def main():
    parser = argparse.ArgumentParser(description="Download MERGE via HTTPS")
    parser.add_argument("--destino", type=str, default="./dados/merge")
    parser.add_argument("--inicio", type=str, default="2025-01-01")
    parser.add_argument("--fim", type=str, default="2026-01-31")
    parser.add_argument("--verificar", action="store_true",
                        help="Apenas verificar completude, sem baixar")

    args = parser.parse_args()
    data_inicio = datetime.strptime(args.inicio, "%Y-%m-%d")
    data_fim = datetime.strptime(args.fim, "%Y-%m-%d")

    if args.verificar:
        verificar_completude(args.destino, data_inicio, data_fim)
    else:
        download_incremental(args.destino, data_inicio, data_fim)


if __name__ == "__main__":
    main()