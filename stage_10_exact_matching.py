import http.server
import json
import os
import secrets
import threading
import webbrowser
import hashlib
import urllib.request
REFERENCE_CODE={}
QWEN_LOCK=threading.Lock()
def payload(h):
    n=int(h.headers.get("Content-Length","0"));return json.loads(h.rfile.read(n).decode())
def qwen_reference(title):
    body={"model":os.environ.get("MAZE_SEMANTIC_MODEL","qwen3:8b"),"stream":False,"think":False,"format":"json","messages":[{"role":"system","content":"Return JSON only: {\"code\":\"<python source>\"}. Produce one minimal canonical Python answer for the task."},{"role":"user","content":title}],"options":{"temperature":0,"num_predict":500}}
    url=os.environ.get("MAZE_OLLAMA_URL","http://127.0.0.1:11434").rstrip("/")+"/api/chat"
    req=urllib.request.Request(url,data=json.dumps(body).encode(),headers={"Content-Type":"application/json"})
    with QWEN_LOCK, urllib.request.urlopen(req,timeout=90) as r: outer=json.loads(r.read().decode())
    code=json.loads(outer["message"]["content"])["code"];compile(code,"<reference>","exec");return code.strip()
def handle_post(self):
    try:
        p=payload(self)
        if self.path=="/prepare_task":
            title=str(p.get("task","")).strip();code=qwen_reference(title);key=hashlib.sha256(title.encode()).hexdigest();REFERENCE_CODE[key]={"title":title,"code":code};return self.send(200,json.dumps({"reference_key":key,"reference_code":code}),"application/json")
        if self.path=="/check_task":
            e=REFERENCE_CODE.get(p.get("reference_key",""));ok=bool(e and p.get("code","")==e["code"]);return self.send(200,json.dumps({"verified":ok,"message":"MET" if ok else "NOT MET"}),"application/json")
        return self.send(404,"Not found")
    except Exception as e:return self.send(400,json.dumps({"error":str(e)}),"application/json")
Handler.handle_post=handle_post

HOST, PORT = "127.0.0.1", int(os.environ.get("MAZE_PORT", "8000"))
TOKEN = secrets.token_urlsafe(24)
HTML = r"""<!doctype html><html><head><meta charset="utf-8"><title>Codify Maze</title><style>*{box-sizing:border-box}body{margin:0;background:#090909;color:#eee;font-family:Arial}#app{display:grid;grid-template-columns:330px 1fr;height:100vh}#left{padding:16px;border-right:1px solid #333;overflow:auto}#right{position:relative;min-width:0}textarea,input{width:100%;background:#111;color:#fff;border:1px solid #444;border-radius:8px;padding:10px;margin:6px 0 12px}button{background:#191919;color:#fff;border:1px solid #555;border-radius:8px;padding:9px 12px;cursor:pointer}canvas{width:100%;height:100%;display:block;background:#050505}#player{position:absolute;border-radius:50%;background:#b25cff;border:2px solid #f2d6ff;pointer-events:none}#modalShade{position:fixed;inset:0;background:#000b;display:none;align-items:center;justify-content:center;padding:20px}#modal{width:min(720px,92vw);background:#111;border:1px solid #555;border-radius:12px;padding:16px}.good{color:#8cff9a}.bad{color:#ff7b7b}</style></head><body><div id="app"><section id="left"><h2>Codify Maze</h2><p style="font-size:12px;color:#aaa">Each task must start with <b>Using ...</b></p><textarea id="tasks" rows="14"></textarea><button id="generate">Generate Maze</button><div id="msg"></div></section><section id="right"><canvas id="maze"></canvas><div id="player"></div></section></div><div id="modalShade"><div id="modal"><h3 id="cpTitle"></h3><div id="taskText"></div><label>Qwen answer</label><textarea id="reference" rows="8" readonly></textarea><label>Your code</label><textarea id="code" rows="8"></textarea><button id="check">Check</button> <button id="close">Close</button><pre id="feedback"></pre></div></div><script>let maze=null, checkpoints=[], player={r:0,c:0};
const canvas=document.getElementById('maze'),ctx=canvas.getContext('2d');
function buildMaze(rows,cols){const cells=Array.from({length:rows},()=>Array.from({length:cols},()=>({v:false,w:[true,true,true,true]})));const dirs=[[-1,0,0,2],[0,1,1,3],[1,0,2,0],[0,-1,3,1]],stack=[[0,0]];cells[0][0].v=true;while(stack.length){const [r,c]=stack[stack.length-1],o=[];for(const [dr,dc,wi,oi] of dirs){const nr=r+dr,nc=c+dc;if(nr>=0&&nr<rows&&nc>=0&&nc<cols&&!cells[nr][nc].v)o.push([nr,nc,wi,oi])}if(!o.length){stack.pop();continue}const [nr,nc,wi,oi]=o[Math.floor(Math.random()*o.length)];cells[r][c].w[wi]=false;cells[nr][nc].w[oi]=false;cells[nr][nc].v=true;stack.push([nr,nc])}return{rows,cols,cells}}
function geom(){if(!maze)return null;const w=canvas.clientWidth,h=canvas.clientHeight,p=18,s=Math.min((w-p*2)/maze.cols,(h-p*2)/maze.rows);return{s,ox:(w-s*maze.cols)/2,oy:(h-s*maze.rows)/2}}
function resize(){canvas.width=Math.max(1,canvas.clientWidth*devicePixelRatio);canvas.height=Math.max(1,canvas.clientHeight*devicePixelRatio);ctx.setTransform(devicePixelRatio,0,0,devicePixelRatio,0,0);draw()}window.addEventListener('resize',resize);
function draw(){ctx.clearRect(0,0,canvas.clientWidth,canvas.clientHeight);if(!maze)return;const g=geom();ctx.strokeStyle='#666';ctx.lineWidth=1.5;ctx.beginPath();for(let r=0;r<maze.rows;r++)for(let c=0;c<maze.cols;c++){const x=g.ox+c*g.s,y=g.oy+r*g.s,w=maze.cells[r][c].w;if(w[0]){ctx.moveTo(x,y);ctx.lineTo(x+g.s,y)}if(w[1]){ctx.moveTo(x+g.s,y);ctx.lineTo(x+g.s,y+g.s)}if(w[2]){ctx.moveTo(x,y+g.s);ctx.lineTo(x+g.s,y+g.s)}if(w[3]){ctx.moveTo(x,y);ctx.lineTo(x,y+g.s)}}ctx.stroke();if(typeof drawCheckpoints==='function')drawCheckpoints();if(typeof placePlayer==='function')placePlayer()}
const tb=document.getElementById('tasks');function tasks(){return tb.value.split(/\r?\n/).map(x=>x.trim()).filter(Boolean)}function validTasks(ts){return ts.length>0&&ts.every(x=>/^Using\s+\S+/i.test(x))}function placeCheckpoints(n){const used=new Set(['0,0']),o=[];while(o.length<n){const r=Math.floor(Math.random()*maze.rows),c=Math.floor(Math.random()*maze.cols),k=r+','+c;if(!used.has(k)){used.add(k);o.push({r,c,num:o.length+1})}}return o}function drawCheckpoints(){if(!maze)return;const g=geom();checkpoints.forEach((cp,i)=>{const x=g.ox+(cp.c+.5)*g.s,y=g.oy+(cp.r+.5)*g.s;ctx.beginPath();ctx.arc(x,y,g.s*.24,0,Math.PI*2);ctx.fillStyle='#5b4619';ctx.fill();ctx.fillStyle='#fff';ctx.textAlign='center';ctx.textBaseline='middle';ctx.fillText(cp.num,x,y)})}function placePlayer(){if(!maze)return;const g=geom(),p=document.getElementById('player'),s=g.s*.38;p.style.display='block';p.style.width=s+'px';p.style.height=s+'px';p.style.left=(g.ox+(player.c+.5)*g.s-s/2)+'px';p.style.top=(g.oy+(player.r+.5)*g.s-s/2)+'px'}function canMove(dr,dc){if(!maze)return false;const nr=player.r+dr,nc=player.c+dc;if(nr<0||nr>=maze.rows||nc<0||nc>=maze.cols)return false;const w=maze.cells[player.r][player.c].w;if(dr===-1&&w[0])return false;if(dc===1&&w[1])return false;if(dr===1&&w[2])return false;if(dc===-1&&w[3])return false;return true}function move(dr,dc){if(canMove(dr,dc)){player.r+=dr;player.c+=dc;placePlayer();if(typeof checkCheckpoint==='function')checkCheckpoint()}}window.addEventListener('keydown',e=>{if(e.key==='ArrowUp')move(-1,0);if(e.key==='ArrowRight')move(0,1);if(e.key==='ArrowDown')move(1,0);if(e.key==='ArrowLeft')move(0,-1)});let activeCheckpoint=0,done=[];function drawCheckpoints(){if(!maze)return;const g=geom();checkpoints.forEach((cp,i)=>{const x=g.ox+(cp.c+.5)*g.s,y=g.oy+(cp.r+.5)*g.s;ctx.beginPath();ctx.arc(x,y,g.s*.24,0,Math.PI*2);ctx.fillStyle=done[i]?'#244c2b':i===activeCheckpoint?'#785b18':'#242424';ctx.fill();ctx.fillStyle=done[i]?'#8cff9a':i===activeCheckpoint?'#fff1b8':'#777';ctx.textAlign='center';ctx.textBaseline='middle';ctx.fillText(cp.num,x,y)})}let modalOpen=false,referenceKey='';async function api(path,p){const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(p)});const j=await r.json();if(!r.ok)throw new Error(j.error||'Request failed');return j}function checkCheckpoint(){const cp=checkpoints[activeCheckpoint];if(cp&&player.r===cp.r&&player.c===cp.c)openCheckpoint(activeCheckpoint)}async function openCheckpoint(i){modalOpen=true;document.getElementById('modalShade').style.display='flex';document.getElementById('cpTitle').textContent='Checkpoint '+(i+1);const task=tasks()[i]||'';document.getElementById('taskText').textContent=task;document.getElementById('reference').value='Generating...';try{const r=await api('/prepare_task',{task});document.getElementById('reference').value=r.reference_code;referenceKey=r.reference_key}catch(e){document.getElementById('reference').value=e.message}}document.getElementById('close').onclick=()=>{document.getElementById('modalShade').style.display='none';modalOpen=false};document.getElementById('generate').onclick=()=>{const ts=tasks();if(!validTasks(ts)){document.getElementById('msg').textContent='Every task must start with Using ...';return}document.getElementById('msg').textContent='';maze=buildMaze(12,18);checkpoints=placeCheckpoints(ts.length);player={r:0,c:0};activeCheckpoint=0;done=Array(ts.length).fill(false);resize()};resize();document.getElementById('check').onclick=async()=>{const r=await api('/check_task',{reference_key:referenceKey,code:document.getElementById('code').value});document.getElementById('feedback').textContent=r.message};</script></body></html>"""

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def send(self, status, body, mime="text/html; charset=utf-8"):
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)
    def do_GET(self):
        if self.path == "/": return self.send(200, HTML.replace("__TOKEN__", TOKEN))
        self.send(404, "Not found", "text/plain; charset=utf-8")
    def do_POST(self):
        return self.handle_post() if hasattr(self, "handle_post") else self.send(404, "Not found")

if __name__ == "__main__":
    http.server.ThreadingHTTPServer.allow_reuse_address = True
    with http.server.ThreadingHTTPServer((HOST, PORT), Handler) as s:
        print(f"Codify Maze: http://{HOST}:{PORT}")
        threading.Timer(0.4, lambda: webbrowser.open(f"http://{HOST}:{PORT}")).start()
        try: s.serve_forever()
        except KeyboardInterrupt: print("\nStopped.")
