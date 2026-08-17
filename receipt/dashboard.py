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
from .waste import profile as _waste_profile


def _waste(session) -> list:
    try:
        return _waste_profile(session, top=6)
    except Exception:
        return []


def _last_asks(path: Path, n: int = 3) -> list[str]:
    """The last few things the human actually typed — the fastest way to know
    what a session is for without opening it."""
    out: list[str] = []
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            m = rec.get("message") or {}
            if m.get("role") != "user":
                continue
            c = m.get("content")
            blocks = ([{"type": "text", "text": c}] if isinstance(c, str)
                      else c if isinstance(c, list) else [])
            for b in blocks:
                if isinstance(b, dict) and b.get("type") == "text":
                    t = " ".join((b.get("text") or "").split())
                    if t and not t.startswith("<") and 12 < len(t) < 300:
                        out.append(t[:160])
    except OSError:
        return []
    return out[-n:]

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
                "problems": [{"s": x.sentence[:200], "d": x.detail[:140]}
                             for x in r.claims
                             if x.status in (UNBACKED, UNVERIFIED_TESTS)][:12],
                "topfiles": [{"f": k.split("/")[-1], "n": v}
                             for k, v in list(r.session.files_touched.items())[:12]],
                "waste": [{"w": i.label, "t": i.tokens, "turn": i.turn,
                           "c": i.carry_tokens} for i in _waste(r.session)],
                "asked": _last_asks(path),
                "in_tok": c.input_tokens, "cw_tok": c.cache_write,
                "cr_tok": c.cache_read, "size_mb": round(path.stat().st_size / 1e6, 1),
            }
            with _LOCK:
                _CACHE[sid] = {"mtime": mtime, "row": row}
            rows.append(row)
    return sorted(rows, key=lambda r: -r["mtime"])


PAGE = """<!doctype html><meta charset=utf-8>
<title>Sessions</title><meta name=viewport content="width=device-width,initial-scale=1">
<style>
:root{--bg:#F6F7F6;--card:#fff;--ink:#16191B;--mut:#626B6E;--rule:#DCE1DF;--soft:#EDF0EE;
--ok:#0E6E68;--bad:#8E3B2F;--okw:#E4EFEE;--badw:#F5E7E4;
--mono:ui-monospace,"SF Mono",Menlo,Consolas,monospace}
@media(prefers-color-scheme:dark){:root{--bg:#0F1313;--card:#151A19;--ink:#E7ECE9;
--mut:#8B9591;--rule:#242C2A;--soft:#1B2220;--ok:#54BCB3;--bad:#D8836F;
--okw:#142A28;--badw:#2B1B18}}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--ink);font-family:var(--mono);font-size:13px;
margin:0;padding:1.2rem 1.4rem 3rem;-webkit-font-smoothing:antialiased}
header{display:flex;gap:1rem;align-items:baseline;margin-bottom:1rem;flex-wrap:wrap}
h1{font-size:.72rem;letter-spacing:.15em;text-transform:uppercase;color:var(--mut);
font-weight:500;margin:0}
#age{font-size:.68rem;color:var(--mut)}
nav{display:flex;gap:.4rem;flex-wrap:wrap;border-bottom:1px solid var(--rule);
padding-bottom:.7rem;margin-bottom:1.2rem}
nav button{font:inherit;background:transparent;color:var(--mut);border:1px solid var(--rule);
border-radius:3px;padding:.45rem .8rem;cursor:pointer;display:flex;gap:.5rem;align-items:center}
nav button:hover{border-color:var(--ok)}
nav button.on{background:var(--card);color:var(--ink);border-color:var(--ok)}
nav .dot{width:6px;height:6px;border-radius:50%;background:var(--ok);flex:none}
nav .dot.warn{background:var(--bad)}
nav small{color:var(--mut);font-size:.66rem}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:1.1rem;align-items:start}
@media(max-width:900px){.cols{grid-template-columns:1fr}}
.panel{background:var(--card);border:1px solid var(--rule);border-radius:4px;padding:.95rem 1.05rem}
.panel h2{font-size:.64rem;letter-spacing:.13em;text-transform:uppercase;color:var(--mut);
font-weight:500;margin:0 0 .7rem}
.row{display:flex;justify-content:space-between;gap:1rem;padding:.2rem 0;
font-variant-numeric:tabular-nums}
.row span:first-child{color:var(--mut)}
.row b{font-weight:600}
.warn{color:var(--bad)}
.cwd{font-size:.7rem;color:var(--mut);word-break:break-all;margin:-.3rem 0 .8rem}
.ask{font-size:.74rem;line-height:1.55;color:var(--ink);padding:.3rem 0;
border-bottom:1px solid var(--soft)}
.ask:last-child{border:0}
table{width:100%;border-collapse:collapse;font-size:.72rem;
font-variant-numeric:tabular-nums}
td{padding:.22rem 0;vertical-align:top}
td:last-child{text-align:right;color:var(--mut);white-space:nowrap}
.prob{font-size:.73rem;line-height:1.5;padding:.45rem 0;border-bottom:1px solid var(--soft)}
.prob:last-child{border:0}
.prob b{color:var(--bad);font-weight:600;display:block;margin-bottom:.15rem}
.prob span{color:var(--mut)}
.none{color:var(--mut);font-size:.75rem}
.bar{height:4px;background:var(--soft);border-radius:2px;overflow:hidden;margin-top:.5rem}
.bar i{display:block;height:100%;background:var(--ok)}
</style>
<header><h1>Live sessions</h1><span id=age></span></header>
<nav id=tabs></nav>
<div id=body></div>
<script>
const f=n=>(n||0).toLocaleString();
let DATA=[], SEL=null;
function tabs(){
  document.getElementById('tabs').innerHTML = DATA.map(s=>`
    <button data-id="${s.id}" class="${s.id===SEL?'on':''}">
      <i class="dot ${s.unbacked?'warn':''}"></i>${s.id}
      <small>${s.cwd.split('/').pop()||'~'} · $${s.usd.toFixed(0)}</small>
    </button>`).join('');
  document.querySelectorAll('nav button').forEach(b=>
    b.onclick=()=>{SEL=b.dataset.id;tabs();detail();});
}
function detail(){
  const s = DATA.find(x=>x.id===SEL); if(!s) return;
  const esc = t => (t||'').replace(/[<>&]/g,c=>({'<':'&lt;','>':'&gt;','&':'&amp;'}[c]));
  document.getElementById('body').innerHTML = `
   <p class=cwd>${esc(s.cwd)} · ${s.procs} session(s) live here · ${s.size_mb} MB transcript</p>
   <div class=cols>
    <div class=panel><h2>What it is doing</h2>
      ${s.asked.length? s.asked.map(a=>`<p class=ask>${esc(a)}</p>`).join('') :
        '<p class=none>no recent prompt</p>'}</div>
    <div class=panel><h2>Activity</h2>
      <div class=row><span>tool calls</span><b>${f(s.calls)}</b></div>
      <div class=row><span>files changed</span><b>${f(s.files)}</b></div>
      <div class=row><span>test runs</span><b>${f(s.tests)}</b></div>
      <div class=row><span>failed calls</span><b>${f(s.failed)}</b></div>
    </div>
    <div class=panel><h2>Claims checked against disk</h2>
      <div class=row><span>backed</span><b>${f(s.backed)} / ${f(s.claims)}</b></div>
      <div class="bar"><i style="width:${s.claims?100*s.backed/s.claims:100}%"></i></div>
      ${s.problems.length? `<div style="margin-top:.7rem">`+s.problems.map(p=>
        `<div class=prob><b>${esc(p.s)}</b><span>${esc(p.d)}</span></div>`).join('')+`</div>`
        : '<p class=none style="margin-top:.6rem">nothing unbacked</p>'}
    </div>
    <div class=panel><h2>Cost &amp; context</h2>
      <div class=row><span>new input</span><b>${f(s.in_tok)}</b></div>
      <div class=row><span>cache written</span><b>${f(s.cw_tok)}</b></div>
      <div class=row><span>cache re-read</span><b class="${s.cache_share>0.9?'warn':''}">${f(s.cr_tok)} · ${(s.cache_share*100).toFixed(0)}%</b></div>
      <div class=row><span>output</span><b>${f(s.out_tok)}</b></div>
      <div class=row style="margin-top:.4rem"><span>at API list prices</span><b>$${s.usd.toFixed(2)}</b></div>
      <p class=none style="margin-top:.4rem">A Claude Code subscription is not billed
      per token — this is what the same work would cost through the API.</p>
    </div>
    <div class=panel><h2>Most-touched files</h2>
      <table>${s.topfiles.map(t=>`<tr><td>${esc(t.f)}</td><td>${t.n}x</td></tr>`).join('')
        || '<tr><td class=none>none</td></tr>'}</table></div>
    <div class=panel><h2>What cost the most to carry</h2>
      <table>${s.waste.map(w=>`<tr><td>${esc(w.w)}</td><td>${f(w.c)}</td></tr>`).join('')
        || '<tr><td class=none>nothing large</td></tr>'}</table>
      <p class=none style="margin-top:.5rem">tokens × turns they stayed in context</p></div>
   </div>`;
}
async function tick(){
  try{ DATA = await (await fetch('/data')).json() }catch(e){ return }
  document.getElementById('age').textContent = new Date().toLocaleTimeString();
  if(!DATA.length){ document.getElementById('body').innerHTML='<p class=none>No live sessions.</p>'; return }
  if(!DATA.find(x=>x.id===SEL)) SEL = DATA[0].id;
  tabs(); detail();
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
