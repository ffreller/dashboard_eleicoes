"""O que já foi totalizado, por Brasil e UF, sem projeção."""

import numpy as np

from eleicao.tipos import Apuracao, Base, Recorte


def recortes_apurados(base: Base, ap: Apuracao) -> tuple[Recorte, dict[str, Recorte]]:
    """Brasil e cada UF só com o que já foi totalizado, sem projeção."""
    uf_mun = base.municipios["uf"].to_numpy()
    secoes_mun = np.bincount(base.mun_idx, minlength=base.n_municipios)
    aptos_mun = np.bincount(base.mun_idx, weights=base.col("aptos"), minlength=base.n_municipios)

    def recorte(m: np.ndarray) -> Recorte:
        validos = int(ap.esq[m].sum() + ap.dir[m].sum())
        return Recorte(
            pct_secoes=100 * ap.secoes[m].sum() / secoes_mun[m].sum(),
            pct_aptos=100 * ap.aptos[m].sum() / aptos_mun[m].sum(),
            apurado=100 * ap.esq[m].sum() / validos if validos else None,
            votos_validos=validos,
            projecao=None,
        )

    todos = np.ones(base.n_municipios, dtype=bool)
    return recorte(todos), {uf: recorte(uf_mun == uf) for uf in np.unique(uf_mun)}
