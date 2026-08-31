"""Local web review page: enter questions, inspect Top-K, and save labels."""
import argparse
import hashlib
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
import sys
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import uvicorn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.ingestion.application.retrieve import RetrieveDocuments
from app.ingestion.bootstrap.handlers import register_exception_handlers
from app.ingestion.bootstrap.logging import setup_logging
from app.ingestion.domain.exceptions import ValidationError
from app.ingestion.bootstrap.container import build_ingestion, build_reranker

review_retriever = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    if review_retriever is not None:
        review_retriever.close()


app = FastAPI(title="Retrieval Review", lifespan=lifespan)
register_exception_handlers(app)
REVIEW_PATH = ROOT / "tests" / "data" / "retrieval_review.json"
CASES_PATH = ROOT / "tests" / "data" / "retrieval_cases.json"


class QueryRequest(BaseModel):
    query: str
    top_k: int | None = None

class SaveRequest(BaseModel):
    id: str
    query: str
    candidates: list[dict]
    stages: dict[str, list[dict]] = {}
    stage_rank: dict[str, dict] = {}
    relevant_rankings: dict[str, dict] = {}
    relevant_chunk_ids: list[str] = []
    forbidden_chunk_ids: list[str] = []
    expected_sections: list[str] = []


def _case_id(query: str) -> str:
    """稳定、确定性的用例 id：同一问题每次得到相同 id（避免 hash 进程随机）。"""
    return "review-" + hashlib.md5(query.encode("utf-8")).hexdigest()[:16]


def _ensure_retriever():
    global review_retriever
    if review_retriever is None:
        service = build_ingestion()
        review_retriever = RetrieveDocuments(service.embedder, service.vectors,
            lexical=service.lexical, reranker=build_reranker())
    return review_retriever

@app.get("/", response_class=HTMLResponse)
def index():
    return HTMLResponse("""<!doctype html><html lang='zh-CN'><meta charset='utf-8'><title>检索评测工作台</title>
<style>
:root{--ink:#172033;--muted:#718096;--line:#e6eaf0;--brand:#3867d6;--brand-dark:#2a55b8;--good:#16805c;--bad:#c53d4f;--bg:#f5f7fb;--card-shadow:0 2px 14px rgba(27,42,74,.06)}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.6 system-ui,-apple-system,'Microsoft YaHei',sans-serif}.shell{max-width:1240px;margin:auto;padding:28px}.hero{display:flex;justify-content:space-between;align-items:end;margin-bottom:20px;gap:16px;flex-wrap:wrap}.eyebrow{color:var(--brand);font-weight:700;letter-spacing:.08em;font-size:12px;text-transform:uppercase}.hero h1{margin:2px 0;font-size:28px}.sub,.meta{color:var(--muted)}.panel{background:#fff;border:1px solid var(--line);border-radius:16px;box-shadow:var(--card-shadow);padding:20px}.controls{display:grid;grid-template-columns:1fr;gap:12px}.query{width:100%;min-height:64px;border:1px solid var(--line);border-radius:10px;padding:12px;font:inherit;resize:vertical;transition:border-color .15s}.query:focus{outline:none;border-color:var(--brand)}.select,.btn{border:1px solid var(--line);border-radius:10px;padding:10px;background:#fff;font:inherit}.btn{cursor:pointer;font-weight:700;transition:background .15s,transform .05s}.btn:hover{filter:brightness(.97)}.btn:active{transform:translateY(1px)}.primary{background:var(--brand);border-color:var(--brand);color:#fff}.primary:hover{background:var(--brand-dark)}.warn{border-color:var(--bad);color:var(--bad);background:#fff}.toolbar{display:flex;gap:10px;align-items:center;margin-top:14px;flex-wrap:wrap}.toolbar .btn{min-width:118px;display:inline-flex;align-items:center;justify-content:center;gap:6px;box-shadow:0 1px 2px rgba(27,42,74,.05)}.toolbar .status{flex:1;min-width:200px;color:var(--muted);font-size:13px}.toolbar .status.err,.toolbar .status.ok{display:inline-flex;align-items:center;justify-content:flex-end;gap:7px;padding:7px 14px;border-radius:9px}.toolbar .status.err{color:var(--bad);font-weight:700;background:#fdecee}.toolbar .status.ok{color:var(--good);font-weight:600;background:#e6f7ef}.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:18px 0}.stat{position:relative;overflow:hidden;background:#fff;border:1px solid var(--line);border-radius:12px;padding:16px 16px 12px;display:flex;flex-direction:column}.stat::before{content:'';position:absolute;top:0;left:0;right:0;height:3px}.stat.total::before{background:var(--brand)}.stat.good::before{background:var(--good)}.stat.bad::before{background:var(--bad)}.stat.pending::before{background:#b26a00}.stat .num{font-size:24px;font-weight:800;line-height:1.2}.stat .lbl{color:var(--muted);font-size:12px;margin-top:2px}.stat.total .num{color:var(--brand)}.stat.good .num{color:var(--good)}.stat.bad .num{color:var(--bad)}.stat.pending .num{color:#b26a00}.section-label{display:flex;align-items:center;gap:8px;margin:0 0 12px;font-weight:800;color:var(--ink);font-size:15px;letter-spacing:.02em}.section-label:before,.section-label:after{content:none}.stage-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px;align-items:start}.stage-panel{min-width:0;background:#fff;border:1px solid var(--line);border-radius:16px;padding:14px;box-shadow:var(--card-shadow);border-top:4px solid var(--brand)}.stage-panel.es{border-top-color:#16805c}.stage-panel.milvus{border-top-color:#3867d6}.stage-panel.rrf{border-top-color:#b26a00}.stage-panel.rerank{border-top-color:#7a3ad6}.stage-list{max-height:calc(100vh - 280px);overflow-y:auto;padding-right:4px}.stage-panel .card{margin:8px 0;padding:12px;box-shadow:none}.card{background:#fff;border:1px solid var(--line);border-radius:13px;box-shadow:var(--card-shadow);margin:10px 0;padding:15px;transition:border-color .15s,background .15s}.card.selected-good{border-color:#7bd4b3;background:#f4fffa}.card.selected-bad{border-color:#e99aa5;background:#fff7f8}.cardhead{display:flex;gap:12px;align-items:center;flex-wrap:wrap}.rank{font-size:18px;font-weight:800;color:var(--brand);min-width:32px}.badge{border-radius:99px;padding:2px 10px;background:#eef2ff;color:var(--brand);font-size:12px;font-weight:600}.checks{margin-left:auto;display:flex;gap:12px}.checks label{cursor:pointer;user-select:none}.good{color:var(--good)}.bad{color:var(--bad)}.good.selected{background:#e6f7ef}.bad.selected{background:#fdecee}.text{white-space:pre-wrap;background:#fafbfc;border-radius:8px;padding:12px;margin-top:10px;max-height:220px;overflow:auto;border:1px solid #eef1f6}.docid{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12px;color:var(--muted);background:#f2f4f8;border-radius:6px;padding:2px 8px;word-break:break-all}.meta-row{display:flex;gap:6px;flex-wrap:wrap;margin-top:6px}.chip{display:inline-flex;align-items:center;gap:4px;border:1px solid var(--line);background:#fafbfc;border-radius:7px;padding:2px 8px;font-size:12px;color:var(--muted)}.chip b{color:var(--ink);font-weight:600}.rank-chip{background:var(--brand);border-color:var(--brand);color:#fff;font-weight:700;min-width:34px;justify-content:center}.kbadge{border-radius:99px;padding:2px 9px;font-size:12px;font-weight:600}.kbadge.legal{background:#eef2ff;color:#3867d6}.kbadge.medical{background:#e6f7ef;color:#16805c}.kbadge.technical{background:#fff3e0;color:#b26a00}.kbadge.qa{background:#fdecee;color:#c53d4f}.kbadge.prose{background:#f3e8fd;color:#7a3ad6}.kbadge.unknown{background:#eef1f6;color:#718096}.empty{text-align:center;padding:40px;color:var(--muted);background:#fff;border:1px dashed var(--line);border-radius:13px;margin:10px 0}.validation-result{margin:10px 0;border:1px solid var(--line);border-radius:13px;padding:14px;box-shadow:var(--card-shadow);background:#fff}.validation-result.good{border-color:#7bd4b3}.validation-result.bad{border-color:#e99aa5}.matrix-wrap{overflow-x:auto}.matrix{width:100%;border-collapse:separate;border-spacing:0;background:#fff;border:1px solid var(--line);border-radius:14px;overflow:hidden}.matrix th,.matrix td{padding:10px 12px;border-bottom:1px solid #edf0f5;font-size:13px;text-align:left;vertical-align:top}.matrix thead th{background:#f7f9fc;font-weight:800;position:sticky;top:0;z-index:2;white-space:nowrap;color:#40506b}.matrix thead th small{display:block;margin-top:2px;color:#9aa5b5;font-size:10px;font-weight:600}.matrix tbody tr:last-child td{border-bottom:0}.matrix tbody tr:hover td{background:#f8fbff}.matrix .cid-cell{width:180px;min-width:180px}.matrix .cid{display:block;font-family:ui-monospace,SFMono-Regular,monospace;font-size:11px;color:#52627c;word-break:break-all;line-height:1.4}.matrix .cell{border-left:1px solid #f0f2f7}.stage-cell .r{font-weight:800;font-size:15px}.stage-cell .sc{font-size:11px;color:var(--muted);display:block}.rank-top{color:var(--good)}.rank-mid{color:#b26a00}.rank-bot{color:var(--bad)}.miss{color:#c0c5cf;font-weight:600}.flag{font-size:11px;padding:3px 8px;border-radius:99px;white-space:nowrap}.flag.drop{background:#fdecee;color:var(--bad)}.flag.up{background:#e6f7ef;color:var(--good)}.matrix .text-cell{max-width:360px;min-width:260px}.matrix .snippet{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;color:#40506b;line-height:1.55}.matrix .expand{cursor:pointer;color:var(--brand);font-size:11px}.rank-cell{min-width:170px}.rerank-col{background:#f7f8ff;border-left:1px solid #dfe5ff!important}.matrix thead .rerank-col{background:#eaf0ff;color:var(--brand);box-shadow:inset 0 3px 0 var(--brand)}.rank-bar{position:relative;height:28px;min-width:150px;border-radius:8px;background:#eef1f6;overflow:hidden;display:flex;align-items:center;padding:0 9px;box-shadow:inset 0 0 0 1px rgba(35,52,86,.05)}.rank-bar-fill{position:absolute;inset:0 auto 0 0;border-radius:8px;opacity:.3;transition:width .25s ease}.rank-bar-content{position:relative;z-index:1;display:flex;align-items:baseline;gap:8px}.rank-bar-rank{font-weight:850;color:var(--ink);font-size:14px}.rank-bar-score{font-size:11px;color:#68758b}.unrecalled{display:inline-flex;align-items:center;min-height:28px;color:#aeb6c5;font-weight:700;padding:0 9px;background:#f7f8fa;border-radius:8px}.movement{display:inline-flex;align-items:center;gap:3px;margin-top:6px;font-size:12px;font-weight:850}.movement.up{color:var(--good)}.movement.down{color:var(--bad)}.movement.flat{color:var(--muted)}.matrix .checks{margin-top:8px;margin-left:0;white-space:nowrap}.matrix .checks label{padding:3px 6px;border-radius:6px}.matrix .checks input{accent-color:var(--brand)}.sumline{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px}.sumchip{background:#fff;border:1px solid var(--line);border-radius:99px;padding:4px 12px;font-size:12px;color:var(--muted)}.sumchip b{color:var(--ink);font-weight:700}.details-toggle{cursor:pointer;color:var(--brand);font-weight:600;font-size:13px;margin:12px 0 6px}.details-panel{display:none}.details-panel.open{display:block}.stage-mini{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;margin-top:8px}.stage-mini .stage-panel{border-top-width:3px}.stage-mini .stage-list{max-height:340px}@media(max-width:1100px){.stage-grid{grid-template-columns:repeat(2,minmax(0,1fr))} .stage-mini{grid-template-columns:1fr}}@media(max-width:860px){.shell{padding:14px}.controls{grid-template-columns:1fr}.stats{grid-template-columns:repeat(2,1fr)}.checks{margin-left:0}.toolbar .status{text-align:left}.stage-grid{grid-template-columns:1fr}.stage-list{max-height:none}}
</style><div class=shell><header class=hero><div><div class=eyebrow>RETRIEVAL REVIEW</div><h1>检索评测工作台</h1><div class=sub>输入真实问题，查看候选结果并标注相关性</div></div><div class=sub>本地只读检索 · 审核后保存</div></header><section class=panel><div class=controls><textarea id=q class=query placeholder='例如：Agent 如何工作的？'></textarea></div><div class=toolbar><button class='btn primary' onclick=search()>搜索候选</button><button class=btn onclick=save()>保存审核</button><button class='btn warn' onclick=validateCases()>校验评测集</button><span id=status class='status sub'></span></div></section><div id=validate></div><div id=stats class=stats></div><main id=out class=empty>输入问题后开始检索</main></div><script>let current=null;const $=id=>document.getElementById(id);function clearResults(){current=null;$('out').className='empty';$('out').textContent='搜索后显示候选结果';$('stats').innerHTML='';$('validate').innerHTML='';}function escapeHtml(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}function setStatus(text,isErr){let el=$('status');el.textContent=text;el.className=isErr?'status err':'status '+(text&&!text.includes('…')?'ok':'sub');}function statCard(num,label,cls){return `<div class="stat ${cls||''}"><div class=num>${num}</div><div class=lbl>${label}</div></div>`;}function updateStats(){let rel=new Set([...document.querySelectorAll('[data-r=rel]:checked')].map(x=>x.value)).size,bad=new Set([...document.querySelectorAll('[data-r=bad]:checked')].map(x=>x.value)).size,total=current?.candidates?.length||0;$('stats').innerHTML=statCard(total,'候选','total')+statCard(rel,'相关','good')+statCard(bad,'噪声','bad')+statCard(Math.max(0,total-rel-bad),'待审核','pending');}async function search(){let query=$('q').value.trim();if(!query)return alert('请输入问题');clearResults();setStatus('检索中…',false);let r=await fetch('/api/search',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({query})});current=await r.json();if(current.error){setStatus(current.error,true);$('out').className='empty';$('out').textContent=current.error;return;}let status={reranked:'已模型 rerank',fallback:'rerank 失败，已退回 RRF',skipped:'未启用 rerank'}[current.rerank_status]||'';setStatus(`已返回 ${current.candidates?.length||0} 条（${status}）`,current.rerank_status==='fallback');render();}function kindClass(k){return ['legal','medical','technical','qa','prose'].includes(k)?k:'unknown';}function stageBadges(cid){let s=(current.stage_rank||{})[cid]||{};let parts=[];for(let k of ['milvus','es','rrf','rerank']){let r=s[k];parts.push(r!=null?`${k.toUpperCase()}<b>#${r}</b>`:`${k.toUpperCase()}<b style=color:var(--muted)>-</b>`);}return `<span class='chip' style='background:#eef2ff'>${parts.join(' · ')}</span>`;}function renderGroup(key,label,annotate){let rows=(current.stages&&current.stages[key])||[];let title=`<div class=section-label>${label}<small class=sub>Top ${current.candidate_k} · ${rows.length} 条</small></div>`;let cards=rows.map(x=>`<article class=card data-chunk='${escapeHtml(x.chunk_id||'')}'><div class=cardhead><span class='chip rank-chip'>#${x.rank}</span><span class='kbadge ${kindClass(x.kind)}'>${escapeHtml(x.kind||'unknown')}</span><span class=checks>${annotate?`<label class='good'><input type=checkbox data-r=rel value='${escapeHtml(x.chunk_id||'')}' data-chunk='${escapeHtml(x.chunk_id||'')}' onchange="toggle(this,'good')"> 相关</label><label class='bad'><input type=checkbox data-r=bad value='${escapeHtml(x.chunk_id||'')}' data-chunk='${escapeHtml(x.chunk_id||'')}' onchange="toggle(this,'bad')"> 噪声</label>`:''}</span></div><div class=meta-row>${stageBadges(x.chunk_id)}<span class=chip>分数 <b>${Number(x.score).toFixed(4)}</b></span>${x.page!=null?`<span class=chip>页 <b>${x.page}</b></span>`:''}${x.section_path&&x.section_path.length?`<span class=chip>${escapeHtml(x.section_path.join(' › '))}</span>`:''}</div><div class=docid>${escapeHtml(x.chunk_id||'')}</div><div class=text>${escapeHtml(x.text)}</div></article>`).join('');return `<section class='stage-panel ${key}'><div class=stage-list>${title}${cards||'<div class=empty>本阶段无结果</div>'}</div></section>`;}function toggle(box,kind){let cid=box.dataset.chunk,same=box.checked;let owner=document.querySelector(`[data-r=${kind}][data-chunk="${CSS.escape(cid||'')}"]`);if(owner&&owner!==box){owner.checked=same;owner.closest('label').classList.toggle('selected',same);}let other=box.closest('.card').querySelector(`[data-r=${kind==='good'?'bad':'rel'}]`);if(other){if(same)other.checked=false;if(same)other.closest('label').classList.remove('selected');}let cards=document.querySelectorAll(`.card[data-chunk="${CSS.escape(cid||'')}"]`);cards.forEach(card=>card.classList.toggle('selected-'+kind,same));updateStats();}function rankClass(r){if(r==null)return'miss';return r<=5?'rank-top':r<=15?'rank-mid':'rank-bot';}function rankColor(r){return r<=5?'#16805c':r<=15?'#b26a00':'#c53d4f';}function barWidth(r,n){return n>0?Math.max(6,Math.round(100*(1-(r-1)/n))):100;}function stageCell(s,key,poolN){let r=s[key],v=s[key+'_score'];if(r==null)return`<span class='unrecalled'>未召回</span>`;let w=barWidth(r,poolN||r),c=rankColor(r);return`<div class='rank-bar'><div class='rank-bar-fill' style='width:${w}%;background:${c}'></div><div class='rank-bar-content'><span class='rank-bar-rank'>#${r}</span><span class='rank-bar-score'>${v==null?'':Number(v).toFixed(4)}</span></div></div>`;}function matrixRows(){let ids=new Set();for(let key of ['milvus','es','rrf','rerank'])for(let x of(current.stages?.[key]||[]))if(x.chunk_id)ids.add(x.chunk_id);let rank=current.stage_rank||{};return [...ids].sort((a,b)=>{let x=rank[a]||{},y=rank[b]||{};return (x.rerank??Infinity)-(y.rerank??Infinity)||(x.rrf??Infinity)-(y.rrf??Infinity)||(x.milvus??Infinity)-(y.milvus??Infinity);});}function matrixRow(cid,pool){let s=(current.stage_rank||{})[cid]||{},rerankTop=(current.candidates||[]).some(x=>x.chunk_id===cid),source=(current.stages?.rerank||[]).find(x=>x.chunk_id===cid)||(current.stages?.rrf||[]).find(x=>x.chunk_id===cid)||(current.stages?.milvus||[]).find(x=>x.chunk_id===cid)||(current.stages?.es||[]).find(x=>x.chunk_id===cid)||{};let movement='';if(s.rerank!=null&&s.rrf!=null){let delta=s.rrf-s.rerank;movement=delta>0?`<span class='movement up'>▲ 提升 ${delta}</span>`:delta<0?`<span class='movement down'>▼ 下降 ${-delta}</span>`:`<span class='movement flat'>— 持平</span>`;}else if(s.rerank==null&&s.rrf!=null){movement=`<span class='movement down'>↓ 未进精排</span>`;}return `<tr data-chunk='${escapeHtml(cid)}'><td class='cid-cell'><span class=cid>${escapeHtml(cid)}</span>${kindClass(source.kind)!=='unknown'?`<span class='kbadge ${kindClass(source.kind)}'>${escapeHtml(source.kind||'')}</span>`:''}</td><td class=text-cell><div class=snippet title='${escapeHtml(source.text||'')}'>${escapeHtml(source.text||'')}</div></td><td class='cell rank-cell'>${stageCell(s,'es',pool.es)}</td><td class='cell rank-cell'>${stageCell(s,'milvus',pool.milvus)}</td><td class='cell rank-cell'>${stageCell(s,'rrf',pool.rrf)}</td><td class='cell rank-cell rerank-col'>${stageCell(s,'rerank',pool.rerank)}${movement}${rerankTop?`<div class=checks><label class=good><input type=checkbox data-r=rel value='${escapeHtml(cid)}' onchange="toggleMatrix(this,'good')"> 相关</label><label class=bad><input type=checkbox data-r=bad value='${escapeHtml(cid)}' onchange="toggleMatrix(this,'bad')"> 噪声</label></div>`:''}</td></tr>`;}function stagePool(stage){let m=0;for(let c in(current.stage_rank||{})){let r=(current.stage_rank[c]||{})[stage];if(r&&r>m)m=r;}return m;}function renderMatrix(){let ids=matrixRows(),sr=current.stages||{};let pool={es:stagePool('es'),milvus:stagePool('milvus'),rrf:stagePool('rrf'),rerank:stagePool('rerank')};let table=`<div class=matrix-wrap><table class=matrix><thead><tr><th>Chunk</th><th>内容</th><th>ES<small>BM25 · ${sr.es?.length||0}</small></th><th>Milvus<small>向量 · ${sr.milvus?.length||0}</small></th><th>RRF<small>融合 · ${sr.rrf?.length||0}</small></th><th class='rerank-col'>Reranker<small>精排 · ${sr.rerank?.length||0}</small></th></tr></thead><tbody>${ids.map(cid=>matrixRow(cid,pool)).join('')}</tbody></table></div>`;let detail=`<div class=details-toggle onclick="this.nextElementSibling.classList.toggle('open')">▶ 查看四路原始列表详情</div><div class='details-panel'><div class=stage-mini>${[['es','ES（全文 BM25）',false],['milvus','Milvus（向量）',false],['rrf','RRF（融合）',false],['rerank','Reranker（模型精排）',true]].map(g=>renderGroup(g[0],g[1],g[2])).join('')}</div></div>`;return table+detail;}function render(){$('out').className='';$('out').innerHTML=renderMatrix();updateStats();}function toggleMatrix(box,kind){let card=box.closest('tr'),cid=box.value,other=card.querySelector(`[data-r=${kind==='good'?'bad':'rel'}]`);if(box.checked&&other){other.checked=false;}box.closest('label').classList.toggle('selected',box.checked);card.classList.toggle('selected-'+kind,box.checked);updateStats();}async function save(){if(!current)return alert('请先搜索');if(!document.querySelector('[data-r=rel]:checked')&&!confirm('未勾选任何「相关」chunk，保存后不会进入正式评测集。仍要保存吗？'))return;let ids=r=>[...document.querySelectorAll(`[data-r=${r}]:checked`)].map(x=>x.value);let body={...current,relevant_chunk_ids:ids('rel'),forbidden_chunk_ids:ids('bad'),expected_sections:[]};let r=await fetch('/api/save',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body)});let data=await r.json();setStatus(data.message||data.error,!!data.error);if(!data.error){clearResults();setStatus(data.message||'已保存并清空候选',false);}}async function validateCases(){let el=$('validate');setStatus('校验中…',false);clearResults();el.innerHTML='<div class="empty">校验中…</div>';let r=await fetch('/api/validate_cases',{method:'POST'});let d=await r.json();if(d.error){setStatus(d.error,true);el.innerHTML='';return;}setStatus(`校验完成：共 ${d.total} 条，${d.stale_cases} 条失效`,d.stale_cases>0||d.empty_relevant_cases>0);let issues=d.issues.filter(i=>i.stale_ids.length||i.empty_relevant);if(!issues.length){el.innerHTML=`<div class="validation-result good"><div style="font-weight:700;color:var(--good)">✓ 校验通过</div><div class=sub>共 ${d.total} 条用例，无失效 id、无空相关标注</div></div>`;return;}let html=`<div class="validation-result bad"><div style="font-weight:700;color:var(--bad)">✗ 发现 ${issues.length} 条问题：${d.stale_cases} 条含失效 id，${d.empty_relevant_cases} 条空相关</div></div>`;html+=issues.map(c=>`<div class=card><div class=cardhead><span class=badge style='background:#fdecee;color:var(--bad)'>${c.stale_ids.length?'失效':'空相关'}</span><b>${escapeHtml(c.query||'')}</b><span class=meta>${escapeHtml(c.id||'')}</span></div><div class=meta style=margin-top:6px>${c.stale_ids.length?('<span class=bad>失效 id: </span>'+escapeHtml(c.stale_ids.join(', '))):'<span class=bad>无 relevant_chunk_ids</span>'}</div></div>`).join('');el.innerHTML=html;}
</script></html>""")

def _row_to_item(row, rank):
    """把策略返回的 row dict 转成前端展示用的 item。"""
    return {
        "rank": rank, "chunk_id": row.get("chunk_id"),
        "score": float(row.get("score", 0.0)),
        "document_id": row.get("document_id", ""), "page": row.get("page"),
        "kind": row.get("kind"), "section_path": _as_section_path(row.get("section_path")),
        "text": row.get("text", ""),
    }


def _stage_rank(stages):
    """由服务端根据真实阶段列表计算每个 chunk 的 rank/score。"""
    result = {}
    for name, rows in stages.items():
        for rank, row in enumerate(rows, 1):
            cid = row.get("chunk_id")
            if not cid:
                continue
            item = result.setdefault(cid, {})
            item[name] = rank
            item[f"{name}_score"] = float(row.get("score", 0.0))
    return result


def _as_section_path(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            return [value] if value else []
    return list(value or [])


@app.post("/api/search")
def search(request: QueryRequest):
    top_k = request.top_k if request.top_k is not None else int(os.getenv("TOP_K", "20"))
    if not request.query.strip() or not 1 <= top_k <= 100:
        raise ValidationError("参数无效")
    service = _ensure_retriever()
    query = request.query
    # 统一走 hybrid，所有阶段由应用服务一次计算，避免审核链路与生产链路分叉。
    try:
        result = service.hybrid_stages(query)
    except ValueError as exc:
        return {"error": str(exc)}
    raw_stages = {"milvus": result.milvus, "es": result.es,
                  "rrf": result.rrf, "rerank": result.rerank}
    recall_k = int(os.getenv("RECALL_K", "100"))
    rerank_k = int(os.getenv("RERANK_K", "100"))
    # 四路展示各自的数量：ES/Milvus 按召回数，RRF 见完整融合，Reranker 按精排池。
    # TOP_K 只决定最终标注/评测范围，不再截断各阶段展示。
    stage_limits = {"milvus": recall_k, "es": recall_k, "rrf": None, "rerank": rerank_k}
    stages = {}
    for name, rows in raw_stages.items():
        limit = stage_limits[name]
        shown = rows if limit is None else rows[:limit]
        stages[name] = [_row_to_item(row, rank) for rank, row in enumerate(shown, 1)]
    # stage_rank 保留完整候选池中的真实排名。
    stage_rank = _stage_rank(raw_stages)
    final_candidates = stages["rerank"][:top_k]
    return {"id": _case_id(query), "query": query,
            "candidate_k": top_k, "rerank_enabled": service.reranker is not None,
            "rerank_status": result.rerank_status,
            "stages": stages, "stage_rank": stage_rank,
            "candidates": final_candidates}

@app.post("/api/save")
def save(request: SaveRequest):
    allowed = {item.get("chunk_id") for item in request.candidates}
    relevant_ids = list(dict.fromkeys(request.relevant_chunk_ids))
    forbidden_ids = list(dict.fromkeys(request.forbidden_chunk_ids))
    relevant = set(relevant_ids); forbidden = set(forbidden_ids)
    if not request.query.strip() or not relevant <= allowed or not forbidden <= allowed or relevant & forbidden:
        return {"error": "审核 ID 无效或相关/噪声重复"}
    relevant_rankings = {
        cid: request.stage_rank[cid] for cid in relevant if cid in request.stage_rank
    }
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
    record = request.model_dump()
    record["relevant_chunk_ids"] = relevant_ids
    record["forbidden_chunk_ids"] = forbidden_ids
    record["relevant_rankings"] = relevant_rankings
    existing.append(record)
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
