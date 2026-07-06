"""Run the pipeline, export web assets, and serve the interactive UI.

    python run_ui.py            # full pipeline + serve at http://127.0.0.1:8000
    python run_ui.py --port 9000
    python run_ui.py --no-run   # skip the pipeline, just (re)export + serve

Open the printed URL in a browser.
"""

from __future__ import annotations

import argparse
import functools
import http.server
import os
import shutil
import socketserver
import sys

# Run from this file's directory so `import run_demo`, the `subsuelo` package,
# and the ./out paths all resolve regardless of the caller's cwd.
_HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(_HERE)
sys.path.insert(0, _HERE)

from subsuelo.web.export import export


def build(run_pipeline: bool, live: bool = False, outdir: str = "out") -> str:
    if run_pipeline:
        if live:
            import run_live
            run_live.main(outdir=outdir)
        else:
            import run_demo
            run_demo.main(outdir=outdir)
    webdir = export(outdir)
    # place index.html alongside the exported assets
    here = os.path.dirname(os.path.abspath(__file__))
    shutil.copy(os.path.join(here, "subsuelo", "web", "index.html"),
                os.path.join(webdir, "index.html"))
    return webdir


def serve(webdir: str, host: str, port: int) -> None:
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=webdir)
    with socketserver.TCPServer((host, port), handler) as httpd:
        url = f"http://{host}:{port}/"
        print(f"\n  Subsuelo UI → {url}\n  Serving {webdir}/  (Ctrl-C to stop)\n")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--no-run", action="store_true", help="skip pipeline, reuse ./out")
    ap.add_argument("--live", action="store_true",
                    help="use real IGME + Catastro data (run_live) instead of synthetic")
    args = ap.parse_args()

    webdir = build(run_pipeline=not args.no_run, live=args.live)
    serve(webdir, args.host, args.port)
