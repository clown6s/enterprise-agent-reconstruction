"""Local web review page: enter questions, inspect Top-K, and save labels."""
import argparse
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
:root{--ink:#172033;--muted:#718096;--line:#e6eaf0;--brand:#3867d6;--good:#16805c;--bad:#c53d4f;--bg:#f5f7fb}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.6 system-ui,-apple-system,'Microsoft YaHei',sans-serif}.shell{max-width:1240px;margin:auto;padding:28px}.hero{display:flex;justify-content:space-between;align-items:end;margin-bottom:20px}.eyebrow{color:var(--brand);font-weight:700;letter-spacing:.08em;font-size:12px}.hero h1{margin:2px 0;font-size:28px}.sub,.meta{color:var(--muted)}.panel{background:#fff;border:1px solid var(--line);border-radius:16px;box-shadow:0 8px 24px #1b2a4a0b;padding:18px}.controls{display:grid;grid-template-columns:1fr 140px 120px;gap:12px}.query{width:100%;min-height:74px;border:1px solid var(--line);border-radius:10px;padding:12px;font:inherit;resize:vertical}.select,.btn{border:1px solid var(--line);border-radius:10px;padding:10px;background:#fff;font:inherit}.btn{cursor:pointer;font-weight:700}.primary{background:var(--brand);border-color:var(--brand);color:#fff}.toolbar{display:flex;gap:10px;align-items:center;margin-top:12px}.stats{display:flex;gap:10px;flex-wrap:wrap;margin:18px 0}.stat{background:#fff;border:1px solid var(--line);border-radius:10px;padding:8px 14px}.stat b{font-size:18px;margin-right:5px}.card{background:#fff;border:1px solid var(--line);border-radius:13px;margin:10px 0;padding:15px}.card.selected-good{border-color:#7bd4b3;background:#f4fffa}.card.selected-bad{border-color:#e99aa5;background:#fff7f8}.cardhead{display:flex;gap:12px;align-items:center}.rank{font-size:18px;font-weight:800;color:var(--brand);min-width:32px}.badge{border-radius:99px;padding:2px 9px;background:#eef2ff;color:var(--brand);font-size:12px}.checks{margin-left:auto;display:flex;gap:12px}.checks label{cursor:pointer}.good{color:var(--good)}.bad{color:var(--bad)}.text{white-space:pre-wrap;background:#fafbfc;border-radius:8px;padding:12px;margin-top:10px;max-height:220px;overflow:auto}.empty{text-align:center;padding:55px;color:var(--muted)}@media(max-width:720px){.shell{padding:14px}.controls{grid-template-columns:1fr}.checks{margin-left:0}.hero{display:block}}
</style><div class=shell><header class=hero><div><div class=eyebrow>RETRIEVAL REVIEW</div><h1>检索评测工作台</h1><div class=sub>输入真实问题，查看候选结果并标注相关性</div></div><div class=sub>本地只读检索 · 审核后保存</div></header><section class=panel><div class=controls><textarea id=q class=query placeholder='例如：Agent 如何工作的？'></textarea><select id=mode class=select><option value=hybrid>Hybrid 检索</option><option value=dense>Dense 检索</option></select><select id=topk class=select><option value=20>Top 20</option><option value=50>Top 50</option><option value=100>Top 100</option></select></div><div class=toolbar><button class='btn primary' onclick=search()>搜索候选</button><button class=btn onclick=save()>保存审核</button><span id=status class=sub></span></div></section><div id=stats class=stats></div><main id=out class=empty>输入问题后开始检索</main></div><script>
let current=null;const $=id=>document.getElementById(id);function escapeHtml(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}function updateStats(){let rel=document.querySelectorAll('[data-r=rel]:checked').length,bad=document.querySelectorAll('[data-r=bad]:checked').length,total=current?.candidates?.length||0;$('stats').innerHTML=`<div class=stat><b>${total}</b>候选</div><div class=stat><b class=good>${rel}</b>相关</div><div class=stat><b class=bad>${bad}</b>噪声</div><div class=stat><b>${total-rel-bad}</b>待审核</div>`;}async function search(){let query=$('q').value.trim();if(!query)return alert('请输入问题');$('status').textContent='检索中…';let r=await fetch('/api/search',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({query,mode:$('mode').value,top_k:Number($('topk').value)})});current=await r.json();$('status').textContent=current.error||`已返回 ${current.candidates?.length||0} 条`;render();}function render(){if(current.error){$('out').className='empty';$('out').textContent=current.error;return;}$('out').className='';$('out').innerHTML=current.candidates.map(x=>`<article class=card id=c${x.rank}><div class=cardhead><span class=rank>#${x.rank}</span><span class=badge>${escapeHtml(x.kind||'unknown')}</span><span class=meta>score ${Number(x.score).toFixed(4)} · page ${x.page??'-'} · ${escapeHtml((x.section_path||[]).join(' › ')||'无章节')}</span><span class=checks><label class=good><input type=checkbox data-r=rel value='${escapeHtml(x.chunk_id)}' onchange="toggle(this,'good')"> 相关</label><label class=bad><input type=checkbox data-r=bad value='${escapeHtml(x.chunk_id)}' onchange="toggle(this,'bad')"> 噪声</label></span></div><div class=meta>${escapeHtml(x.chunk_id||'')}</div><div class=text>${escapeHtml(x.text)}</div></article>`).join('');updateStats();}function toggle(box,kind){let card=box.closest('.card');let other=card.querySelector(`[data-r=${kind==='good'?'bad':'rel'}]`);if(box.checked)other.checked=false;card.classList.toggle('selected-'+kind,box.checked);updateStats();}async function save(){if(!current)return alert('请先搜索');let ids=r=>[...document.querySelectorAll(`[data-r=${r}]:checked`)].map(x=>x.value);let body={...current,relevant_chunk_ids:ids('rel'),forbidden_chunk_ids:ids('bad'),expected_sections:[]};let r=await fetch('/api/save',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body)});let data=await r.json();$('status').textContent=data.message||data.error;}
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
    return {"id": "review-" + str(abs(hash(request.query))), "query": request.query,
            "mode": request.mode, "candidate_k": request.top_k, "candidates": candidates}

@app.post("/api/save")
def save(request: SaveRequest):
    allowed = {item.get("chunk_id") for item in request.candidates}
    relevant = set(request.relevant_chunk_ids); forbidden = set(request.forbidden_chunk_ids)
    if not request.query.strip() or not relevant <= allowed or not forbidden <= allowed or relevant & forbidden:
        return {"error": "审核 ID 无效或相关/噪声重复"}
    REVIEW_PATH.parent.mkdir(parents=True, exist_ok=True)
    existing = json.loads(REVIEW_PATH.read_text(encoding="utf-8")) if REVIEW_PATH.exists() else []
    existing = [item for item in existing if item.get("id") != request.id]
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

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port)

if __name__ == "__main__": main()
