"""生成 TRAE 用量监控页面

两种模式:
  python gen_index.py              # 生成静态页面 trae_usage_card.html（可直接双击打开）
  python gen_index.py --server     # 生成 index.html（配合 serve.py 使用，从 /api/data 加载）
"""
import argparse
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent
DATA_FILE = BASE / "trae_usage_data.json"

CSS = """
:root{--bg:#0b0e14;--panel:#0d1117;--panel2:#111726;--line:#1c2436;--txt:#e6edf3;--muted:#8b96a8;--dim:#5b6678;--acc:#6c5ce7;--acc2:#00cec9;--green:#2ecc71;--warn:#f39c12;--red:#e74c3c;--grad:linear-gradient(135deg,#6c5ce7,#00cec9)}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:"Segoe UI","Microsoft YaHei",system-ui,sans-serif;background:var(--bg);color:var(--txt);min-height:100vh;padding:24px 16px;background-image:radial-gradient(900px 400px at 15% -5%,rgba(108,92,231,.12),transparent 60%),radial-gradient(700px 350px at 95% 0%,rgba(0,206,201,.10),transparent 60%)}
.wrap{max-width:960px;margin:0 auto}
.head{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-bottom:18px}
.brand{display:flex;align-items:center;gap:12px}
.logo{width:42px;height:42px;border-radius:11px;background:var(--grad);display:flex;align-items:center;justify-content:center;font-weight:800;font-size:20px;box-shadow:0 4px 20px rgba(108,92,231,.45)}
.brand h1{font-size:20px;letter-spacing:.5px}
.brand .sub{font-size:12px;color:var(--muted)}
.status{display:flex;align-items:center;gap:8px;font-size:13px;color:var(--muted);background:var(--panel);border:1px solid var(--line);border-radius:20px;padding:6px 14px;cursor:pointer;transition:border-color .2s}
.status:hover{border-color:var(--acc)}
.dot{width:8px;height:8px;border-radius:50%;background:var(--green);box-shadow:0 0 8px var(--green);animation:pulse 2s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:14px}
.kpi{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:14px 16px;position:relative;overflow:hidden}
.kpi::before{content:"";position:absolute;inset:0 0 auto 0;height:2px;background:var(--grad);opacity:.85}
.kpi .label{font-size:12px;color:var(--muted)}
.kpi .value{font-size:26px;font-weight:700;margin-top:6px;font-variant-numeric:tabular-nums}
.kpi .unit{font-size:12px;color:var(--muted);font-weight:400;margin-left:2px}
.kpi .trend{font-size:11px;margin-top:4px;color:var(--dim)}
.kpi .val-acc{background:var(--grad);-webkit-background-clip:text;background-clip:text;color:transparent}
.row{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:14px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:16px}
.card h3{font-size:13px;color:var(--muted);font-weight:600;margin-bottom:12px;display:flex;align-items:center;gap:8px}
.badge{display:inline-flex;align-items:center;gap:6px;padding:4px 12px;border-radius:20px;font-size:12px;font-weight:600}
.badge.on{background:rgba(46,204,113,.14);color:var(--green);border:1px solid rgba(46,204,113,.4)}
.badge.off{background:rgba(243,156,18,.12);color:var(--warn);border:1px solid rgba(243,156,18,.4)}
.sign-main{display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap}
.sign-credit{font-size:34px;font-weight:800;background:var(--grad);-webkit-background-clip:text;background-clip:text;color:transparent}
.sign-credit small{font-size:13px;font-weight:400;-webkit-text-fill-color:var(--muted)}
.week{display:grid;grid-template-columns:repeat(7,1fr);gap:6px;margin-top:14px}
.wday{text-align:center}
.wday .wd{font-size:10px;color:var(--dim);margin-bottom:4px}
.wday .cell{height:30px;border-radius:8px;border:1px solid var(--line);background:var(--panel2);display:flex;align-items:center;justify-content:center;font-size:11px;color:var(--dim)}
.wday .cell.on{background:var(--grad);color:#fff;border-color:transparent;box-shadow:0 2px 10px rgba(108,92,231,.4)}
.wday .cell.miss{background:rgba(231,76,60,.12);color:var(--red);border-color:rgba(231,76,60,.35)}
.wday .cell.today{border-color:var(--acc2)}
.wday .cell.future{border-style:dashed;opacity:.45}
.wday .cell.unknown{border-style:dashed;opacity:.35}
.chart{display:flex;align-items:flex-end;gap:10px;height:150px;padding:6px 4px 0}
.bar-col{flex:1;display:flex;flex-direction:column;align-items:center;gap:6px;height:100%;justify-content:flex-end}
.bar-track{width:100%;max-width:44px;height:100%;display:flex;align-items:flex-end;background:var(--panel2);border-radius:6px;position:relative;overflow:hidden}
.bar{width:100%;border-radius:6px;background:var(--grad);min-height:2px;transition:height .6s cubic-bezier(.2,.8,.2,1)}
.bar.hot{box-shadow:0 0 14px rgba(108,92,231,.5)}
.bar-val{font-size:11px;color:var(--muted);font-variant-numeric:tabular-nums}
.bar-date{font-size:11px;color:var(--dim)}
.legend{font-size:11px;color:var(--dim);margin-top:8px;display:flex;gap:14px}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;color:var(--dim);font-weight:500;font-size:11px;padding:8px 10px;border-bottom:1px solid var(--line)}
td{padding:9px 10px;border-bottom:1px solid rgba(28,36,54,.6);font-variant-numeric:tabular-nums}
tr:hover td{background:rgba(108,92,231,.05)}
.mini-bar{height:5px;border-radius:3px;background:var(--grad);display:inline-block;vertical-align:middle;margin-left:8px}
.day-cell{display:flex;align-items:center}
.day-cell .dd{min-width:86px}
.pill{font-size:10px;padding:2px 8px;border-radius:10px;background:var(--panel2);color:var(--muted);border:1px solid var(--line)}
.foot{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-top:14px}
.btn{display:inline-flex;align-items:center;gap:6px;border:none;cursor:pointer;font-size:13px;font-weight:600;padding:9px 16px;border-radius:10px;color:#fff;background:var(--grad);transition:filter .15s,transform .1s}
.btn:hover{filter:brightness(1.1)}
.btn:active{transform:translateY(1px)}
.btn.ghost{background:var(--panel2);color:var(--txt);border:1px solid var(--line)}
.tags{display:flex;gap:8px;flex-wrap:wrap}
.tag{font-size:11px;color:var(--muted);padding:4px 10px;border-radius:8px;background:var(--panel);border:1px solid var(--line)}
.tag b{color:var(--acc2)}
.hint{font-size:11px;color:var(--dim);margin-top:8px}
#toast{position:fixed;left:50%;bottom:24px;transform:translateX(-50%) translateY(20px);background:var(--panel);border:1px solid var(--acc);color:var(--txt);padding:10px 18px;border-radius:10px;font-size:13px;opacity:0;pointer-events:none;transition:opacity .25s,transform .25s;z-index:99;box-shadow:0 8px 30px rgba(0,0,0,.5)}
#toast.show{opacity:1;transform:translateX(-50%) translateY(0)}
@keyframes spin{0%{transform:rotate(0)}100%{transform:rotate(360deg)}}
.spinner{width:14px;height:14px;border:2px solid var(--dim);border-top-color:var(--acc);border-radius:50%;animation:spin .8s linear infinite;display:inline-block}
#loading{text-align:center;padding:60px;color:var(--muted);font-size:14px}
@media(max-width:720px){.kpis{grid-template-columns:repeat(2,1fr)}.row{grid-template-columns:1fr}}
"""

JS = r"""
function fmt(n){return(Math.round(n*100)/100).toLocaleString('zh-CN')}
function toast(msg){const t=document.getElementById('toast');t.textContent=msg;t.classList.add('show');setTimeout(()=>t.classList.remove('show'),2600)}

function renderAll(DATA){
  document.getElementById('loading')?.remove();
  document.getElementById('app').style.display='block';
  document.getElementById('subline').textContent=
    '数据更新于 '+DATA.fetched_at+'  \u00b7  '+DATA.user.username+' \u00b7 '+DATA.user.product;

  const u=DATA.overall_usage||{total_limit:0,total_used:0,remaining:0};
  const today=DATA.daily[DATA.daily.length-1];
  const kpis=[
    {label:'今日消耗',value:fmt(today.consumed),unit:'积分',trend:today.sessions+' 个会话',cls:''},
    {label:'本月累计',value:fmt(DATA.month_total),unit:'积分',trend:'截止今日',cls:'val-acc'},
    {label:'剩余积分',value:fmt(u.remaining),unit:'积分',trend:'总额 '+fmt(u.total_limit),cls:'val-acc'},
    {label:'连续签到',value:DATA.continuous_days,unit:'天',trend:'今日已领 '+(DATA.checkin?.credits||0),cls:''},
  ];
  document.getElementById('kpis').innerHTML=kpis.map(k=>
    '<div class="kpi"><div class="label">'+k.label+'</div><div class="value '+k.cls+'">'+k.value+'<span class="unit">'+k.unit+'</span></div><div class="trend">'+k.trend+'</div></div>'
  ).join('');

  const ci=DATA.checkin||{};
  const badge=document.getElementById('badge');
  if(ci.checked_in){badge.className='badge on';badge.textContent='\u2714 今日已签到'}
  else{badge.className='badge off';badge.textContent='\u2718 今日未签到'}
  document.getElementById('sign-credit').innerHTML=fmt(ci.credits||0)+'<small> 积分</small>';
  document.getElementById('streak').innerHTML='连续签到 <b style="color:var(--acc2)">'+(DATA.continuous_days||0)+'</b> 天';
  document.getElementById('sign-note').textContent=ci.checked_in?'\u6bcf\u65e5\u7b7e\u5230 +'+fmt(ci.credits||0)+' \u79ef\u5206':'\u53bb TRAE \u5b8c\u6210\u4eca\u65e5\u7b7e\u5230';

  (function(){
    const now=new Date();const monday=new Date(now);monday.setDate(now.getDate()-((now.getDay()+6)%7));
    const hist=DATA.signin_history||{};const wd=['\u4e00','\u4e8c','\u4e09','\u56db','\u4e94','\u516d','\u65e5'];
    const html=[];
    for(let i=0;i<7;i++){const d=new Date(monday);d.setDate(monday.getDate()+i);
      const key=d.toISOString().slice(0,10);const isFuture=d>now;const isToday=d.toDateString()===now.toDateString();
      const rec=hist[key];let cls='cell';
      if(isFuture)cls+=' future';else if(rec===true)cls+=' on';else if(rec===false)cls+=' miss';else cls+=' unknown';
      if(isToday)cls+=' today';
      html.push('<div class="wday"><div class="wd">\u5468'+wd[i]+(isToday?'\u00b7\u4eca':'')+'</div><div class="'+cls+'">'+(rec===true?'\u2714':isFuture?'\u00b7':isToday?'\u2026':'')+'</div></div>');
    }
    document.getElementById('week').innerHTML=html.join('');
  })();

  (function(){
    const ds=DATA.daily;const max=Math.max(...ds.map(d=>d.consumed),1);
    const maxIdx=ds.reduce((a,d,i)=>d.consumed>ds[a].consumed?i:a,0);
    document.getElementById('chart').innerHTML=ds.map((d,i)=>{
      const h=Math.max(d.consumed/max*100,2);const hot=i===maxIdx&&d.consumed>0;
      return '<div class="bar-col" title="'+d.date+' \u6d88\u8017 '+fmt(d.consumed)+' \u79ef\u5206 ('+d.sessions+' \u4f1a\u8bdd)"><div class="bar-val">'+fmt(d.consumed)+'</div><div class="bar-track"><div class="bar '+(hot?'hot':'')+'" style="height:'+h+'%"></div></div><div class="bar-date">'+d.date.slice(5).replace('-','/')+'</div></div>';
    }).join('');
  })();

  (function(){
    const ds=DATA.daily,m=DATA.month_total||1;
    document.getElementById('tbody').innerHTML=ds.slice().reverse().map(d=>{
      const ratio=d.consumed/m*100;
      const top=d.details&&d.details.length?Math.max(...d.details.map(x=>x.credits)):0;
      return '<tr><td><div class="day-cell"><span class="dd">'+d.date+'</span>'+(d.days_ago===0?'<span class="pill">\u4eca\u5929</span>':'')+'</div></td><td>'+fmt(d.consumed)+'</td><td>'+d.sessions+'</td><td><span style="color:var(--muted)">'+ratio.toFixed(1)+'%</span><span class="mini-bar" style="width:'+Math.max(ratio*2,2)+'px"></span></td><td>'+fmt(top)+'</td></tr>';
    }).join('');
  })();
}

let lastFetchAt=0;
let serverMode=false;

async function loadData(){
  if(!serverMode){renderAll(EMBEDDED_DATA);return}
  try{
    const r=await fetch('/api/data?t='+Date.now());
    const DATA=await r.json();
    if(DATA.error){document.getElementById('loading').textContent='\u6570\u636e\u52a0\u8f7d\u5931\u8d25: '+DATA.error;return}
    renderAll(DATA);
    lastFetchAt=new Date(DATA.fetched_at).getTime()||Date.now();
  }catch(e){
    document.getElementById('loading').textContent='\u65e0\u6cd5\u8fde\u63a5\u670d\u52a1\u5668: '+e.message;
  }
}

async function checkUpdate(){
  if(!serverMode)return;
  try{
    const r=await fetch('/api/status');
    const s=await r.json();
    if(s.last_refresh>lastFetchAt/1000+5){loadData();toast('\u6570\u636e\u5df2\u81ea\u52a8\u66f4\u65b0')}
  }catch(e){}
}

async function doRefresh(){
  if(!serverMode){toast('\u9759\u6001\u6a21\u5f0f\u4e0d\u652f\u6301\u5728\u7ebf\u5237\u65b0\uff0c\u8bf7\u91cd\u65b0\u8fd0\u884c python trae_usage_api.py');return}
  const btn=document.getElementById('btn-refresh');
  btn.disabled=true;btn.innerHTML='<span class="spinner"></span> \u6293\u53d6\u4e2d...';
  document.getElementById('runstate').textContent='\u6b63\u5728\u6293\u53d6...';
  try{
    await fetch('/api/refresh');
    toast('\u6293\u53d6\u5df2\u542f\u52a8\uff0c\u8bf7\u7b49\u5f85\u7ea660\u79d2');
    setTimeout(()=>{loadData();btn.disabled=false;btn.innerHTML='\ud83d\udd04 \u7acb\u5373\u6293\u53d6'},65000);
  }catch(e){
    toast('\u5237\u65b0\u5931\u8d25: '+e.message);btn.disabled=false;btn.innerHTML='\ud83d\udd04 \u7acb\u5373\u6293\u53d6';
  }
}

function exportCSV(){
  const DATA=serverMode?null:EMBEDDED_DATA;
  if(DATA){buildCSV(DATA);return}
  fetch('/api/data').then(r=>r.json()).then(buildCSV);
}
function buildCSV(DATA){
  const rows=[['\u65e5\u671f','\u6d88\u8017\u79ef\u5206','\u4f1a\u8bdd\u6570','\u6700\u9ad8\u5355\u6b21'],...DATA.daily.map(d=>[
    d.date,d.consumed,d.sessions,d.details&&d.details.length?Math.max(...d.details.map(x=>x.credits)):0])];
  const csv=rows.map(r=>r.join(',')).join('\n');
  const blob=new Blob(['\ufeff'+csv],{type:'text/csv;charset=utf-8'});
  const a=document.createElement('a');a.href=URL.createObjectURL(blob);
  a.download='trae_usage_'+new Date().toISOString().slice(0,10)+'.csv';a.click();
  toast('CSV \u5df2\u5bfc\u51fa');
}

window.addEventListener('DOMContentLoaded',()=>{
  loadData();
  setInterval(checkUpdate,60*1000);
});
"""

BODY = r"""
<div class="wrap">
  <div class="head">
    <div class="brand">
      <div class="logo">T</div>
      <div>
        <h1>TRAE \u7528\u91cf\u76d1\u63a7\u9762\u677f</h1>
        <div class="sub" id="subline">\u52a0\u8f7d\u4e2d...</div>
      </div>
    </div>
    <div class="status" id="status-dot" onclick="doRefresh()">
      <span class="dot" id="dot"></span>
      <span id="runstate">\u5df2\u5c31\u7eea</span>
    </div>
  </div>
  <div id="loading"><span class="spinner"></span> \u52a0\u8f7d\u6570\u636e\u4e2d...</div>
  <div id="app" style="display:none">
    <div class="kpis" id="kpis"></div>
    <div class="row">
      <div class="card">
        <h3>\u26f3 \u4eca\u65e5\u7b7e\u5230</h3>
        <div class="sign-main">
          <div>
            <span class="badge" id="badge">--</span>
            <div style="margin-top:8px" class="sign-credit" id="sign-credit">--<small> \u79ef\u5206</small></div>
          </div>
          <div style="text-align:right;font-size:12px;color:var(--muted)">
            <div id="streak">\u8fde\u7eed\u7b7e\u5230 <b style="color:var(--acc2)">--</b> \u5929</div>
            <div style="margin-top:4px" id="sign-note">--</div>
          </div>
        </div>
        <div class="week" id="week"></div>
      </div>
      <div class="card">
        <h3>\ud83d\udcca \u6700\u8fd17\u5929\u6d88\u8017</h3>
        <div class="chart" id="chart"></div>
        <div class="legend"><span>\u25aa \u5cf0\u503c\u65e5\u9ad8\u4eae</span><span>\u25aa \u60ac\u505c\u67e5\u770b\u6570\u503c</span></div>
      </div>
    </div>
    <div class="card" style="margin-bottom:0">
      <h3>\ud83d\udcc5 \u6bcf\u65e5\u660e\u7ec6</h3>
      <table>
        <thead><tr><th>\u65e5\u671f</th><th>\u6d88\u8017\u79ef\u5206</th><th>\u4f1a\u8bdd\u6570</th><th>\u5360\u6bd4(\u6708\u7d2f\u8ba1)</th><th>\u6700\u9ad8\u5355\u6b21</th></tr></thead>
        <tbody id="tbody"></tbody>
      </table>
    </div>
    <div class="foot">
      <div>
        <button class="btn" id="btn-refresh" onclick="doRefresh()">\ud83d\udd04 \u7acb\u5373\u6293\u53d6</button>
        <button class="btn ghost" style="margin-left:8px" onclick="exportCSV()">\ud83d\udce5 \u5bfc\u51faCSV</button>
      </div>
      <div class="tags">
        <span class="tag">\u2699\ufe0f <b>Python</b></span>
        <span class="tag">\ud83d\udd11 <b>refresh_token</b></span>
        <span class="tag">\ud83d\ude80 <b>TRAE API</b></span>
      </div>
    </div>
    <div class="hint" id="hint"></div>
  </div>
</div>
<div id="toast"></div>
"""


def gen_static():
    """生成静态页面，数据直接嵌入 HTML，可双击打开。"""
    if not DATA_FILE.exists():
        print("错误: trae_usage_data.json 不存在，请先运行 python trae_usage_api.py")
        return
    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    data_json = json.dumps(data, ensure_ascii=False)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>TRAE \u7528\u91cf\u76d1\u63a7\u9762\u677f</title>
<style>{CSS}</style>
</head>
<body>
{BODY}
<script>
const serverMode=false;
const EMBEDDED_DATA={data_json};
{JS}
</script>
</body>
</html>"""

    out = BASE / "trae_usage_card.html"
    out.write_text(html, encoding="utf-8")
    print(f"\u2713 \u9759\u6001\u9875\u9762\u5df2\u751f\u6210: {out}")
    print("  \u53cc\u6253\u6253\u5f00\u5373\u53ef\u67e5\u770b\uff0c\u65e0\u9700\u670d\u52a1\u5668")


def gen_server():
    """生成服务器版 index.html，从 /api/data 加载数据。"""
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>TRAE \u7528\u91cf\u76d1\u63a7\u9762\u677f</title>
<style>{CSS}</style>
</head>
<body>
{BODY}
<script>
const serverMode=true;
{JS}
</script>
</body>
</html>"""

    out = BASE / "index.html"
    out.write_text(html, encoding="utf-8")
    print(f"\u2713 \u670d\u52a1\u5668\u7248\u9875\u9762\u5df2\u751f\u6210: {out}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TRAE \u7528\u91cf\u76d1\u63a7\u9875\u9762\u751f\u6210\u5668")
    parser.add_argument("--server", action="store_true", help="\u751f\u6210\u670d\u52a1\u5668\u7248 index.html")
    args = parser.parse_args()
    if args.server:
        gen_server()
    else:
        gen_static()
