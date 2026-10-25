"""Linha de comando: `uv run eleicao <comando>`."""

import argparse


def main() -> None:
    p = argparse.ArgumentParser(prog="eleicao", description="Apuração do 2º turno com projeção do resultado final")
    sub = p.add_subparsers(dest="comando", required=True)

    b = sub.add_parser("base", help="monta a base de seções a partir dos dados abertos do TSE")
    b.add_argument("--ano", type=int, default=2026, choices=(2026, 2022, 2018))

    e = sub.add_parser("ensaio", help="reproduz um 2º turno passado na ordem real de chegada e mede o erro")
    e.add_argument("--ano", type=int, default=2022, choices=(2022, 2018))

    v = sub.add_parser("ao-vivo", help="acompanha a divulgação do TSE e grava site/dados/projecao.json")
    v.add_argument("--ano", type=int, default=2026, choices=(2026, 2022))
    v.add_argument("--intervalo", type=float, default=30, help="segundos entre ciclos")
    v.add_argument("--url-base", default=None, help="outra origem dos arquivos (ex.: o TSE falso)")

    f = sub.add_parser("tse-falso", help="serve um cenário nos arquivos da divulgação do TSE, avançando o relógio")
    f.add_argument("--ano", type=int, default=2022, choices=(2026, 2022))
    f.add_argument("--velocidade", type=float, default=60, help="minutos da apuração por minuto real")
    f.add_argument("--porta", type=int, default=8765)

    pb = sub.add_parser("publicar", help="envia site/dados/projecao.json para a branch dados e publica no GitHub Pages")
    pb.add_argument("--intervalo", type=float, default=60, help="segundos até repetir um envio que falhou (envia assim que o arquivo muda)")

    s = sub.add_parser("servir", help="serve a página em site/")
    s.add_argument("--porta", type=int, default=8000)

    args = p.parse_args()
    if args.comando == "base":
        from eleicao.base.montar import montar
        montar(args.ano)
    elif args.comando == "ensaio":
        from eleicao.ensaio import ensaiar
        ensaiar(args.ano)
    elif args.comando == "ao-vivo":
        from eleicao.tse.ao_vivo import rodar
        rodar(args.ano, args.intervalo, args.url_base)
    elif args.comando == "tse-falso":
        from eleicao.tse.falso import servir
        servir(args.ano, args.velocidade, args.porta)
    elif args.comando == "publicar":
        from eleicao.publicar import rodar
        rodar(args.intervalo)
    elif args.comando == "servir":
        import functools
        import http.server

        from eleicao.config import SITE
        class SemCache(http.server.SimpleHTTPRequestHandler):
            """Sem isso o navegador guarda app.js e style.css antigos e não mostra mudanças na página."""

            def end_headers(self) -> None:
                self.send_header("Cache-Control", "no-cache")
                super().end_headers()

        handler = functools.partial(SemCache, directory=str(SITE))
        print(f"http://localhost:{args.porta}/")
        http.server.ThreadingHTTPServer(("", args.porta), handler).serve_forever()
