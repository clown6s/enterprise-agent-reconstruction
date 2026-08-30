"""Local web review page: enter questions, inspect Top-K, and save labels."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import uvicorn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.ingestion.application.retrieve import RetrieveDocuments
from app.ingestion.bootstrap.logging import setup_logging
from app.ingestion.bootstrap.container import build_ingestion

app = FastAPI(title="Retrieval Review")
REVIEW_PATH = ROOT / "tests" / "data" / "retrieval_review.json"
CASES_PATH = ROOT / "tests" / "data" / "retrieval_cases.json"
retriever = None

class QueryRequest(BaseModel):
    query: str
    mode: str = "hybrid"
    top_k: int = 20

class SaveRequest(BaseModel):
    id: str
    query: str
    mode: str
    candidates: list[dict]
    relevant_chunk_ids: list[str] = []
    forbidden_chunk_ids: list[str] = []
    expected_sections: list[str] = []


def _case_id(query: str) -> str:
    """稳定、确定性的用例 id：同一问题每次得到相同 id（避免 hash 进程随机）。"""
    return "review-" + hashlib.md5(query.encode("utf-8")).hexdigest()[:16]


def _ensure_retriever():
    global retriever
    if retriever is None:
        service = build_ingestion()
        retriever = RetrieveDocuments(service.embedder, service.vectors,
            lexical=service.lexical)
    return retriever

@app.get("/", response_class=HTMLResponse)
def index():
    return HTMLResponse("""<!doctype html><html lang='zh-CN'><meta charset='utf-8'><title>检索评测工作台</title>
<style>
:root{--ink:#172033;--muted:#718096;--line:#e6eaf0;--brand:#3867d6;--brand-dark:#2a55b8;--good:#16805c;--bad:#c53d4f;--bg:#f5f7fb;--card-shadow:0 2px 14px rgba(27,42,74,.06)}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.6 system-ui,-apple-system,'Microsoft YaHei',sans-serif}.shell{max-width:1240px;margin:auto;padding:28px}.hero{display:flex;justify-content:space-between;align-items:end;margin-bottom:20px;gap:16px;flex-wrap:wrap}.eyebrow{color:var(--brand);font-weight:700;letter-spacing:.08em;font-size:12px;text-transform:uppercase}.hero h1{margin:2px 0;font-size:28px}.sub,.meta{color:var(--muted)}.panel{background:#fff;border:1px solid var(--line);border-radius:16px;box-shadow:var(--card-shadow);padding:20px}.controls{display:grid;grid-template-columns:1fr 150px 130px 110px;gap:12px}.query{width:100%;min-height:64px;border:1px solid var(--line);border-radius:10px;padding:12px;font:inherit;resize:vertical;transition:border-color .15s}.query:focus{outline:none;border-color:var(--brand)}.select,.btn{border:1px solid var(--line);border-radius:10px;padding:10px;background:#fff;font:inherit}.btn{cursor:pointer;font-weight:700;transition:background .15s,transform .05s}.btn:hover{filter:brightness(.97)}.btn:active{transform:translateY(1px)}.primary{background:var(--brand);border-color:var(--brand);color:#fff}.primary:hover{background:var(--brand-dark)}.warn{border-color:var(--bad);color:var(--bad);background:#fff}.toolbar{display:flex;gap:10px;align-items:center;margin-top:14px;flex-wrap:wrap}.toolbar .status{flex:1;min-width:200px;text-align:right}.toolbar .status.err{color:var(--bad);font-weight:600}.toolbar .status.ok{color:var(--good);font-weight:600}.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:18px 0}.stat{background:#fff;border:1px solid var(--line);border-radius:12px;padding:12px 16px;display:flex;flex-direction:column}.stat .num{font-size:24px;font-weight:800;line-height:1.2}.stat .lbl{color:var(--muted);font-size:12px;margin-top:2px}.stat.good .num{color:var(--good)}.stat.bad .num{color:var(--bad)}.section-label{display:flex;align-items:center;gap:8px;margin:22px 0 8px;font-weight:700;color:var(--muted);font-size:12px;letter-spacing:.08em;text-transform:uppercase}.section-label:before,.section-label:after{content:'';flex:1;height:1px;background:var(--line)}.card{background:#fff;border:1px solid var(--line);border-radius:13px;box-shadow:var(--card-shadow);margin:10px 0;padding:15px;transition:border-color .15s,background .15s}.card.selected-good{border-color:#7bd4b3;background:#f4fffa}.card.selected-bad{border-color:#e99aa5;background:#fff7f8}.cardhead{display:flex;gap:12px;align-items:center;flex-wrap:wrap}.rank{font-size:18px;font-weight:800;color:var(--brand);min-width:32px}.badge{border-radius:99px;padding:2px 10px;background:#eef2ff;color:var(--brand);font-size:12px;font-weight:600}.checks{margin-left:auto;display:flex;gap:12px}.checks label{cursor:pointer;user-select:none}.good{color:var(--good)}.bad{color:var(--bad)}.good.selected{background:#e6f7ef}.bad.selected{background:#fdecee}.text{white-space:pre-wrap;background:#fafbfc;border-radius:8px;padding:12px;margin-top:10px;max-height:220px;overflow:auto;border:1px solid #eef1f6}.empty{text-align:center;padding:40px;color:var(--muted);background:#fff;border:1px dashed var(--line);border-radius:13px;margin:10px 0}.validation-result{margin:10px 0;border:1px solid var(--line);border-radius:13px;padding:14px;box-shadow:var(--card-shadow);background:#fff}.validation-result.good{border-color:#7bd4b3}.validation-result.bad{border-color:#e99aa5}@media(max-width:860px){.shell{padding:14px}.controls{grid-template-columns:1fr}.stats{grid-template-columns:repeat(2,1fr)}.checks{margin-left:0}.toolbar .status{text-align:left}}
</style><div class=shell><header class=hero><div><div class=eyebrow>RETRIEVAL REVIEW</div><h1>检索评测工作台</h1><div class=sub>输入真实问题，查看候选结果并标注相关性</div></div><div class=sub>本地只读检索 · 审核后保存</div></header><section class=panel><div class=controls><textarea id=q class=query placeholder='例如：Agent 如何工作的？'></textarea><select id=mode class=select><option value=hybrid>Hybrid 检索</option><option value=dense>Dense 检索</option></select><select id=topk class=select><option value=20>Top 20</option><option value=50>Top 50</option><option value=100>Top 100</option></select></div><div class=toolbar><button class='btn primary' onclick=search()>搜索候选</button><button class=btn onclick=save()>保存审核</button><button class='btn warn' onclick=validateCases()>校验评测集</button><span id=status class='status sub'></span></div></section><div id=validate></div><div id=stats class=stats></div><main id=out class=empty>输入问题后开始检索</main></div><script>let current=null;const $=id=>document.getElementById(id);function clearResults(){current=null;$('out').className='empty';$('out').textContent='搜索后显示候选结果';$('stats').innerHTML='';$('validate').innerHTML='';}function escapeHtml(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}function setStatus(text,isErr){let el=$('status');el.textContent=text;el.className=isErr?'status err':'status '+(text&&!text.includes('…')?'ok':'sub');}function statCard(num,label,cls){return `<div class="stat ${cls||''}"><div class=num>${num}</div><div class=lbl>${label}</div></div>`;}function updateStats(){let rel=document.querySelectorAll('[data-r=rel]:checked').length,bad=document.querySelectorAll('[data-r=bad]:checked').length,total=current?.candidates?.length||0;$('stats').innerHTML=statCard(total,'候选')+statCard(rel,'相关','good')+statCard(bad,'噪声','bad')+statCard(Math.max(0,total-rel-bad),'待审核');}async function search(){let query=$('q').value.trim();if(!query)return alert('请输入问题');clearResults();setStatus('检索中…',false);let r=await fetch('/api/search',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({query,mode:$('mode').value,top_k:Number($('topk').value)})});current=await r.json();if(current.error){setStatus(current.error,true);$('out').className='empty';$('out').textContent=current.error;return;}setStatus(`已返回 ${current.candidates?.length||0} 条`,false);render();}function render(){$('out').className='';$('out').innerHTML=current.candidates.map(x=>`<article class=card id=c${x.rank}><div class=cardhead><span class=rank>#${x.rank}</span><span class=badge>${escapeHtml(x.kind||'unknown')}</span><span class=meta>score ${Number(x.score).toFixed(4)} · page ${x.page??'-'} · ${escapeHtml((x.section_path||[]).join(' › ')||'无章节')}</span><span class=checks><label class='good '><input type=checkbox data-r=rel value='${escapeHtml(x.chunk_id)}' onchange="toggle(this,'good')"> 相关</label><label class='bad'><input type=checkbox data-r=bad value='${escapeHtml(x.chunk_id)}' onchange="toggle(this,'bad')"> 噪声</label></span></div><div class=meta>${escapeHtml(x.chunk_id||'')}</div><div class=text>${escapeHtml(x.text)}</div></article>`).join('');updateStats();}function toggle(box,kind){let card=box.closest('.card');let other=card.querySelector(`[data-r=${kind==='good'?'bad':'rel'}]`);if(box.checked){other.checked=false;other.closest('label').classList.remove('selected');}box.closest('label').classList.toggle('selected',box.checked);card.classList.toggle('selected-'+kind,box.checked);updateStats();}async function save(){if(!current)return alert('请先搜索');if(!document.querySelector('[data-r=rel]:checked')&&!confirm('未勾选任何「相关」chunk，保存后不会进入正式评测集。仍要保存吗？'))return;let ids=r=>[...document.querySelectorAll(`[data-r=${r}]:checked`)].map(x=>x.value);let body={...current,relevant_chunk_ids:ids('rel'),forbidden_chunk_ids:ids('bad'),expected_sections:[]};let r=await fetch('/api/save',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body)});let data=await r.json();setStatus(data.message||data.error,!!data.error);if(!data.error){current=null;$('validate').innerHTML='';updateStats();}}async function validateCases(){let el=$('validate');setStatus('校验中…',false);clearResults();el.innerHTML='<div class="empty">校验中…</div>';let r=await fetch('/api/validate_cases',{method:'POST'});let d=await r.json();if(d.error){setStatus(d.error,true);el.innerHTML='';return;}setStatus(`校验完成：共 ${d.total} 条，${d.stale_cases} 条失效`,d.stale_cases>0||d.empty_relevant_cases>0);let issues=d.issues.filter(i=>i.stale_ids.length||i.empty_relevant);if(!issues.length){el.innerHTML=`<div class="validation-result good"><div style="font-weight:700;color:var(--good)">✓ 校验通过</div><div class=sub>共 ${d.total} 条用例，无失效 id、无空相关标注</div></div>`;return;}let html=`<div class="validation-result bad"><div style="font-weight:700;color:var(--bad)">✗ 发现 ${issues.length} 条问题：${d.stale_cases} 条含失效 id，${d.empty_relevant_cases} 条空相关</div></div>`;html+=issues.map(c=>`<div class=card><div class=cardhead><span class=badge style='background:#fdecee;color:var(--bad)'>${c.stale_ids.length?'失效':'空相关'}</span><b>${escapeHtml(c.query||'')}</b><span class=meta>${escapeHtml(c.id||'')}</span></div><div class=meta style=margin-top:6px>${c.stale_ids.length?('<span class=bad>失效 id: </span>'+escapeHtml(c.stale_ids.join(', '))):'<span class=bad>无 relevant_chunk_ids</span>'}</div></div>`).join('');el.innerHTML=html;}
</script></html>""")

@app.post("/api/search")
def search(request: QueryRequest):
    if not request.query.strip(): return {"error": "query 不能为空"}
    if request.mode not in {"dense", "hybrid"} or not 1 <= request.top_k <= 100: return {"error": "参数无效"}
    service = _ensure_retriever()
    results = (service.execute(request.query, top_k=request.top_k) if request.mode == "dense"
               else service.execute_hybrid(request.query, top_k=request.top_k))
    candidates = []
    for rank, item in enumerate(results, 1):
        meta = item.metadata or {}
        candidates.append({"rank": rank, "chunk_id": meta.get("chunk_id"), "score": item.score,
            "document_id": item.document_id, "page": item.page, "kind": item.kind,
            "section_path": list(item.section_path), "text": item.text})
    return {"id": _case_id(request.query), "query": request.query,
            "mode": request.mode, "candidate_k": request.top_k, "candidates": candidates}

@app.post("/api/save")
def save(request: SaveRequest):
    allowed = {item.get("chunk_id") for item in request.candidates}
    relevant = set(request.relevant_chunk_ids); forbidden = set(request.forbidden_chunk_ids)
    if not request.query.strip() or not relevant <= allowed or not forbidden <= allowed or relevant & forbidden:
        return {"error": "审核 ID 无效或相关/噪声重复"}
    # 保存前校验所有勾选的 chunk 是否真实存在于向量库，阻止失效标注进入评测集。
    if relevant or forbidden:
        exists = _ensure_retriever().vectors.chunk_exists(relevant | forbidden)
        stale = [cid for cid, ok in exists.items() if not ok]
        if stale:
            return {"error": "以下 chunk 已失效（不在向量库中），已阻止保存: " + ", ".join(sorted(stale))}
    REVIEW_PATH.parent.mkdir(parents=True, exist_ok=True)
    existing = json.loads(REVIEW_PATH.read_text(encoding="utf-8")) if REVIEW_PATH.exists() else []
    # 同时按 id 和 query 去重：兼容旧 hash 生成的 id，避免同一问题重复条目。
    existing = [item for item in existing
                if item.get("id") != request.id and item.get("query") != request.query]
    existing.append(request.model_dump())
    temp = REVIEW_PATH.with_suffix(".tmp")
    temp.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(REVIEW_PATH)
    formal = [{key: item.get(key) for key in (
        "id", "query", "relevant_chunk_ids", "expected_sections", "forbidden_chunk_ids")}
              for item in existing if item.get("query", "").strip() and item.get("relevant_chunk_ids")]
    cases_temp = CASES_PATH.with_suffix(".tmp")
    cases_temp.write_text(json.dumps(formal, ensure_ascii=False, indent=2), encoding="utf-8")
    cases_temp.replace(CASES_PATH)
    return {"message": f"已保存，共 {len(existing)} 条；正式评测集 {len(formal)} 条"}


@app.post("/api/validate_cases")
def validate_cases():
    """扫描整个评测集，标出失效或空的 relevant/forbidden chunk id。"""
    if not CASES_PATH.exists():
        return {"total": 0, "stale_cases": 0, "empty_relevant_cases": 0,
                "issues": [], "message": "评测集为空"}
    data = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    issues = []
    stale_cases = 0
    empty_relevant_cases = 0
    for case in data:
        relevant = case.get("relevant_chunk_ids") or []
        forbidden = case.get("forbidden_chunk_ids") or []
        if not relevant:
            empty_relevant_cases += 1
        ids = list(dict.fromkeys([str(i) for i in list(relevant) + list(forbidden)]))
        stale = []
        if ids:
            exists = _ensure_retriever().vectors.chunk_exists(ids)
            stale = [cid for cid, ok in exists.items() if not ok]
        if stale:
            stale_cases += 1
        issues.append({"id": case.get("id"), "query": case.get("query"),
                       "relevant_chunk_ids": list(relevant),
                       "forbidden_chunk_ids": list(forbidden),
                       "stale_ids": stale,
                       "empty_relevant": not relevant})
    return {"total": len(data), "stale_cases": stale_cases,
            "empty_relevant_cases": empty_relevant_cases, "issues": issues}

def main():
    setup_logging()
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port)

if __name__ == "__main__": main()
