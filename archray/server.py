"""Web service: `uvicorn archray.server:app --reload`.

POST /api/analyze  → JSON report
GET  /report       → the rendered dashboard for a repository
GET  /             → the address bar for pasting a GitHub URL
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from typing import Any

try:
    from fastapi import FastAPI, HTTPException, Query
    from fastapi.responses import HTMLResponse, JSONResponse
    from pydantic import BaseModel, Field
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "The web service needs FastAPI:  pip install fastapi uvicorn"
    ) from exc

from .config import Thresholds
from .engine import VERSION, analyze_source
from .report import render_html

app = FastAPI(title="ArchRay", version=VERSION,
              description="Architecture analysis service for source repositories")

CACHE_TTL = 900  # seconds
_cache: dict[str, tuple[float, dict]] = {}
_semaphore = asyncio.Semaphore(2)  # at most two clones at a time


class AnalyzeRequest(BaseModel):
    source: str = Field(..., description="GitHub repository URL or a path on the server")
    language: str = Field("auto", description="Language to analyse, or 'auto'")
    include_tests: bool = Field(False, description="Analyse test files as well")
    refresh: bool = Field(False, description="Skip the cache")


def _cache_key(source: str, language: str, include_tests: bool) -> str:
    raw = f"{source}|{language}|{include_tests}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


async def _analyze(source: str, language: str, include_tests: bool,
                   refresh: bool = False) -> dict[str, Any]:
    key = _cache_key(source, language, include_tests)
    hit = _cache.get(key)
    if hit and not refresh and time.time() - hit[0] < CACHE_TTL:
        return hit[1]

    async with _semaphore:
        try:
            report = await asyncio.to_thread(
                analyze_source, source, language, Thresholds(), include_tests
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"Analysis error: {exc}") from exc

    _cache[key] = (time.time(), report)
    return report


@app.post("/api/analyze")
async def api_analyze(request: AnalyzeRequest) -> JSONResponse:
    report = await _analyze(request.source, request.language,
                            request.include_tests, request.refresh)
    return JSONResponse(report)


@app.get("/report", response_class=HTMLResponse)
async def report_page(source: str = Query(..., description="Repository URL or path"),
                      language: str = "auto",
                      include_tests: bool = False) -> HTMLResponse:
    report = await _analyze(source, language, include_tests)
    return HTMLResponse(render_html(report))


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "version": VERSION, "cached_reports": len(_cache)}


INDEX = """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>ArchRay</title>
<style>
:root{--ink:#0A1A2F;--rule:#17395E;--chalk:#DCE9F5;--dim:#7E9CB8;--cyan:#48C4E8;
--mono:ui-monospace,"JetBrains Mono",Menlo,Consolas,monospace}
*{box-sizing:border-box}
body{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--ink);
background-image:linear-gradient(rgba(72,196,232,.06) 1px,transparent 1px),
linear-gradient(90deg,rgba(72,196,232,.06) 1px,transparent 1px),
linear-gradient(rgba(72,196,232,.12) 1px,transparent 1px),
linear-gradient(90deg,rgba(72,196,232,.12) 1px,transparent 1px);
background-size:16px 16px,16px 16px,96px 96px,96px 96px;
color:var(--chalk);font-family:system-ui,sans-serif;padding:24px}
.card{border:1px solid var(--rule);background:rgba(6,18,35,.82);padding:34px 32px;max-width:640px;width:100%}
.eyebrow{font-family:var(--mono);font-size:11px;letter-spacing:.22em;text-transform:uppercase;color:#4B6A88}
h1{font-family:var(--mono);font-size:30px;margin:6px 0 10px;letter-spacing:-.01em}
p{color:var(--dim);font-size:14.5px;line-height:1.6;margin:0 0 22px}
label{font-family:var(--mono);font-size:10px;letter-spacing:.18em;text-transform:uppercase;color:#4B6A88}
input,select{width:100%;margin-top:6px;background:rgba(10,26,47,.9);border:1px solid var(--rule);
color:var(--chalk);font-family:var(--mono);font-size:14px;padding:11px 12px}
input:focus,select:focus,button:focus-visible{outline:2px solid var(--cyan);outline-offset:2px}
.row{display:flex;gap:12px;margin-top:16px}.row>div{flex:1}
button{margin-top:22px;width:100%;font-family:var(--mono);font-size:12px;letter-spacing:.2em;
text-transform:uppercase;background:var(--cyan);color:#061223;border:0;padding:13px;cursor:pointer}
button:hover{background:#7ad8f5}
.hint{font-family:var(--mono);font-size:11px;color:#4B6A88;margin-top:16px;line-height:1.8}
.examples{display:flex;gap:6px;flex-wrap:wrap;margin-top:10px}
.examples button{margin:0;width:auto;background:transparent;border:1px solid var(--rule);
color:var(--dim);padding:5px 10px;letter-spacing:.06em;text-transform:none;font-size:11px}
.examples button:hover{color:var(--chalk);border-color:var(--cyan);background:transparent}
a{color:var(--cyan)}
</style></head><body>
<form class="card" action="/report" method="get" target="_blank">
  <div class="eyebrow">Architecture analysis</div>
  <h1>ArchRay</h1>
  <p>Paste a GitHub repository URL. The repo is shallow-cloned, parsed into an AST, and one
  report brings together SOLID violations, code smells, cyclomatic complexity, design
  patterns and the dependency graph. Mixed-language projects are analysed as a whole.</p>
  <label for="source">Repository</label>
  <input id="source" name="source" required placeholder="https://github.com/user/project"
         value="https://github.com/pallets/click">
  <div class="examples">
    <button type="button" onclick="pick('https://github.com/pallets/click')">click · Python</button>
    <button type="button" onclick="pick('https://github.com/google/gson')">gson · Java</button>
    <button type="button" onclick="pick('https://github.com/serilog/serilog')">serilog · C#</button>
    <button type="button" onclick="pick('https://github.com/commonmark/cmark')">cmark · C</button>
  </div>
  <div class="row">
    <div><label for="language">Language</label>
      <select id="language" name="language">
        <option value="auto">Detect automatically</option>
        <option value="python">Python</option><option value="java">Java</option>
        <option value="typescript">TypeScript</option><option value="csharp">C#</option>
        <option value="cpp">C++</option><option value="c">C</option>
      </select></div>
    <div><label for="include_tests">Test files</label>
      <select id="include_tests" name="include_tests">
        <option value="false">Exclude</option><option value="true">Include</option>
      </select></div>
  </div>
  <button type="submit">Generate report</button>
  <div class="hint">The report opens in a new tab · a first analysis takes 5-60 seconds
  depending on repository size<br>
  API: <a href="/docs">/docs</a> · JSON: <code>POST /api/analyze</code></div>
</form>
<script>
function pick(url){ document.getElementById("source").value = url; }
</script>
</body></html>"""


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    return HTMLResponse(INDEX)
