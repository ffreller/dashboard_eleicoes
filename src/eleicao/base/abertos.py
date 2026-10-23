"""Leitura dos arquivos de dados abertos do TSE (votação e detalhe da apuração por seção, cargo Presidente).

Os CSVs vêm zipados, em latin-1, separados por ";". Colunas que um ano não publica (2014 não tem
nome nem endereço do local) viram nulas. Cada um é convertido uma vez para parquet em
data/raw/parquet/, só com as linhas de Presidente e as colunas usadas, e lido de lá nas vezes seguintes.
"""

import io
import shutil
import zipfile
from pathlib import Path

import polars as pl

from eleicao.config import BRUTOS

CDN = "https://cdn.tse.jus.br/estatistica/sead/odsele"

CHAVE = ["uf", "mun", "zona", "secao"]

_VOTACAO = {
    "NR_TURNO": ("turno", pl.Int8),
    "SG_UF": ("uf", pl.String),
    "CD_MUNICIPIO": ("mun", pl.Int32),
    "NM_MUNICIPIO": ("nm_mun", pl.String),
    "NR_ZONA": ("zona", pl.Int32),
    "NR_SECAO": ("secao", pl.Int32),
    "NR_VOTAVEL": ("numero", pl.Int32),
    "QT_VOTOS": ("votos", pl.Int32),
    "NR_LOCAL_VOTACAO": ("local", pl.Int32),
    "NM_LOCAL_VOTACAO": ("nm_local", pl.String),
    "DS_LOCAL_VOTACAO_ENDERECO": ("endereco", pl.String),
}

_DETALHE = {
    "NR_TURNO": ("turno", pl.Int8),
    "SG_UF": ("uf", pl.String),
    "CD_MUNICIPIO": ("mun", pl.Int32),
    "NM_MUNICIPIO": ("nm_mun", pl.String),
    "NR_ZONA": ("zona", pl.Int32),
    "NR_SECAO": ("secao", pl.Int32),
    "QT_APTOS": ("aptos", pl.Int32),
    "QT_COMPARECIMENTO": ("comparecimento", pl.Int32),
    "QT_VOTOS_BRANCOS": ("brancos", pl.Int32),
    "QT_VOTOS_NULOS": ("nulos", pl.Int32),
    "NR_LOCAL_VOTACAO": ("local", pl.Int32),
    "NM_LOCAL_VOTACAO": ("nm_local", pl.String),
    "DS_LOCAL_VOTACAO_ENDERECO": ("endereco", pl.String),
    "DT_PRIM_TOT_PARCIAL_HOR_TSE": ("hora", pl.String),
    "ST_SECAO_INSTALADA": ("instalada", pl.String),
    "ST_SECAO_ANULADA": ("anulada", pl.String),
}


def _zip(nome: str, url: str) -> Path:
    destino = BRUTOS / nome
    if not destino.exists():
        import httpx

        destino.parent.mkdir(parents=True, exist_ok=True)
        tmp = destino.with_suffix(".parcial")
        with httpx.stream("GET", url, follow_redirects=True, timeout=120) as r, open(tmp, "wb") as f:
            r.raise_for_status()
            for bloco in r.iter_bytes(1 << 20):
                f.write(bloco)
        tmp.rename(destino)
    return destino


def _csv_utf8(zip_path: Path, membro: str) -> Path:
    destino = BRUTOS / "csv" / membro
    if not destino.exists():
        destino.parent.mkdir(parents=True, exist_ok=True)
        tmp = destino.with_suffix(".parcial")
        with zipfile.ZipFile(zip_path) as z, z.open(membro) as bruto, open(tmp, "w", encoding="utf-8") as saida:
            shutil.copyfileobj(io.TextIOWrapper(bruto, encoding="latin-1", newline=""), saida, 1 << 24)
        tmp.rename(destino)
    return destino


def _parquet(nome: str, zip_path: Path, membro: str, colunas: dict) -> pl.DataFrame:
    destino = BRUTOS / "parquet" / f"{nome}.parquet"
    if not destino.exists():
        destino.parent.mkdir(parents=True, exist_ok=True)
        csv = _csv_utf8(zip_path, membro)
        lf = pl.scan_csv(csv, separator=";", infer_schema=False)
        presentes = set(lf.collect_schema().names())
        lf = (
            lf.filter(pl.col("CD_CARGO").cast(pl.Int32) == 1)
            .select(
                (pl.col(orig) if orig in presentes else pl.lit(None)).cast(tipo).alias(novo)
                for orig, (novo, tipo) in colunas.items()
            )
            .with_columns(pl.col("uf").str.to_lowercase())
        )
        lf.sink_parquet(destino)
        csv.unlink()
    return pl.read_parquet(destino)


def votacao(ano: int) -> pl.DataFrame:
    """Votos por seção e número votado (inclui 95 branco e 96 nulo), os dois turnos."""
    z = _zip(f"votacao_secao_{ano}_BR.zip", f"{CDN}/votacao_secao/votacao_secao_{ano}_BR.zip")
    return _parquet(f"votacao_{ano}", z, f"votacao_secao_{ano}_BR.csv", _VOTACAO)


def votos_por_secao(ano: int, turno: int, esq: int, dir: int) -> pl.DataFrame:
    """Votos de `esq`, de `dir` e dos demais candidatos (`outros`, sem branco e nulo), por seção, mais o local de votação."""
    nominal = ~pl.col("numero").is_in([95, 96, 97])
    return (
        votacao(ano)
        .filter(pl.col("turno") == turno)
        .group_by(CHAVE)
        .agg(
            pl.col("votos").filter(pl.col("numero") == esq).sum().alias("esq"),
            pl.col("votos").filter(pl.col("numero") == dir).sum().alias("dir"),
            pl.col("votos").filter(nominal & ~pl.col("numero").is_in([esq, dir])).sum().alias("outros"),
            pl.col("local").first(),
            pl.col("nm_local").first(),
            pl.col("endereco").first(),
        )
    )


def detalhe(ano: int) -> pl.DataFrame:
    """Aptos, comparecimento, brancos, nulos, local de votação e hora de totalização por seção."""
    z = _zip(f"detalhe_votacao_secao_{ano}.zip", f"{CDN}/detalhe_votacao_secao/detalhe_votacao_secao_{ano}.zip")
    df = _parquet(f"detalhe_{ano}", z, f"detalhe_votacao_secao_{ano}_BR.csv", _DETALHE)
    return df.with_columns(pl.col("hora").str.strptime(pl.Datetime, "%d/%m/%Y %H:%M:%S", strict=False))
