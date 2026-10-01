"""Project Maze — Qwen canonical-code mystery (Python 3.10+).



Flow:

1. Any checkpoint title is accepted as written.

2. Qwen generates one canonical Python answer from that title.

3. The UI shows the generated reference code (for now).

4. The user writes Python code.

5. Python compares the answer to the canonical code character-for-character.

6. Whitespace, blank lines, names, values, punctuation, and every other character must match exactly.

7. On a miss, local Python gives simple text-difference feedback. Qwen is never called during Check.



Maze, timer, movement and checkpoints are retained.

"""



import difflib

import hashlib

import http.server

import json

import os

import secrets

import threading

import urllib.request

import webbrowser



HOST, PORT = '127.0.0.1', int(os.environ.get('MAZE_PORT', '8000'))

TOKEN = secrets.token_urlsafe(32)

LOCK = threading.RLock()

QWEN_LOCK = threading.Lock()

REFERENCE_CODE = {}

RECEIPTS = {}

ATTEMPTS = {}

MAX_BYTES = 2_000_000





def dumps(value):

    return json.dumps(value, ensure_ascii=False, allow_nan=False)





def strict_json(text):

    def pairs(items):

        result = {}

        for key, value in items:

            if key in result:

                raise ValueError('Duplicate JSON key: ' + key)

            result[key] = value

        return result

    return json.loads(text, object_pairs_hook=pairs)





def task_title(value):

    if isinstance(value, dict):

        tool = str(value.get('tool', '')).strip()

        objective = str(value.get('objective', '')).strip()

        value = ('Using ' + tool + ', ' + objective).strip() if tool or objective else ''

    title = str(value or '').strip()

    if not title:

        raise ValueError('Enter a checkpoint title')

    if len(title) > 5000:

        raise ValueError('Checkpoint title is too long')

    return title





def reference_key(title):

    return hashlib.sha256(title.encode('utf-8')).hexdigest()





def qwen_reference(title):

    prompt = r"""

Turn the checkpoint TITLE into one canonical Python answer.



Rules:

\- Output one canonical Python answer that fulfills the title as written.

\- The title is always accepted. Never ask for clarification.

\- If the title leaves details unspecified, choose ordinary minimal defaults yourself.

\- Add only setup strictly necessary for the requested program.

\- Do NOT add optional delays, demonstrations, cleanup, comments, helper functions, extra output, or extra behavior unless the title requires them.

\- Keep naming and formatting simple and conventional because this exact source becomes the answer key.

\- Do not explain anything.

\- Do not use markdown fences.

\- Return JSON only in exactly this shape: {"code":"<python source>"}

""".strip()

    body = {

        'model': os.environ.get('MAZE_SEMANTIC_MODEL', 'qwen3:8b'),

        'stream': False,

        'think': False,

        'format': 'json',

        'keep_alive': -1,

        'options': {

            'temperature': 0,

            'num_ctx': 4096,

            'num_predict': 500,

        },

        'messages': [

            {'role': 'system', 'content': prompt},

            {'role': 'user', 'content': title},

        ],

    }

    url = os.environ.get('MAZE_OLLAMA_URL', 'http://127.0.0.1:11434').rstrip('/')

    request = urllib.request.Request(

        url + '/api/chat',

        data=dumps(body).encode('utf-8'),

        headers={'Content-Type': 'application/json'},

    )

    try:

        with QWEN_LOCK:

            with urllib.request.urlopen(request, timeout=90) as response:

                raw = response.read(MAX_BYTES + 1)

        if len(raw) > MAX_BYTES:

            raise ValueError('Qwen response was too large')

        envelope = strict_json(raw.decode('utf-8'))

        result = strict_json(envelope['message']['content'])

        code = result.get('code') if isinstance(result, dict) else None

        if not isinstance(code, str) or not code.strip():

            raise ValueError('Qwen did not return reference code')

        compile(code, '<reference>', 'exec')

        return code.strip()

    except Exception as exc:

        raise ValueError(

            'Could not create reference code. Check that Ollama and the configured model are running. '

            + str(exc)

        ) from exc





def prepare_task(payload):

    title = task_title(payload.get('task'))

    key = reference_key(title)

    with LOCK:

        if key in REFERENCE_CODE and REFERENCE_CODE[key]['title'] == title:

            return {'status': 'ready', 'reference_key': key, 'reference_code': REFERENCE_CODE[key]['code'], 'message': 'Reference code ready'}

    code = qwen_reference(title)

    with LOCK:

        REFERENCE_CODE[key] = {'title': title, 'code': code}

    return {'status': 'ready', 'reference_key': key, 'reference_code': code, 'message': 'Reference code ready'}





def exact_difference(expected, actual, attempt):

    """Text-only feedback. No semantic interpretation: exact source is the answer key."""

    if expected == actual:

        return ''



    exp_lines = expected.splitlines(keepends=True)

    act_lines = actual.splitlines(keepends=True)

    matcher = difflib.SequenceMatcher(a=expected, b=actual, autojunk=False)

    op = next((x for x in matcher.get_opcodes() if x[0] != 'equal'), None)

    if op is None:

        return 'The source text differs.'



    tag, i1, i2, j1, j2 = op

    before = expected[:i1]

    line = before.count('\n') + 1

    col = len(before.rsplit('\n', 1)[-1]) + 1



    expected_piece = expected[i1:i2]

    actual_piece = actual[j1:j2]



    def shown(text, limit=120):

        if text == '':

            return '<nothing>'

        text = text.replace(' ', '·').replace('\t', '→').replace('\r', '\\\r').replace('\n', '↵\n')

        return text if len(text) <= limit else text[:limit] + '…'



    if tag == 'insert':

        kind = 'Extra text'

        detail = 'Your code has extra text starting here: ' + shown(actual_piece)

    elif tag == 'delete':

        kind = 'Missing text'

        detail = 'Your code is missing: ' + shown(expected_piece)

    else:

        kind = 'Different text'

        detail = 'Expected: ' + shown(expected_piece) + '\nFound:    ' + shown(actual_piece)



    # Progressive mystery feedback: later attempts expose a little more context,

    # but it is always purely textual and never semantic.

    message = f'{kind} at line {line}, column {col}.\n{detail}'

    if attempt >= 2:

        exp_line = exp_lines[line - 1].rstrip('\r\n') if line - 1 < len(exp_lines) else ''

        act_line = act_lines[line - 1].rstrip('\r\n') if line - 1 < len(act_lines) else ''

        message += '\n\nExpected line: ' + shown(exp_line, 220)

        message += '\nYour line:     ' + shown(act_line, 220)

    if attempt >= 3:

        message += '\n\nRemember: spaces are shown as · and line endings as ↵.'

    return message





def check_task(payload):

    title = task_title(payload.get('task'))

    code = payload.get('code')

    if not isinstance(code, str) or not code or len(code) > 100_000:

        raise ValueError('Enter Python code to check')



    key = payload.get('reference_key') or reference_key(title)

    with LOCK:

        entry = REFERENCE_CODE.get(key)

    if not entry or entry['title'] != title:

        raise ValueError('Reference code is not ready for this title yet.')



    expected = entry['code']

    attempt_key = key

    with LOCK:

        ATTEMPTS[attempt_key] = ATTEMPTS.get(attempt_key, 0) + 1

        attempt = ATTEMPTS[attempt_key]



    verified = code == expected

    if verified:

        message = 'MET — exact match.'

    else:

        message = 'NOT MET\n\n' + exact_difference(expected, code, attempt)



    response = {

        'status': 'met' if verified else 'not_met',

        'verified': verified,

        'verdict': 'MET' if verified else 'NOT MET',

        'message': message,

        'receipt': None,

        'attempt': attempt,

    }

    if verified:

        receipt = secrets.token_urlsafe(32)

        with LOCK:

            RECEIPTS[receipt] = {'title': title, 'code': code, 'reference_key': key}

        response['receipt'] = receipt

    return response



def complete_checkpoint(payload):

    receipt_value = payload.get('receipt')

    code = payload.get('code')

    title = task_title(payload.get('task'))

    key = payload.get('reference_key') or reference_key(title)

    with LOCK:

        receipt = RECEIPTS.get(receipt_value)

        if not receipt or receipt['code'] != code or receipt['title'] != title or receipt['reference_key'] != key:

            raise ValueError('Code or task changed. Check again before completing this checkpoint.')

        del RECEIPTS[receipt_value]

    return {'completed': True}





class Handler(http.server.BaseHTTPRequestHandler):

    def log_message(self, *args):

        pass



    def respond(self, status, data, mime='application/json; charset=utf-8'):

        body = data.encode() if isinstance(data, str) else dumps(data).encode()

        self.send_response(status)

        self.send_header('Content-Type', mime)

        self.send_header('Content-Length', str(len(body)))

        self.send_header('Cache-Control', 'no-store')

        self.send_header('X-Content-Type-Options', 'nosniff')

        self.send_header('Content-Security-Policy', "frame-ancestors 'none'")

        self.end_headers()

        self.wfile.write(body)



    def allowed_host(self):

        return self.headers.get('Host') in {f'127.0.0.1:{PORT}', f'localhost:{PORT}'}



    def do_GET(self):

        if not self.allowed_host():

            return self.respond(403, {'error': 'Invalid host'})

        if self.path == '/':

            return self.respond(200, HTML.replace('__API_TOKEN__', TOKEN), 'text/html; charset=utf-8')

        self.respond(404, {'error': 'Not found'})



    def do_POST(self):

        if not self.allowed_host() or self.headers.get('X-Maze-Token') != TOKEN:

            return self.respond(403, {'error': 'Invalid session'})

        origin = self.headers.get('Origin')

        if origin and origin not in {f'http://127.0.0.1:{PORT}', f'http://localhost:{PORT}'}:

            return self.respond(403, {'error': 'Invalid origin'})

        try:

            size = int(self.headers.get('Content-Length', '0'))

            if not 0 < size <= MAX_BYTES:

                raise ValueError('Invalid request size')

            payload = strict_json(self.rfile.read(size).decode('utf-8'))

            if not isinstance(payload, dict):

                raise ValueError('Expected an object')



            if self.path == '/prepare_task':

                result = prepare_task(payload)

            elif self.path in {'/check_task', '/describe_code', '/verify_task'}:

                result = check_task(payload)

            elif self.path == '/complete_checkpoint':

                result = complete_checkpoint(payload)

            else:

                return self.respond(404, {'error': 'Not found'})



            self.respond(200, result)

        except (ValueError, TypeError, KeyError, RecursionError) as exc:

            self.respond(400, {'error': str(exc)})

        except Exception as exc:

            self.respond(500, {'error': 'Verification could not finish: ' + str(exc)})





def main():

    http.server.ThreadingHTTPServer.allow_reuse_address = True

    with http.server.ThreadingHTTPServer((HOST, PORT), Handler) as server:

        print(f'Project Maze: http://{HOST}:{PORT} — exact-code mystery. Ctrl+C to stop.')

        threading.Timer(0.5, lambda: webbrowser.open(f'http://{HOST}:{PORT}')).start()

        try:

            server.serve_forever()

        except KeyboardInterrupt:

            print('\nStopped.')





# UI is adapted from the supplied maze; movement, timer and layout are retained.



HTML = r'''<!doctype html>

<html lang="en">

<head>

<meta charset="utf-8">

<meta name="viewport" content="width=device-width, initial-scale=1">

<title>Project Maze</title>

<style>

*{box-sizing:border-box} body{margin:0;background:#080808;color:#f5f5f5;font-family:Arial,sans-serif;overflow:hidden}

#app{display:grid;grid-template-rows:50% 50%;height:100vh;overflow:hidden}

#left{grid-row:2;overflow:auto;padding:18px;border-right:1px solid #2d2d2d;display:flex;flex-direction:column;gap:12px;min-width:0}

#brand{font-size:24px;font-weight:800;letter-spacing:.4px} #sub{color:#929292;font-size:13px;line-height:1.45}

label{font-size:12px;color:#b8b8b8;font-weight:700;letter-spacing:.5px;text-transform:uppercase}

input,textarea{width:100%;background:#101010;color:white;border:1px solid #363636;border-radius:10px;outline:none;padding:12px;font:14px Consolas,monospace}

input:focus,textarea:focus{border-color:#777}

#tasks{flex:1;min-height:180px;resize:none;line-height:1.55}

.row{display:flex;gap:9px;align-items:center}.btn{border:1px solid #4c4c4c;background:#151515;color:white;border-radius:9px;padding:10px 14px;cursor:pointer;font-weight:700}.btn:hover{border-color:#aaa}.btn:disabled{opacity:.35;cursor:default}

#counter{margin-left:auto;color:#aaa;font-size:13px} #modelStatus{font-size:12px;color:#999;min-height:18px}

#taskList{max-height:29vh;overflow:auto;border:1px solid #272727;border-radius:10px;background:#0d0d0d;padding:8px}

.task{padding:8px 9px;border-radius:7px;color:#7f7f7f;font-size:13px;display:flex;gap:8px}.task.active{background:#24201a;color:#ffd98b}.task.done{color:#8cff9a}.num{min-width:20px;font-weight:800}

#right{grid-row:1;display:flex;flex-direction:column;min-width:0;overflow:hidden} #topbar{height:58px;padding:0 16px;display:flex;align-items:center;border-bottom:1px solid #242424;gap:12px}

#status{font-size:13px;color:#aaa} #progress{margin-left:auto;font-size:13px;color:#d3d3d3}

#mazeWrap{position:relative;flex:1;min-height:0;overflow:hidden;background:#050505} canvas{display:block;width:100%;height:100%}#playerDot{position:absolute;left:0;top:0;border-radius:50%;background:#b25cff;border:2px solid #f2d6ff;pointer-events:none;will-change:transform;display:none}

#help{position:absolute;left:12px;bottom:10px;color:#666;font-size:11px;background:#090909cc;padding:6px 8px;border-radius:7px}

#modalShade{position:fixed;inset:0;background:#000b;display:none;align-items:center;justify-content:center;z-index:20;padding:20px}

#modal{overflow:auto;width:min(760px,92vw);max-height:88vh;display:flex;flex-direction:column;background:#101010;border:1px solid #555;border-radius:14px;padding:18px;gap:12px;box-shadow:0 25px 80px #000}

#checkpointTitle{font-size:13px;color:#aaa} #currentTask{font-size:20px;font-weight:800;line-height:1.35}

#feedback{min-height:42px;white-space:pre-wrap;font-size:13px;line-height:1.4;color:#aaa}

.good{color:#8cff9a!important}.partial{color:#ffd36f!important}.bad{color:#ff7b7b!important}

#modalButtons{display:flex;gap:8px;justify-content:flex-end}



</style>

</head>

<body>

<div id="app">

  <section id="left">

    <div><div id="brand">Project Maze</div><div id="sub">Write a specific task, enter your Python code, and click Check.</div></div>

    <label>Tasks — each task must start with *Using ...</label>

    <div style="color:#888;font-size:11px;line-height:1.4">Format: <b>*Using Library, task</b>. If no library is needed, use Python, e.g. <b>*Using math, read a nonnegative integer from stdin and print its integer square root using math.isqrt.</b>.</div>

    <textarea id="tasks" spellcheck="false" placeholder="*Using math, read one nonnegative integer from stdin and print its integer square root using math.isqrt."></textarea>

    <label>Timer goal — minutes</label>

    <input id="timerGoal" type="number" min="1" step="1" placeholder="e.g. 30">

    <div class="row"><button id="generate" class="btn">Generate Project Maze</button><button id="reset" class="btn">Reset</button><span id="counter">0 tasks</span></div>

    <div id="modelStatus">Automatic task and code checks · Ollama and Docker required</div>

    <div id="taskList"></div>

  </section>

  <section id="right">

    <div id="topbar"><span id="status">Enter tasks, then generate the maze.</span><span id="timer">00:00</span><span id="progress">0 / 0 complete</span></div>

    <div id="mazeWrap"><canvas id="maze"></canvas><div id="playerDot"></div><div id="help">Move: Arrow Keys · Reach checkpoints in numerical order</div></div>

  </section>

</div>



<div id="modalShade">

  <div id="modal">

    <div id="checkpointTitle"></div>

    <label for="currentTask">Task</label>

    <textarea id="currentTask" spellcheck="false" style="height:100px;resize:vertical"></textarea>

    <div id="projectContext" style="color:#aaa;font-size:12px">Qwen generates the canonical answer below. Check compares your code against it locally.</div>

    <div id="taskStatus" style="font-size:13px;color:#ffd36f;white-space:pre-wrap" aria-live="polite"></div>

    <label>Qwen generated answer key</label>

    <textarea id="referenceCode" spellcheck="false" readonly style="height:190px;resize:vertical"></textarea>

    <label>Your code</label>

    <textarea id="codeBox" spellcheck="false" placeholder="Paste/write code for this checkpoint..." style="height:190px;resize:vertical"></textarea>

    <div class="row" style="justify-content:flex-end">

      <button id="describeCode" class="btn">Check</button>

    </div>

    <div id="descriptionWrap" style="display:none">

      <label>Mystery feedback</label>

      <textarea id="codeDescription" spellcheck="false" readonly style="height:240px;resize:vertical;margin-top:6px"></textarea>

    </div>

        <div id="feedback"></div>

    <div id="modalButtons"><button id="completeCheckpoint" class="btn">Mark complete</button><button id="closeModal" class="btn">Close</button></div>

  </div>

</div>



<script>

const $=id=>document.getElementById(id);

const canvas=$('maze'),ctx=canvas.getContext('2d'),playerDot=$('playerDot');

const tasksBox=$('tasks'),taskList=$('taskList'),statusEl=$('status'),progressEl=$('progress'),timerEl=$('timer'),timerGoalInput=$('timerGoal');

const modalShade=$('modalShade'),feedback=$('feedback'),describeCodeBtn=$('describeCode'),codeBox=$('codeBox'),referenceCode=$('referenceCode'),codeDescription=$('codeDescription'),descriptionWrap=$('descriptionWrap');

let busy=false;

let tasks=[],done=[],savedCodes=[],savedDescriptions=[],savedResults=[],savedReferenceKeys=[],savedReferenceCodes=[],referenceLoading=[],maze=null,player={r:0,c:0,vr:0,vc:0},checkpoints=[],activeCheckpoint=0,modalCheckpoint=0,modalOpen=false,moving=false;

let timerStarted=false,timerRunning=false,timerStartAt=0,timerElapsedMs=0,timerInterval=null,timerGoalMs=0;

let heldKeys=new Set();

let moveKeyOrder=[];

const TEST_PASS_WALLS=false;

const MOVE_DURATION=90;



function formatTimer(ms){

  const total=Math.floor(ms/1000);

  const minutes=Math.floor(total/60);

  const seconds=total%60;

  return String(minutes).padStart(2,'0')+':'+String(seconds).padStart(2,'0');

}



function renderTimer(){

  const ms=timerElapsedMs+(timerRunning?(Date.now()-timerStartAt):0);

  timerEl.textContent=formatTimer(ms)+(timerGoalMs?' / '+formatTimer(timerGoalMs):'');

}



function startTimer(){

  if(timerStarted)return;

  timerStarted=true;

  timerRunning=true;

  timerStartAt=Date.now();

  renderTimer();

  timerInterval=setInterval(renderTimer,250);

}



function pauseTimer(){

  if(!timerRunning)return;

  timerElapsedMs+=Date.now()-timerStartAt;

  timerRunning=false;

  renderTimer();

}



function resumeTimer(){

  if(!timerStarted||timerRunning)return;

  timerRunning=true;

  timerStartAt=Date.now();

  renderTimer();

}



function resetTimer(){

  timerStarted=false;

  timerRunning=false;

  timerStartAt=0;

  timerElapsedMs=0;

  timerGoalMs=0;

  if(timerInterval){clearInterval(timerInterval);timerInterval=null;}

  timerEl.textContent='00:00';

}



function parseTasks(){return tasksBox.value.split(/\r?\n/).filter(x=>/^\\*\s*\S/.test(x)).map(x=>x.slice(1).trim())}



function checkpointTitle(task){return String(task||'').trim()}



function updateCounter(){$('counter').textContent=parseTasks().length+' tasks'}

tasksBox.addEventListener('input',updateCounter);updateCounter();



function buildMaze(rows,cols){

  const cells=Array.from({length:rows},()=>Array.from({length:cols},()=>({v:false,w:[true,true,true,true]})));

  const stack=[[0,0]];cells[0][0].v=true;const dirs=[[-1,0,0,2],[0,1,1,3],[1,0,2,0],[0,-1,3,1]];

  while(stack.length){const [r,c]=stack[stack.length-1];const opts=[];for(const [dr,dc,wi,oi] of dirs){const nr=r+dr,nc=c+dc;if(nr>=0&&nr<rows&&nc>=0&&nc<cols&&!cells[nr][nc].v)opts.push([nr,nc,wi,oi])}

    if(!opts.length){stack.pop();continue}const [nr,nc,wi,oi]=opts[Math.floor(Math.random()*opts.length)];cells[r][c].w[wi]=false;cells[nr][nc].w[oi]=false;cells[nr][nc].v=true;stack.push([nr,nc])}

  return {rows,cols,cells};

}



function distancesFromStart(){const dist=Array.from({length:maze.rows},()=>Array(maze.cols).fill(-1)),q=[[0,0]];dist[0][0]=0;for(let i=0;i<q.length;i++){const [r,c]=q[i],w=maze.cells[r][c].w;const ns=[];if(!w[0])ns.push([r-1,c]);if(!w[1])ns.push([r,c+1]);if(!w[2])ns.push([r+1,c]);if(!w[3])ns.push([r,c-1]);for(const [nr,nc] of ns)if(dist[nr][nc]<0){dist[nr][nc]=dist[r][c]+1;q.push([nr,nc])}}return dist}

function placeCheckpoints(n){

  const dist=distancesFromStart(),pool=[];for(let r=0;r<maze.rows;r++)for(let c=0;c<maze.cols;c++)if(!(r===0&&c===0))pool.push({r,c,d:dist[r][c]});

  pool.sort((a,b)=>b.d-a.d);const chosen=[];let candidates=pool.slice(0,Math.max(n*5,Math.floor(pool.length*.65)));

  while(chosen.length<n&&candidates.length){const i=Math.floor(Math.random()*candidates.length);chosen.push(candidates.splice(i,1)[0])}

  while(chosen.length<n&&pool.length){const p=pool.shift();if(!chosen.some(x=>x.r===p.r&&x.c===p.c))chosen.push(p)}

  return chosen.map((p,i)=>({r:p.r,c:p.c,num:i+1}));

}



function renderTaskList(){taskList.innerHTML='';tasks.forEach((t,i)=>{const d=document.createElement('div');d.className='task '+(done[i]?'done':i===activeCheckpoint?'active':'');d.innerHTML='<span class="num">'+(i+1)+'.</span><span>'+escapeHtml(t)+'</span>';taskList.appendChild(d)})}

function escapeHtml(s){return s.replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]))}

function updateProgress(){progressEl.textContent=done.filter(Boolean).length+' / '+tasks.length+' complete';renderTaskList();draw()}



function dpr(){return Math.min(devicePixelRatio||1,1.5)}

function resize(){const r=canvas.parentElement.getBoundingClientRect(),d=dpr();canvas.width=Math.max(1,Math.floor(r.width*d));canvas.height=Math.max(1,Math.floor(r.height*d));draw();positionPlayer()}window.addEventListener('resize',resize);

function geom(){if(!maze)return null;const d=dpr(),p=14*d,s=Math.min((canvas.width-p*2)/maze.cols,(canvas.height-p*2)/maze.rows),mw=s*maze.cols,mh=s*maze.rows;return{s,ox:(canvas.width-mw)/2,oy:(canvas.height-mh)/2,d}}

function center(r,c,g){return{x:g.ox+(c+.5)*g.s,y:g.oy+(r+.5)*g.s}}

function draw(){ctx.clearRect(0,0,canvas.width,canvas.height);if(!maze){playerDot.style.display='none';return}const g=geom();ctx.strokeStyle='#6b6b6b';ctx.lineWidth=Math.max(1.5,1.5*g.d);ctx.beginPath();for(let r=0;r<maze.rows;r++)for(let c=0;c<maze.cols;c++){const x=g.ox+c*g.s,y=g.oy+r*g.s,w=maze.cells[r][c].w;if(w[0]){ctx.moveTo(x,y);ctx.lineTo(x+g.s,y)}if(w[1]){ctx.moveTo(x+g.s,y);ctx.lineTo(x+g.s,y+g.s)}if(w[2]){ctx.moveTo(x,y+g.s);ctx.lineTo(x+g.s,y+g.s)}if(w[3]){ctx.moveTo(x,y);ctx.lineTo(x,y+g.s)}}ctx.stroke();checkpoints.forEach((cp,i)=>{const p=center(cp.r,cp.c,g);ctx.beginPath();ctx.arc(p.x,p.y,g.s*.27,0,Math.PI*2);ctx.fillStyle=done[i]?'#244c2b':i===activeCheckpoint?'#785b18':'#242424';ctx.fill();ctx.strokeStyle=done[i]?'#8cff9a':i===activeCheckpoint?'#ffd36f':'#555';ctx.stroke();ctx.fillStyle=done[i]?'#8cff9a':i===activeCheckpoint?'#fff1b8':'#777';ctx.font=\`${Math.max(11,g.s*.26)}px Arial\`;ctx.textAlign='center';ctx.textBaseline='middle';ctx.fillText(String(i+1),p.x,p.y)})}

function positionPlayer(){if(!maze){playerDot.style.display='none';return}const g=geom(),p=center(player.vr,player.vc,g),size=Math.max(8,g.s*.40)/g.d;playerDot.style.display='block';playerDot.style.width=size+'px';playerDot.style.height=size+'px';playerDot.style.transform=\`translate3d(${p.x/g.d-size/2}px,${p.y/g.d-size/2}px,0)\`}



function directionForKey(k){

  if(k==='arrowup')return[-1,0];

  if(k==='arrowright')return[0,1];

  if(k==='arrowdown')return[1,0];

  if(k==='arrowleft')return[0,-1];

  return null;

}



function canMove(dr,dc){

  if(!maze||modalOpen||moving)return false;

  const nr=player.r+dr,nc=player.c+dc;

  if(nr<0||nr>=maze.rows||nc<0||nc>=maze.cols)return false;

  if(TEST_PASS_WALLS)return true;

  const w=maze.cells[player.r][player.c].w;

  if(dr===-1&&w[0])return false;

  if(dc===1&&w[1])return false;

  if(dr===1&&w[2])return false;

  if(dc===-1&&w[3])return false;

  return true;

}





function move(dr,dc){

  if(!canMove(dr,dc))return;



  if(!timerStarted)startTimer();

  moving=true;



  const startR=player.vr;

  const startC=player.vc;

  const targetR=player.r+dr;

  const targetC=player.c+dc;

  const started=performance.now();



  function animate(now){

    const t=Math.min(1,(now-started)/MOVE_DURATION);

    const e=t;



    player.vr=startR+(targetR-startR)*e;

    player.vc=startC+(targetC-startC)*e;

    positionPlayer();



    if(t<1){

      requestAnimationFrame(animate);

      return;

    }



    player.vr=targetR;

    player.vc=targetC;

    player.r=targetR;

    player.c=targetC;

    positionPlayer();

    moving=false;

    checkCheckpoint();



    // Continue using the most recently pressed direction that is still held.

    if(!modalOpen){

      const key=[...moveKeyOrder].reverse().find(k=>heldKeys.has(k));

      if(key){

        const next=directionForKey(key);

        requestAnimationFrame(()=>move(...next));

      }

    }

  }



  requestAnimationFrame(animate);

}



window.addEventListener('keydown',e=>{

  if(modalOpen||!maze||e.target.closest('input,textarea,[contenteditable]'))return;

  const k=e.key.toLowerCase();

  const d=directionForKey(k);

  if(!d)return;



  e.preventDefault();

  heldKeys.add(k);

  moveKeyOrder=moveKeyOrder.filter(x=>x!==k);

  moveKeyOrder.push(k);



  // Ignore browser key-repeat. Held movement is handled by our animation loop.

  if(!e.repeat&&!moving)move(...d);

});



window.addEventListener('keyup',e=>{

  const k=e.key.toLowerCase();

  heldKeys.delete(k);

  moveKeyOrder=moveKeyOrder.filter(x=>x!==k);

});



window.addEventListener('blur',()=>{

  heldKeys.clear();

  moveKeyOrder=[];

});



function checkCheckpoint(){for(let i=0;i<checkpoints.length;i++){const cp=checkpoints[i];if(player.r===cp.r&&player.c===cp.c&&(i===activeCheckpoint||done[i])){openCheckpoint(i);return}}}

function taskText(){return $('currentTask').value.trim().replace(/^\\*\s*/, '');}

function refreshButtons(){

  const i=modalCheckpoint,result=savedResults[i];

  describeCodeBtn.disabled=busy||!!done[i]||!codeBox.value.trim()||!savedReferenceKeys[i]||!!referenceLoading[i];

  $('completeCheckpoint').disabled=busy||!!done[i]||!result?.receipt||!result.verified||savedCodes[i]!==codeBox.value;

  codeBox.disabled=busy||!!done[i];$('currentTask').disabled=busy||!!done[i];

}

async function ensureReference(i){

  if(done[i]||savedReferenceKeys[i]||referenceLoading[i])return;

  const title=checkpointTitle(tasks[i]);

  if(!title)return;

  referenceLoading[i]=true;

  if(i===modalCheckpoint&&modalOpen){

    $('taskStatus').textContent='Creating reference code…';

    $('taskStatus').style.color='#ffd36f';

    refreshButtons();

  }

  try{

    const r=await api('/prepare_task',{task:title});

    if(tasks[i]!==title)return;

    savedReferenceKeys[i]=r.reference_key;

    savedReferenceCodes[i]=r.reference_code||'';

    if(i===modalCheckpoint&&modalOpen){

      referenceCode.value=savedReferenceCodes[i];

      $('taskStatus').textContent='✓ Reference code ready';

      $('taskStatus').style.color='#8cff9a';

    }

  }catch(e){

    if(i===modalCheckpoint&&modalOpen){

      $('taskStatus').textContent='Reference code failed: '+e.message;

      $('taskStatus').style.color='#ff8585';

    }

  }finally{

    referenceLoading[i]=false;

    if(i===modalCheckpoint&&modalOpen)refreshButtons();

  }

}



function openCheckpoint(i=activeCheckpoint){

  heldKeys.clear();moveKeyOrder=[];modalCheckpoint=i;modalOpen=true;modalShade.style.display='flex';

  $('checkpointTitle').textContent='Checkpoint '+(i+1)+' of '+tasks.length;

  $('currentTask').value=tasks[i];codeBox.value=savedCodes[i]||'';referenceCode.value=savedReferenceCodes[i]||'';

  codeDescription.value=savedDescriptions[i]||'';descriptionWrap.style.display=savedDescriptions[i]?'block':'none';

  feedback.textContent=savedResults[i]?.message||'';

  if(done[i]){$('taskStatus').textContent='Task completed.';$('taskStatus').style.color='#8cff9a';}

  else if(savedReferenceKeys[i]){$('taskStatus').textContent='✓ Reference code ready';$('taskStatus').style.color='#8cff9a';}

  else{$('taskStatus').textContent='Creating reference code…';$('taskStatus').style.color='#ffd36f';}

  refreshButtons();ensureReference(i);

}

async function api(path,payload){

  const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-Maze-Token':'__API_TOKEN__'},body:JSON.stringify(payload)});

  const result=await response.json();if(!response.ok)throw new Error(result.error||'Request failed');return result;

}

$('currentTask').addEventListener('input',()=>{

  const i=modalCheckpoint;

  tasks[i]=taskText();tasksBox.value=tasks.map(t=>'*'+t).join('\n');updateCounter();renderTaskList();

  savedResults[i]=null;savedDescriptions[i]='';savedReferenceKeys[i]=null;savedReferenceCodes[i]='';referenceCode.value='';

  codeDescription.value='';descriptionWrap.style.display='none';feedback.textContent='';

  $('taskStatus').textContent='Reference code not ready';$('taskStatus').style.color='#ffd36f';refreshButtons();

});

$('currentTask').addEventListener('change',()=>ensureReference(modalCheckpoint));

$('closeModal').onclick=()=>{if(busy)return;savedCodes[modalCheckpoint]=codeBox.value;modalOpen=false;modalShade.style.display='none';};

codeBox.addEventListener('input',()=>{

  savedCodes[modalCheckpoint]=codeBox.value;savedResults[modalCheckpoint]=null;savedDescriptions[modalCheckpoint]='';

  codeDescription.value='';descriptionWrap.style.display='none';

  feedback.textContent='Code changed — click Check again.';feedback.className='';

  refreshButtons();

});

function setBusy(value){

  busy=value;

  for(const id of ['generate','reset','closeModal'])$(id).disabled=value;

  refreshButtons();

}

describeCodeBtn.onclick=async()=>{

  const i=modalCheckpoint,code=codeBox.value;

  if(!code.trim()||!savedReferenceKeys[i])return;

  savedResults[i]=null;setBusy(true);feedback.textContent='Comparing exact source…';

  try{

    const r=await api('/check_task',{code,task:checkpointTitle(tasks[i]),reference_key:savedReferenceKeys[i]});

    savedCodes[i]=code;savedResults[i]=r;

    const verdict=r.verdict||'NOT MET';

    savedDescriptions[i]=r.message||verdict;

    codeDescription.value=savedDescriptions[i];descriptionWrap.style.display='block';

    feedback.textContent=verdict;

    feedback.className=r.verified?'good':'bad';

  }catch(e){feedback.textContent='Cannot verify: '+e.message;feedback.className='bad';}

  finally{setBusy(false);}

};

$('completeCheckpoint').onclick=async()=>{

  const i=modalCheckpoint,r=savedResults[i];

  if(!r?.verified||!r.receipt||savedCodes[i]!==codeBox.value)return;

  setBusy(true);

  try{

    await api('/complete_checkpoint',{receipt:r.receipt,code:codeBox.value,task:checkpointTitle(tasks[i]),reference_key:savedReferenceKeys[i]});

    done[i]=true;activeCheckpoint=done.findIndex(x=>!x);if(activeCheckpoint<0)activeCheckpoint=tasks.length;

    updateProgress();statusEl.textContent=activeCheckpoint===tasks.length?'All checkpoints complete.':'Find checkpoint '+(activeCheckpoint+1)+'.';

    if(activeCheckpoint===tasks.length)pauseTimer();

    feedback.textContent='Met — checkpoint complete.';feedback.className='good';

  }catch(e){feedback.textContent=e.message;}

  finally{setBusy(false);}

};



$('generate').onclick=()=>{if(moving||busy)return;resetTimer();const goalMinutes=Number(timerGoalInput.value);if(!Number.isFinite(goalMinutes)||goalMinutes<=0){statusEl.textContent='Set a timer goal in minutes before generating the maze.';timerGoalInput.focus();return}timerGoalMs=goalMinutes*60*1000;renderTimer();heldKeys.clear();moveKeyOrder=[];tasks=parseTasks();if(!tasks.length){statusEl.textContent='Add at least one task beginning with *';return}if(tasks.length>200){statusEl.textContent='Use at most 200 checkpoints.';return}const rows=Math.max(9,Math.min(17,9+Math.floor(tasks.length/2))),cols=Math.max(13,Math.min(24,13+tasks.length));maze=buildMaze(rows,cols);player={r:0,c:0,vr:0,vc:0};done=Array(tasks.length).fill(false);savedCodes=Array(tasks.length).fill('');savedDescriptions=Array(tasks.length).fill('');savedResults=Array(tasks.length).fill(null);savedReferenceKeys=Array(tasks.length).fill(null);savedReferenceCodes=Array(tasks.length).fill('');referenceLoading=Array(tasks.length).fill(false);activeCheckpoint=0;modalCheckpoint=0;checkpoints=placeCheckpoints(tasks.length);statusEl.textContent='Maze generated. Find checkpoint 1.';updateProgress();resize()};

$('reset').onclick=()=>{if(moving||busy)return;resetTimer();modalOpen=false;modalShade.style.display='none';maze=null;tasks=[];done=[];savedCodes=[];savedDescriptions=[];savedResults=[];savedReferenceKeys=[];savedReferenceCodes=[];referenceLoading=[];checkpoints=[];activeCheckpoint=0;modalCheckpoint=0;player={r:0,c:0,vr:0,vc:0};heldKeys.clear();moveKeyOrder=[];statusEl.textContent='Enter tasks, then generate the maze.';progressEl.textContent='0 / 0 complete';taskList.innerHTML='';draw()};

tasksBox.value='*Using math, read one nonnegative integer from standard input and print its integer square root using math.isqrt, followed by a newline.';

updateCounter();

resize();

</script>

</body>

</html>'''



if __name__ == '__main__':

    main()
