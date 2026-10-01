import http.server
import json
import os
import secrets
import threading
import webbrowser

HOST, PORT = "127.0.0.1", int(os.environ.get("MAZE_PORT", "8000"))
TOKEN = secrets.token_urlsafe(24)
HTML = r"""<!doctype html><html><head><meta charset="utf-8"><title>Codify Maze</title><style>*{box-sizing:border-box}body{margin:0;background:#090909;color:#eee;font-family:Arial}#app{display:grid;grid-template-columns:330px 1fr;height:100vh}#left{padding:16px;border-right:1px solid #333;overflow:auto}#right{position:relative;min-width:0}textarea,input{width:100%;background:#111;color:#fff;border:1px solid #444;border-radius:8px;padding:10px;margin:6px 0 12px}button{background:#191919;color:#fff;border:1px solid #555;border-radius:8px;padding:9px 12px;cursor:pointer}canvas{width:100%;height:100%;display:block;background:#050505}#player{position:absolute;border-radius:50%;background:#b25cff;border:2px solid #f2d6ff;pointer-events:none}#modalShade{position:fixed;inset:0;background:#000b;display:none;align-items:center;justify-content:center;padding:20px}#modal{width:min(720px,92vw);background:#111;border:1px solid #555;border-radius:12px;padding:16px}.good{color:#8cff9a}.bad{color:#ff7b7b}</style></head><body><div id="app"><section id="left"><h2>Codify Maze</h2><p>Random maze prototype.</p><button id="generate">Generate Maze</button></section><section id="right"><canvas id="maze"></canvas><div id="player"></div></section></div><script>let maze=null, checkpoints=[], player={r:0,c:0};
const canvas=document.getElementById('maze'),ctx=canvas.getContext('2d');
function buildMaze(rows,cols){const cells=Array.from({length:rows},()=>Array.from({length:cols},()=>({v:false,w:[true,true,true,true]})));const dirs=[[-1,0,0,2],[0,1,1,3],[1,0,2,0],[0,-1,3,1]],stack=[[0,0]];cells[0][0].v=true;while(stack.length){const [r,c]=stack[stack.length-1],o=[];for(const [dr,dc,wi,oi] of dirs){const nr=r+dr,nc=c+dc;if(nr>=0&&nr<rows&&nc>=0&&nc<cols&&!cells[nr][nc].v)o.push([nr,nc,wi,oi])}if(!o.length){stack.pop();continue}const [nr,nc,wi,oi]=o[Math.floor(Math.random()*o.length)];cells[r][c].w[wi]=false;cells[nr][nc].w[oi]=false;cells[nr][nc].v=true;stack.push([nr,nc])}return{rows,cols,cells}}
function geom(){if(!maze)return null;const w=canvas.clientWidth,h=canvas.clientHeight,p=18,s=Math.min((w-p*2)/maze.cols,(h-p*2)/maze.rows);return{s,ox:(w-s*maze.cols)/2,oy:(h-s*maze.rows)/2}}
function resize(){canvas.width=Math.max(1,canvas.clientWidth*devicePixelRatio);canvas.height=Math.max(1,canvas.clientHeight*devicePixelRatio);ctx.setTransform(devicePixelRatio,0,0,devicePixelRatio,0,0);draw()}window.addEventListener('resize',resize);
function draw(){ctx.clearRect(0,0,canvas.clientWidth,canvas.clientHeight);if(!maze)return;const g=geom();ctx.strokeStyle='#666';ctx.lineWidth=1.5;ctx.beginPath();for(let r=0;r<maze.rows;r++)for(let c=0;c<maze.cols;c++){const x=g.ox+c*g.s,y=g.oy+r*g.s,w=maze.cells[r][c].w;if(w[0]){ctx.moveTo(x,y);ctx.lineTo(x+g.s,y)}if(w[1]){ctx.moveTo(x+g.s,y);ctx.lineTo(x+g.s,y+g.s)}if(w[2]){ctx.moveTo(x,y+g.s);ctx.lineTo(x+g.s,y+g.s)}if(w[3]){ctx.moveTo(x,y);ctx.lineTo(x,y+g.s)}}ctx.stroke();if(typeof drawCheckpoints==='function')drawCheckpoints();if(typeof placePlayer==='function')placePlayer()}
function drawCheckpoints(){} function placePlayer(){document.getElementById('player').style.display='none'} document.getElementById('generate').onclick=()=>{maze=buildMaze(12,18);resize()};resize();</script></body></html>"""

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
