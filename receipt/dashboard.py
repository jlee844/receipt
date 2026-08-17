"""One page, every live session, refreshing. Keyed by session id so two
sessions in the same directory never collide.

Serves on 127.0.0.1 only. Reads transcripts; writes nothing.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from .claims import BACKED, UNBACKED, UNVERIFIED_TESTS
from .report import build
from .session import PROJECTS, live_sessions, load, slug

_CACHE: dict[str, dict] = {}
_LOCK = threading.Lock()


def _sessions_for(cwd: str) -> list[Path]:
    d = PROJECTS / slug(Path(cwd))
    if not d.exists():
        return []
    return sorted((p for p in d.glob("*.jsonl") if p.stat().st_size > 2000),
                  key=lambda p: -p.stat().st_mtime)


def snapshot() -> list[dict]:
    """One row per live session. Cheap enough to poll.

    A session id cannot be mapped to a specific pid from outside: several
    Claude processes share a working directory and nothing on disk links one to
    a transcript. So the row reports the DIRECTORY and how many processes are
    live in it, and never attributes a pid it cannot establish.
    """
    by_cwd: dict[str, int] = {}
    for proc in live_sessions():
        by_cwd[proc["cwd"]] = by_cwd.get(proc["cwd"], 0) + 1

    seen: set[str] = set()
    rows = []
    for cwd, n_procs in by_cwd.items():
        for path in _sessions_for(cwd)[:n_procs]:
            sid = path.stem
            if sid in seen:
                continue
            seen.add(sid)
            mtime = path.stat().st_mtime
            with _LOCK:
                cached = _CACHE.get(sid)
            if cached and cached["mtime"] == mtime:
                rows.append(cached["row"])
                continue
            try:
                r = build(load(path))
            except Exception:
                continue
            c = r.cost
            row = {
                "id": sid[:8], "cwd": cwd.replace(str(Path.home()), "~"),
                "procs": n_procs, "calls": len(r.session.calls),
                "files": len(r.session.files_touched),
                "failed": len(r.session.failures),
                "tests": len(r.session.test_runs),
                "claims": len(r.claims),
                "backed": sum(1 for x in r.claims if x.status == BACKED),
                "unbacked": sum(1 for x in r.claims
                                if x.status in (UNBACKED, UNVERIFIED_TESTS)),
                "usd": round(c.usd, 2), "cache_share": round(c.cache_share, 3),
                "out_tok": c.output_tokens, "mtime": mtime,
                "problems": [{"s": x.sentence[:110], "d": x.detail[:90]}
                             for x in r.claims
                             if x.status in (UNBACKED, UNVERIFIED_TESTS)][:4],
            }
            with _LOCK:
                _CACHE[sid] = {"mtime": mtime, "row": row}
            rows.append(row)
    return sorted(rows, key=lambda r: -r["mtime"])


PAGE = """<!doctype html><meta charset=utf-8>
<title>Sessions</title><meta name=viewport content="width=device-width,initial-scale=1">
<style>
:root{--bg:#F6F7F6;--card:#fff;--ink:#16191B;--mut:#626B6E;--rule:#DCE1DF;
--ok:#0E6E68;--bad:#8E3B2F;--okw:#E4EFEE;--badw:#F5E7E4;
--mono:ui-monospace,"SF Mono",Menlo,monospace}
@media(prefers-color-scheme:dark){:root{--bg:#0F1313;--card:#151A19;--ink:#E7ECE9;
--mut:#8B9591;--rule:#242C2A;--ok:#54BCB3;--bad:#D8836F;--okw:#142A28;--badw:#2B1B18}}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--ink);font-family:var(--mono);font-size:13px;
margin:0;padding:1.5rem}
h1{font-size:.75rem;letter-spacing:.14em;text-transform:uppercase;color:var(--mut);
font-weight:500;margin:0 0 1.2rem;display:flex;gap:1rem;align-items:baseline}
#age{font-size:.7rem}
.grid{display:grid;gap:1rem;grid-template-columns:repeat(auto-fill,minmax(21rem,1fr))}
.card{background:var(--card);border:1px solid var(--rule);border-radius:4px;padding:1rem 1.1rem}
.hd{display:flex;justify-content:space-between;align-items:baseline;gap:.5rem;margin-bottom:.2rem}
.sid{font-size:1.05rem;font-weight:600;letter-spacing:-.01em}
.pid{font-size:.68rem;color:var(--mut)}
.cwd{font-size:.7rem;color:var(--mut);word-break:break-all;margin-bottom:.8rem}
.row{display:flex;justify-content:space-between;padding:.18rem 0;font-variant-numeric:tabular-nums}
.row span:first-child{color:var(--mut)}
.bad{color:var(--bad);font-weight:600}
.pill{display:inline-block;font-size:.66rem;padding:.12rem .45rem;border-radius:3px;
background:var(--okw);color:var(--ok);margin-top:.6rem}
.pill.warn{background:var(--badw);color:var(--bad)}
.prob{margin-top:.7rem;padding-top:.6rem;border-top:1px solid var(--rule);font-size:.72rem}
.prob div{margin-bottom:.45rem;line-height:1.45}
.prob b{color:var(--bad);font-weight:600}
.empty{color:var(--mut);padding:2rem 0}
</style>
<h1>Live sessions <span id=age></span></h1>
<div class=grid id=g></div>
<script>
const fmt=n=>n.toLocaleString();
async function tick(){
  let d; try{ d=await (await fetch('/data')).json() }catch(e){ return }
  document.getElementById('age').textContent = new Date().toLocaleTimeString();
  const g=document.getElementById('g');
  if(!d.length){ g.innerHTML='<p class=empty>No live sessions found.</p>'; return }
  g.innerHTML = d.map(s=>`
    <div class=card>
      <div class=hd><span class=sid>${s.id}</span><span class=pid>${s.procs} live here</span></div>
      <div class=cwd>${s.cwd}</div>
      <div class=row><span>tool calls</span><span>${fmt(s.calls)}</span></div>
      <div class=row><span>files changed</span><span>${fmt(s.files)}</span></div>
      <div class=row><span>test runs</span><span>${fmt(s.tests)}</span></div>
      <div class=row><span>failed calls</span><span>${fmt(s.failed)}</span></div>
      <div class=row><span>claims backed</span><span>${fmt(s.backed)} / ${fmt(s.claims)}</span></div>
      <div class=row><span>cache re-read</span><span>${(s.cache_share*100).toFixed(0)}%</span></div>
      <div class=row><span>at API list</span><span>$${s.usd.toFixed(2)}</span></div>
      <span class="pill ${s.unbacked?'warn':''}">${s.unbacked? s.unbacked+' need a look':'all claims backed'}</span>
      ${s.problems.length?`<div class=prob>${s.problems.map(p=>
        `<div><b>${p.s.replace(/</g,'&lt;')}</b><br>${p.d.replace(/</g,'&lt;')}</div>`).join('')}</div>`:''}
    </div>`).join('');
}
tick(); setInterval(tick, 4000);
</script>"""


class _H(BaseHTTPRequestHandler):
    def do_GET(self):                                   # noqa: N802
        if self.path.startswith("/data"):
            body = json.dumps(snapshot()).encode()
            ctype = "application/json"
        else:
            body = PAGE.encode()
            ctype = "text/html; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):                          # noqa: A003
        pass


def serve(port: int = 8974) -> None:
    srv = HTTPServer(("127.0.0.1", port), _H)           # localhost only
    print(f"\n  live session dashboard -> http://127.0.0.1:{port}\n  ctrl-c to stop\n")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("  stopped")
