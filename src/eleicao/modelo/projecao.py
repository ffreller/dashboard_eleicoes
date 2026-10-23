"""Projeção do 2º turno: o apurado mais uma estimativa, seção a seção, do que falta.

Para cada seção, a referência é a fração da esquerda entre os dois candidatos no 1º turno, na mesma
seção (em logit). Em cada município que já começou, a mudança ("swing") é a diferença entre o logit do
apurado e o logit da referência das mesmas seções já totalizadas. Uma regressão ponderada explica essa
mudança pelo perfil do lugar (voto nos demais candidatos, diferença para o 2º turno anterior, inclinação
política, capital, porte), com interceptos por região e por UF encolhidos para o nacional. Cada seção que
falta recebe a referência dela mais a mudança prevista para o seu perfil, mais o desvio próprio do seu
município (encolhido conforme quanto dele já foi apurado). O total de votos válidos de cada seção que falta
é o do 1º turno vezes a razão 2º/1º turno medida no município (encolhida para a da UF).

A faixa vem de sorteios: coeficientes da distribuição a posteriori da regressão, desvios de município,
razões de votos válidos (por município e por UF) e choques comuns sobre tudo o que falta. Os sorteios usam
uma semente derivada da própria apuração, para que os mesmos dados deem sempre a mesma faixa.
"""

from dataclasses import dataclass

import numpy as np

from eleicao.config import REGIAO
from eleicao.modelo.apurado import recortes_apurados
from eleicao.tipos import Apuracao, Base, Faixa, Projecao, Recorte


def logit(p: np.ndarray) -> np.ndarray:
    return np.log(p) - np.log1p(-p)


def expit(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


@dataclass(frozen=True)
class Parametros:
    sd_coef: tuple[float, ...] = (0.5, 0.1, 0.1, 1.0, 0.05, 0.02, 0.3, 0.5)
    """Desvio a priori de cada coeficiente do perfil (mesma ordem das colunas de `Modelo.perfil`)."""
    sd_nacional: float = 0.3
    sd_regiao: float = 0.08
    sd_uf: float = 0.08
    sd_municipio: float = 0.024
    """Pisos dos desvios de região, UF e município em relação ao previsto; a apuração pode aumentá-los.
    Região e UF: entre a dispersão medida no 2º turno de 2022 (0,016 e 0,019) e no de 2018 (0,076 e
    0,099), porque um bloco que chega inteiro por último só tem a priori para se apoiar."""
    sobredispersao: float = 3.0
    """Multiplica a variância binomial do swing medido em poucas seções."""
    peso_validos: float = 5000.0
    """Votos com que a razão de válidos da UF entra na estimativa de cada município."""
    sd_validos: float = 0.018
    sd_validos_uf: float = 0.02
    sd_ordem_nacional: float = 0.015
    sd_ordem_uf: float = 0.02
    """Choques comuns no swing de tudo o que falta (no Brasil e em cada UF): o risco de as seções que
    chegam por último mudarem de voto de um jeito que as primeiras não mostram."""
    sorteios: int = 300
    nivel: float = 0.95


NOMES_PERFIL = (
    "outros", "dif_2t_anterior", "inclinacao", "outros_x_inclinacao", "capital", "porte", "abstencao", "brancos_nulos",
)


class Modelo:
    def __init__(self, base: Base, parametros: Parametros = Parametros()):
        self.base = base
        self.par = parametros
        s = base.secoes
        nm = base.n_municipios
        mi = base.mun_idx
        self.mi = mi
        a_esq, a_dir, a_out = (s[c].to_numpy().astype(float) for c in ("a_esq", "a_dir", "a_outros"))
        self.a_esq, self.a_dir = a_esq, a_dir
        self.v1 = a_esq + a_dir + a_out
        self.aptos = s["aptos"].to_numpy().astype(float)
        self.aptos_mun = np.bincount(mi, self.aptos, nm)

        dois_mun = np.bincount(mi, a_esq + a_dir, nm)
        p_mun = np.where(dois_mun > 0, np.bincount(mi, a_esq, nm) / np.maximum(dois_mun, 1), 0.5).clip(0.01, 0.99)
        self.lg_a = logit((a_esq + 2 * p_mun[mi]) / (a_esq + a_dir + 2))
        outros = np.where(self.v1 > 0, a_out / np.maximum(self.v1, 1), 0.0)
        dif = logit(s["b_p"].to_numpy()) - self.lg_a
        m = base.municipios
        capital = m["capital"].to_numpy().astype(float)
        porte = np.log(np.maximum(self.aptos_mun, 1.0))
        compar = s["a_comparecimento"].to_numpy().astype(float)
        abstencao = 1 - compar / np.maximum(self.aptos, 1)
        brancos_nulos = (s["a_brancos"].to_numpy() + s["a_nulos"].to_numpy()) / np.maximum(compar, 1)
        perfil = np.column_stack([
            outros, dif, self.lg_a, outros * self.lg_a, capital[mi], porte[mi], abstencao, brancos_nulos,
        ])
        media = np.average(perfil, axis=0, weights=np.maximum(self.v1, 1e-9))
        self.perfil = perfil - media

        uf_mun = m["uf"].to_numpy()
        self.ufs = np.unique(uf_mun)
        self.uf_idx = np.searchsorted(self.ufs, uf_mun)
        regioes = sorted(set(REGIAO.values()))
        self.reg_idx = np.array([regioes.index(REGIAO[u]) for u in uf_mun])
        self.n_reg, self.n_uf = len(regioes), len(self.ufs)

        k = self.n_perfil = perfil.shape[1]
        sd = np.concatenate([
            parametros.sd_coef, [parametros.sd_nacional],
            np.full(self.n_reg, parametros.sd_regiao), np.full(self.n_uf, parametros.sd_uf),
        ])
        assert len(parametros.sd_coef) == k
        self.precisao_priori = 1.0 / sd**2

    def _efeitos(self, perfil_m: np.ndarray, mun: np.ndarray) -> np.ndarray:
        """Matriz de desenho: perfil, intercepto nacional, região e UF dos municípios `mun`."""
        n = len(mun)
        reg = np.zeros((n, self.n_reg))
        reg[np.arange(n), self.reg_idx[mun]] = 1
        uf = np.zeros((n, self.n_uf))
        uf[np.arange(n), self.uf_idx[mun]] = 1
        return np.column_stack([perfil_m, np.ones(n), reg, uf])

    def projetar(self, ap: Apuracao) -> Projecao:
        brasil, ufs = recortes_apurados(self.base, ap)
        estimativa = self._estimar(ap)
        if estimativa is None:
            return Projecao(momento=ap.momento, brasil=brasil, ufs=ufs)
        centro, sorteios, _ = estimativa
        nome_uf = self.ufs

        def com_faixa(r: Recorte, c: float, amostra: np.ndarray) -> Recorte:
            q = (1 - self.par.nivel) / 2
            lo, hi = np.quantile(amostra, [q, 1 - q])
            f = Faixa(centro=c, baixo=min(lo, c), alto=max(hi, c), chance=100 * float(np.mean(amostra > 50)))
            return Recorte(r.pct_secoes, r.pct_aptos, r.apurado, r.votos_validos, f)

        brasil = com_faixa(brasil, centro[0], sorteios[:, 0])
        ufs = {u: com_faixa(ufs[u], centro[1 + j], sorteios[:, 1 + j]) for j, u in enumerate(nome_uf)}
        return Projecao(momento=ap.momento, brasil=brasil, ufs=ufs)

    def _ajustar(self, z: np.ndarray, swing: np.ndarray, var_amostra: np.ndarray, mun: np.ndarray):
        """Regressão ponderada com priori normal. As variâncias entre municípios, UFs e regiões partem dos
        valores de `Parametros` (o piso) e são reestimadas com a dispersão observada na própria apuração:
        uma eleição em que os estados divergem muito precisa de faixas mais largas para os que faltam."""
        par, k = self.par, self.n_perfil
        fatia_reg = slice(k + 1, k + 1 + self.n_reg)
        fatia_uf = slice(k + 1 + self.n_reg, k + 1 + self.n_reg + self.n_uf)
        n_uf = np.bincount(self.uf_idx[mun], minlength=self.n_uf)
        n_reg = np.bincount(self.reg_idx[mun], minlength=self.n_reg)
        var_m, sd_reg, sd_uf = par.sd_municipio**2, par.sd_regiao, par.sd_uf
        for _ in range(3):
            prec = self.precisao_priori.copy()
            prec[fatia_reg], prec[fatia_uf] = 1 / sd_reg**2, 1 / sd_uf**2
            w = 1 / (var_m + var_amostra)
            cov = np.linalg.inv(z.T @ (z * w[:, None]) + np.diag(prec))
            theta = cov @ (z.T @ (w * swing))
            resid = swing - z @ theta
            var_m = max(par.sd_municipio**2, np.average(resid**2 - var_amostra, weights=w**2))
            pv = np.diag(cov)
            com_dados = n_uf >= 5
            if com_dados.sum() >= 3:
                sd_uf = max(par.sd_uf, np.sqrt(np.mean(theta[fatia_uf][com_dados] ** 2 + pv[fatia_uf][com_dados])))
            com_dados = n_reg >= 5
            if com_dados.sum() >= 2:
                sd_reg = max(par.sd_regiao, np.sqrt(np.mean(theta[fatia_reg][com_dados] ** 2 + pv[fatia_reg][com_dados])))
        return theta, cov, var_m

    def _swing_uniforme(self, w_sec: np.ndarray, alvo: np.ndarray, mun: np.ndarray) -> np.ndarray:
        """Para cada município em `mun`, o swing que, somado ao logit de cada seção apurada (pesos
        `w_sec`), reproduz a fração `alvo` do apurado. Diferença de logits agregados não serve: com
        mudanças grandes e seções heterogêneas ela erra, e o erro passa para as seções que faltam."""
        mi, nm = self.mi, self.base.n_municipios
        dentro = w_sec > 0
        sec_mi, sec_w, sec_lg = mi[dentro], w_sec[dentro], self.lg_a[dentro]
        total = np.bincount(sec_mi, sec_w, nm)[mun]
        base_agg = np.bincount(sec_mi, sec_w * expit(sec_lg), nm)[mun] / total
        swing = np.zeros(nm)
        swing[mun] = logit(alvo) - logit(base_agg.clip(1e-6, 1 - 1e-6))
        for _ in range(8):
            p = expit(sec_lg + swing[sec_mi])
            f = np.bincount(sec_mi, sec_w * p, nm)[mun] / total - alvo
            df = np.bincount(sec_mi, sec_w * p * (1 - p), nm)[mun] / total
            swing[mun] -= f / np.maximum(df, 1e-9)
        return swing[mun]

    def _estimar(self, ap: Apuracao) -> tuple[np.ndarray, np.ndarray, "Previsao"] | None:
        """% da esquerda projetado [Brasil, UFs...], os sorteios (linhas) no mesmo formato e a previsão
        central seção a seção."""
        par, mi, nm = self.par, self.mi, self.base.n_municipios
        cont = ap.totalizada.astype(bool)
        est = ap.aptos.astype(float)
        aptos_c = np.bincount(mi, self.aptos * cont, nm)
        # O eleitorado do 2º turno pode ser menor que o do 1º; município completo no resultado não tem resto.
        completo = ap.secoes >= np.bincount(mi, minlength=nm)
        resto = np.where(completo, 0.0, np.maximum(self.aptos_mun - est, 0.0))
        aptos_nc = self.aptos_mun - aptos_c

        # Reconciliação: as seções marcadas no arquivo de seções valem pelo eleitorado que o arquivo de
        # resultado diz estar totalizado; se o arquivo de seções não marca nenhuma (ou todas), vale o
        # município inteiro na proporção do resultado.
        sem_marcadas = (aptos_c == 0) & (est > 0)
        todas_marcadas = (aptos_nc == 0) & (resto > 0)
        frac_mun = np.where(self.aptos_mun > 0, 1 / np.maximum(self.aptos_mun, 1), 0)
        peso_c = np.where(cont, (est / np.maximum(aptos_c, 1))[mi], 0) + np.where(sem_marcadas, est * frac_mun, 0)[mi]
        peso_n = np.where(~cont, (resto / np.maximum(aptos_nc, 1))[mi], 0) + np.where(todas_marcadas, resto * frac_mun, 0)[mi]

        e_obs, d_obs = ap.esq.astype(float), ap.dir.astype(float)
        v2 = e_obs + d_obs
        ac_esq = np.bincount(mi, peso_c * self.a_esq, nm)
        ac_dir = np.bincount(mi, peso_c * self.a_dir, nm)
        v1c = np.bincount(mi, peso_c * self.v1, nm)
        ativo = (v2 >= 1) & (v1c > 0) & (ac_esq + ac_dir > 0)
        if not ativo.any():
            return None
        mun = np.flatnonzero(ativo)

        p_obs = ((e_obs + 0.5) / (v2 + 1))[mun]
        w_sec = peso_c * self.v1
        swing = self._swing_uniforme(w_sec, p_obs, mun)
        perfil_m = np.column_stack([np.bincount(mi, w_sec * x, nm)[mun] for x in self.perfil.T]) / v1c[mun, None]
        var_amostra = par.sobredispersao / (v2[mun] * p_obs * (1 - p_obs))
        z = self._efeitos(perfil_m, mun)
        theta, cov, var_m = self._ajustar(z, swing, var_amostra, mun)
        resid = swing - z @ theta
        encolhe = var_m / (var_m + var_amostra)
        desvio = np.zeros(nm)
        desvio[mun] = resid * encolhe
        var_desvio = np.full(nm, var_m)
        var_desvio[mun] = var_m * (1 - encolhe)

        lk = np.zeros(nm)
        lk[mun] = np.log(v2[mun] / v1c[mun])
        peso_lk = np.where(ativo, v1c, 0)
        uf_lk_num = np.bincount(self.uf_idx, peso_lk * lk, self.n_uf)
        uf_lk_den = np.bincount(self.uf_idx, peso_lk, self.n_uf)
        nac_lk = uf_lk_num.sum() / uf_lk_den.sum()
        uf_lk = (uf_lk_num + par.peso_validos * nac_lk) / (uf_lk_den + par.peso_validos)
        k_mun = (peso_lk * lk + par.peso_validos * uf_lk[self.uf_idx]) / (peso_lk + par.peso_validos)
        sd_lk = par.sd_validos * np.sqrt(par.peso_validos / (peso_lk + par.peso_validos))
        sd_lk_uf = par.sd_validos_uf * np.sqrt(par.peso_validos / (uf_lk_den + par.peso_validos))

        falta = np.flatnonzero(peso_n > 0)
        mf = mi[falta]
        z_falta = self._efeitos(self.perfil[falta], mf)
        base_val = peso_n[falta] * self.v1[falta]
        lg = self.lg_a[falta]

        uf_falta = self.uf_idx[mf]
        e_obs_uf = np.bincount(self.uf_idx, e_obs, self.n_uf)
        d_obs_uf = np.bincount(self.uf_idx, d_obs, self.n_uf)

        def secao(theta_s: np.ndarray, desvio_s: np.ndarray, lk_s: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
            return expit(lg + z_falta @ theta_s + desvio_s[mf]), base_val * np.exp(lk_s[mf])

        def total(theta_s: np.ndarray, desvio_s: np.ndarray, lk_s: np.ndarray) -> np.ndarray:
            p, val = secao(theta_s, desvio_s, lk_s)
            e_uf = e_obs_uf + np.bincount(uf_falta, val * p, self.n_uf)
            d_uf = d_obs_uf + np.bincount(uf_falta, val * (1 - p), self.n_uf)
            return 100 * np.concatenate([[e_uf.sum() / (e_uf.sum() + d_uf.sum())], e_uf / np.maximum(e_uf + d_uf, 1)])

        centro = total(theta, desvio, k_mun)
        chol = np.linalg.cholesky(cov)
        rng = np.random.default_rng([int(ap.secoes.sum()), int(e_obs.sum()), int(d_obs.sum()), int(cont.sum())])
        amostras = np.empty((par.sorteios, 1 + self.n_uf))
        for j in range(par.sorteios):
            theta_s = theta + chol @ rng.standard_normal(len(theta))
            choque = par.sd_ordem_nacional * rng.standard_normal() + par.sd_ordem_uf * rng.standard_normal(self.n_uf)
            desvio_s = desvio + np.sqrt(var_desvio) * rng.standard_normal(nm) + choque[self.uf_idx]
            lk_s = k_mun + sd_lk * rng.standard_normal(nm) + (sd_lk_uf * rng.standard_normal(self.n_uf))[self.uf_idx]
            amostras[j] = total(theta_s, desvio_s, lk_s)
        return centro, amostras, Previsao(falta, *secao(theta, desvio, k_mun))


@dataclass(frozen=True)
class Previsao:
    """Previsão central para as seções que faltam (índices na Base), usada para diagnóstico."""

    falta: np.ndarray
    p: np.ndarray
    validos: np.ndarray
