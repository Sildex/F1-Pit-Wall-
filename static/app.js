// ─── State ────────────────────────────────────────────────────────────────
let bestLapMs=Infinity, bestS1Ms=Infinity, bestS2Ms=Infinity, bestS3Ms=Infinity;
let selectedLap=null, voiceEnabled=false, _audio=null;
let _audioCtx=null, _prevSessionType='';
const TYRE_C={Soft:'#ff2222',Medium:'#f5d300',Hard:'#cccccc',Inter:'#39b54a',Wet:'#0055ff'};

// ─── Voice ────────────────────────────────────────────────────────────────
function toggleVoice(){
  voiceEnabled=!voiceEnabled;
  const b=document.getElementById('voice-btn');
  b.textContent=voiceEnabled?'🔊':'🔈';
  b.className='btn-ghost'+(voiceEnabled?' on':'');
  if(voiceEnabled&&!localStorage.getItem('jeff_v1')){
    localStorage.setItem('jeff_v1','1');
    setTimeout(()=>speak('Jeff here. Ready when you are.'),400);
  }
}
function _makeDistCurve(amount){
  const n=256,c=new Float32Array(n);
  for(let i=0;i<n;i++){const x=i*2/n-1;c[i]=((Math.PI+amount)*x)/(Math.PI+amount*Math.abs(x));}
  return c;
}
async function speak(text){
  if(!voiceEnabled) return;
  if(_audioCtx&&_audioCtx.state==='suspended') await _audioCtx.resume();
  try{
    const r=await fetch('/api/speak',{method:'POST',
      headers:{'Content-Type':'application/json'},body:JSON.stringify({text})});
    if(!r.ok) return;
    const buf=await r.arrayBuffer();
    if(!_audioCtx) return;
    const decoded=await _audioCtx.decodeAudioData(buf);
    const src=_audioCtx.createBufferSource();
    src.buffer=decoded;
    const hp=_audioCtx.createBiquadFilter();hp.type='highpass';hp.frequency.value=300;
    const lp=_audioCtx.createBiquadFilter();lp.type='lowpass';lp.frequency.value=3400;
    const ws=_audioCtx.createWaveShaper();ws.curve=_makeDistCurve(15);
    const comp=_audioCtx.createDynamicsCompressor();
    comp.threshold.value=-20;comp.ratio.value=8;
    const gain=_audioCtx.createGain();gain.gain.value=1.2;
    src.connect(hp);hp.connect(lp);lp.connect(ws);ws.connect(comp);comp.connect(gain);
    gain.connect(_audioCtx.destination);
    src.start();
  }catch(e){}
}

// ─── Polling ──────────────────────────────────────────────────────────────
async function poll(){
  let d;
  try{ d=await fetch('/api/live').then(r=>r.json()); }catch(e){return;}
  window._lt=(d.live_telemetry||{}).tyre_temp||[0,0,0,0];
  try{updateHeader(d);}catch(e){console.error('updateHeader',e);}
  try{updateCar(d.status||{}, d.damage||{}, d.setup||{});}catch(e){console.error('updateCar',e);}
  try{updateInputs(d.live_telemetry||{});}catch(e){console.error('updateInputs',e);}
  try{updateSectorDeltas(d.laps||[]);}catch(e){console.error('updateSectorDeltas',e);}
  try{updateLaps(d.laps||[]);}catch(e){console.error('updateLaps',e);}
  try{updateSetup(d.setup||{});}catch(e){console.error('updateSetup',e);}
  try{drawTrack(d);}catch(e){console.error('drawTrack',e);}
  try{
    const forMini=selectedLap||(d.laps?.length?d.laps[d.laps.length-1]:null);
    drawMini(forMini?.mini_sectors||d.current_mini_sectors||[]);
  }catch(e){console.error('drawMini',e);}
}
async function pollTrig(){
  try{
    const d=await fetch('/api/trigger').then(r=>r.json());
    if(d.new&&d.lap_context){
      addMsg('Analysing...','system');
      await chatWithCtx(d.lap_context);
    }
  }catch(e){}
}

// ─── Voice input (hold LSB) ───────────────────────────────────────────────
let _lastVoiceStartTs='';
let _lastVoiceStopTs='';
let _lastAnalyzeTs='';
let _voiceRecog=null;
const _SR=window.SpeechRecognition||window.webkitSpeechRecognition;

async function pollVoiceTrig(){
  try{
    const d=await fetch('/api/voice_trigger').then(r=>r.json());
    if(d.start_ts && d.start_ts!==_lastVoiceStartTs){
      _lastVoiceStartTs=d.start_ts;
      startVoiceInput();
    }
    if(d.stop_ts && d.stop_ts!==_lastVoiceStopTs){
      _lastVoiceStopTs=d.stop_ts;
      stopVoiceInput();
    }
    if(d.analyze_ts && d.analyze_ts!==_lastAnalyzeTs){
      _lastAnalyzeTs=d.analyze_ts;
      analyzeLaps();
    }
  }catch(e){}
}
let _audioArmed=false;
async function armAudio(){
  if(_audioArmed) return;
  _audioCtx=new (window.AudioContext||window.webkitAudioContext)();
  const a=new Audio('/api/beep');
  try{ await a.play(); } catch(e){}
  _audioArmed=true;
  const b=document.getElementById('arm-btn');
  if(b){b.textContent='● ARMED';b.style.color='var(--grn)';b.style.borderColor='var(--grn)';}
}
async function playRadioBeep(){
  try{
    const r=await fetch('/api/beep');
    const url=URL.createObjectURL(await r.blob());
    const a=new Audio(url);
    a.onended=()=>URL.revokeObjectURL(url);
    await a.play();
  }catch(e){}
}

function startVoiceInput(){
  if(!_SR){addMsg('Speech recognition not supported (use Chrome/Edge).','system');return;}
  if(_voiceRecog){_voiceRecog.abort();}
  const recog=new _SR();
  _voiceRecog=recog;
  recog.lang='en-US';
  recog.interimResults=false;
  recog.maxAlternatives=1;
  playRadioBeep();
  const ind=document.getElementById('voice-ind');
  if(ind){ind.style.display='flex';}
  recog.onresult=async(e)=>{
    const text=e.results[0][0].transcript;
    if(ind){ind.style.display='none';}
    if(!text.trim())return;
    addMsg(text,'user');
    const ph=addMsg('...','engineer');
    speakAck();
    try{
      const r=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({message:text,lap_context:''})});
      const reply=(await r.json()).reply;
      ph.textContent=reply; speak(reply);
    }catch(ex){ph.textContent='Error.';}
  };
  recog.onerror=()=>{if(ind){ind.style.display='none';}};
  recog.onend=()=>{if(ind){ind.style.display='none';}_voiceRecog=null;};
  recog.start();
  addMsg('🎙 Listening...','system');
}
function stopVoiceInput(){
  if(_voiceRecog){
    _voiceRecog.stop();
  }
}

// ─── Header ───────────────────────────────────────────────────────────────
function _onSessionChange(from, to){
  const race=to==='Race'||to==='Race 2'||to==='Race 3';
  if(race){
    addMsg('⚠ Parc fermé. Cockpit only: diff, brake bias, brake balance.','system');
    speak('Parc fermé conditions. Cockpit adjustments only.');
  } else if(from){
    addMsg(`Session: ${to}`,'system');
  }
}
function updateHeader(d){
  document.getElementById('h-track').textContent=d.track||'–';
  document.getElementById('h-temp').textContent=
    d.track_temp?`${d.track_temp}°/${d.air_temp||'–'}°`:'–';
  const stype=d.session_type||'';
  document.getElementById('h-session').textContent=stype||'–';
  const lapDisplay=(!d.current_lap||d.current_lap>99)?'–':d.current_lap;
  document.getElementById('h-lap').textContent=lapDisplay;
  document.getElementById('live-ring').className=
    'live-ring'+((d.laps?.length||d.current_lap>0)?' on':'');
  const valid=(d.laps||[]).filter(l=>l.valid&&l.time_ms>0);
  if(valid.length){
    const bms=Math.min(...valid.map(l=>l.time_ms));
    document.getElementById('h-best').textContent=valid.find(l=>l.time_ms===bms)?.time||'–';
  }
  const last=d.laps?.length?d.laps[d.laps.length-1]:null;
  document.getElementById('h-last').textContent=last?.time||'–:––.–––';
  if(stype&&stype!==_prevSessionType){_onSessionChange(_prevSessionType,stype);_prevSessionType=stype;}
}

// ─── Car status ───────────────────────────────────────────────────────────
function updateCar(st, dm, setup){
  document.getElementById('ers-mode').textContent=st.ers_deploy_mode||'–';
  document.getElementById('ers-pct').textContent=(st.ers_store_pct||0)+'%';
  document.getElementById('ers-fill').style.width=(st.ers_store_pct||0)+'%';
  document.getElementById('ers-dep').textContent=(st.ers_deployed_pct||0)+'%';
  const isTT=(_prevSessionType==='Time Trial');
  document.getElementById('fuel-l').textContent=st.fuel_remaining!=null?st.fuel_remaining+'L':'–L';
  document.getElementById('fuel-laps').textContent=isTT?'–':st.fuel_laps_left!=null?st.fuel_laps_left+' lps':'–';
  document.getElementById('fuel-mix').textContent=st.fuel_mix||'–';
  const tr2=setup?.transmission||{};
  document.getElementById('diff-vals').textContent=tr2.on_throttle!=null?`${tr2.on_throttle}/${tr2.off_throttle}%`:'–';

  const comp=st.tyre_compound||'';
  const tc=TYRE_C[comp]||'#888';
  document.getElementById('tyre-compound').innerHTML=
    comp?`<span style="color:${tc}">■</span> ${comp}  <span style="color:var(--dim)">${st.tyre_age_laps??'–'} laps old</span>`:'–';

  const a=setup.aero||{}, b=setup.brakes||{};
  document.getElementById('wings').textContent=
    a.front_wing!=null?`${a.front_wing} / ${a.rear_wing}`:'–/–';
  document.getElementById('brake-bias').textContent=
    b.brake_bias!=null?`${b.brake_bias}%`:'–%';

  // game order RL,RR,FL,FR → display FL,FR,RL,RR
  const wear=dm.tyre_wear||null;
  const temps=window._lt||[0,0,0,0];
  const hasWear=wear&&wear.some(w=>w>0);
  [['fl',2],['fr',3],['rl',0],['rr',1]].forEach(([id,idx])=>{
    const w=wear?wear[idx]||0:0, temp=temps[idx]||0;
    const wc=w>80?'var(--red)':w>50?'var(--yel)':'var(--grn)';
    const tc2=temp>110?'var(--red)':temp>90?'var(--yel)':'var(--text)';
    document.getElementById('tw-'+id).style.cssText=`width:${Math.min(w,100)}%;background:${wc}`;
    document.getElementById('tv-'+id).textContent=hasWear?w.toFixed(1)+'%':'–%';
    document.getElementById('tv-'+id).style.color=hasWear?wc:'var(--dim)';
    document.getElementById('tt-'+id).textContent=temp?temp+'°':'–°';
    document.getElementById('tt-'+id).style.color=tc2;
  });
}

// ─── Live inputs ──────────────────────────────────────────────────────────
function updateInputs(t){
  const thr=t.throttle||0, brk=t.brake||0, rpm=t.engine_rpm||0;
  setBar('thr',thr,'%'); setBar('brk',brk,'%');
  document.getElementById('bar-rpm').style.width=Math.min(100,rpm/15000*100)+'%';
  document.getElementById('val-rpm').textContent=rpm?Math.round(rpm/100)/10+'k':'–';

  const pct=t.rev_lights_pct||0;
  for(let i=0;i<12;i++){
    const el=document.getElementById('rl'+i);
    const lit=pct>=(i+1)/12*100;
    const hue=i<5?120:i<9?60:0;
    el.style.background=lit?`hsl(${hue},100%,50%)`:'var(--p3)';
  }

  document.getElementById('spd-num').textContent=t.speed||0;
  const g=t.gear||0;
  document.getElementById('gear-disp').textContent=g===0?'N':g<0?'R':g;
  const drs=document.getElementById('drs-box');
  drs.textContent=t.drs?'DRS ON':'DRS OFF';
  drs.className='drs-box'+(t.drs?' on':'');

  const gLat=t.g_lat||0, gLon=t.g_lon||0;
  document.getElementById('g-vals').textContent=
    Math.abs(gLat).toFixed(1)+' / '+Math.abs(gLon).toFixed(1)+' g';
  setGBar('gfl',gLat,5,'var(--grn)','var(--yel)');
  setGBar('gfn',gLon,6,'var(--red)','var(--grn)');

  if(t.brake_temp){
    document.getElementById('brk-temps').textContent=t.brake_temp.map(v=>v+'°').join(' / ');
  }
  document.getElementById('eng-temp').textContent=t.engine_temp!=null?t.engine_temp+'°':'–°';
}

function setBar(id, val, suffix){
  document.getElementById('bar-'+id).style.width=val+'%';
  document.getElementById('val-'+id).textContent=val+suffix;
}
function setGBar(prefix, val, maxG, colPos, colNeg){
  const pct=Math.min(50,Math.abs(val)/maxG*50);
  const f=document.getElementById(prefix+'-fill');
  f.style.width=pct+'%';
  f.style.left=val>=0?'50%':(50-pct)+'%';
  f.style.background=val>=0?colPos:colNeg;
  document.getElementById(prefix+'-val').textContent=val.toFixed(1)+' g';
}

// ─── Sector delta boxes ───────────────────────────────────────────────────
function updateSectorDeltas(laps){
  const valid=laps.filter(l=>l.valid&&l.time_ms>0);
  bestS1Ms=valid.length?Math.min(...valid.filter(l=>l.sector1_ms>0).map(l=>l.sector1_ms)):Infinity;
  bestS2Ms=valid.length?Math.min(...valid.filter(l=>l.sector2_ms>0).map(l=>l.sector2_ms)):Infinity;
  bestS3Ms=valid.length?Math.min(...valid.filter(l=>l.sector3_ms>0).map(l=>l.sector3_ms)):Infinity;

  const lap=selectedLap||(laps.length?laps[laps.length-1]:null);
  if(!lap){resetSectorBoxes();return;}

  const pairs=[
    ['sd-t1','sd-d1',lap.sector1,lap.sector1_ms,bestS1Ms],
    ['sd-t2','sd-d2',lap.sector2,lap.sector2_ms,bestS2Ms],
    ['sd-t3','sd-d3',lap.sector3,lap.sector3_ms,bestS3Ms],
  ];
  let totalDelta=0;
  pairs.forEach(([tId,dId,timeStr,ms,best])=>{
    document.getElementById(tId).textContent=timeStr||'–:––.–––';
    if(ms&&best&&isFinite(best)){
      const delta=ms-best;
      totalDelta+=delta;
      const el=document.getElementById(dId);
      if(delta===0){el.textContent='◆ BEST';el.className='sd-delta best';}
      else if(delta>0){el.textContent='+'+((delta)/1000).toFixed(3)+'s';el.className='sd-delta slow';}
      else{el.textContent=((delta)/1000).toFixed(3)+'s';el.className='sd-delta fast';}
    } else {
      document.getElementById(dId).textContent='–';
      document.getElementById(dId).className='sd-delta none';
    }
  });

  const gapEl=document.getElementById('sd-gap');
  bestLapMs=isFinite(bestS1Ms)&&isFinite(bestS2Ms)&&isFinite(bestS3Ms)?bestS1Ms+bestS2Ms+bestS3Ms:Infinity;
  if(lap.time_ms&&isFinite(bestLapMs)){
    const d=lap.time_ms-bestLapMs;
    gapEl.textContent=(d>0?'+':'')+((d)/1000).toFixed(3);
    gapEl.className='sd-gap-val '+(d<=0?'fast':'slow');
    gapEl.style.color=d<=0?'var(--grn)':'var(--red)';
  } else {
    gapEl.textContent='–'; gapEl.style.color='var(--dim)';
  }
  document.getElementById('sd-lapnum').textContent=lap.lap?'Lap '+lap.lap:'–';
}
function resetSectorBoxes(){
  ['sd-t1','sd-t2','sd-t3'].forEach(id=>document.getElementById(id).textContent='–:––.–––');
  ['sd-d1','sd-d2','sd-d3'].forEach(id=>{document.getElementById(id).textContent='–';document.getElementById(id).className='sd-delta none';});
  document.getElementById('sd-gap').textContent='–';
}

// ─── Laps table ───────────────────────────────────────────────────────────
function updateLaps(laps){
  if(!laps.length){document.getElementById('laps-body').innerHTML='';return;}
  const valid=laps.filter(l=>l.valid&&l.time_ms>0);
  bestLapMs=valid.length?Math.min(...valid.map(l=>l.time_ms)):Infinity;

  const chron=[...laps].filter(l=>l.time_ms>0).sort((a,b)=>a.lap-b.lap);
  const prevMap=new Map();
  for(let i=1;i<chron.length;i++) prevMap.set(chron[i].lap, chron[i-1]);

  const sC=(ms,best,prevMs)=>{
    if(!ms) return '';
    if(isFinite(best)&&ms===best) return 's-best';
    if(prevMs>0&&ms<prevMs)       return 's-fast';
    if(prevMs>0)                  return 's-slow';
    return isFinite(best)?'s-slow':'';
  };

  const tbody=document.getElementById('laps-body');
  tbody.innerHTML='';
  chron.slice().reverse().forEach(lap=>{
    const prev=prevMap.get(lap.lap);
    const isBest=lap.valid&&lap.time_ms===bestLapMs;
    const delta=lap.time_ms-bestLapMs;
    const dStr=(!lap.valid||!isFinite(bestLapMs)||delta===0)?'–':
      ((delta>0?'+':'')+((delta)/1000).toFixed(3));
    const lapTcls=!lap.valid?'':isBest?'s-best':(prev&&lap.time_ms<prev.time_ms?'s-fast':prev?'s-slow':'');
    const comp=lap.status_snap?.tyre_compound||'';
    const tr=document.createElement('tr');
    tr.className=!lap.valid?'invalid-lap':isBest?'best-lap':'';
    if(lap===selectedLap)tr.classList.add('sel-lap');
    tr.innerHTML=`
      <td class="col-num">${lap.lap}</td>
      <td class="${lapTcls}">${lap.time}</td>
      <td class="${sC(lap.sector1_ms,bestS1Ms,prev?.sector1_ms||0)}">${lap.sector1}</td>
      <td class="${sC(lap.sector2_ms,bestS2Ms,prev?.sector2_ms||0)}">${lap.sector2}</td>
      <td class="${sC(lap.sector3_ms,bestS3Ms,prev?.sector3_ms||0)}">${lap.sector3}</td>
      <td class="${delta>0?'delta-pos':delta<0?'delta-neg':''}">${dStr}</td>
      <td><span class="tyre-dot" style="background:${TYRE_C[comp]||'transparent'}"></span>${comp?comp[0]:''}</td>
      <td>${lap.status_snap?.tyre_age_laps??'–'}</td>
      <td>${lap.telemetry?.max_speed_kmh||'–'}</td>
      <td><button onclick="deleteLap(event,${lap.lap})" style="font-size:.5rem;padding:1px 4px;background:#1a0000;color:#ff4444;border:1px solid #440000;border-radius:2px;cursor:pointer">✕</button></td>`;
    tr.onclick=()=>{selectedLap=selectedLap===lap?null:lap;updateSectorDeltas(laps);updateLaps(laps);if(selectedLap)drawMini(selectedLap.mini_sectors||[]);};
    tbody.appendChild(tr);
  });
}

// ─── Setup strip ──────────────────────────────────────────────────────────
function updateSetup(s){
  if(!s?.aero) return;
  const a=s.aero||{},b=s.brakes||{},su=s.suspension||{},g=s.suspension_geometry||{},t=s.tyres||{};
  const _p=v=>v>0?v:'–';
  document.getElementById('su-wing').textContent=`${_p(a.front_wing)}/${_p(a.rear_wing)}`;
  document.getElementById('su-bb').textContent=`${_p(b.brake_bias)}% · ${_p(b.brake_pressure)}%p`;
  document.getElementById('su-susp').textContent=`${_p(su.front_suspension)}/${_p(su.rear_suspension)}`;
  document.getElementById('su-arb').textContent=`${_p(su.front_anti_roll_bar)}/${_p(su.rear_anti_roll_bar)}`;
  document.getElementById('su-camber').textContent=`${g.front_camber??'–'}/${g.rear_camber??'–'}`;
  document.getElementById('su-toe').textContent=`${g.front_toe??'–'}/${g.rear_toe??'–'}`;
  document.getElementById('su-pf').textContent=`${_p(t.front_left_pressure)}/${_p(t.front_right_pressure)}`;
  document.getElementById('su-pr').textContent=`${_p(t.rear_left_pressure)}/${_p(t.rear_right_pressure)}`;
  const hasPres=t.front_left_pressure>0||t.rear_left_pressure>0;
  document.getElementById('tyre-press').textContent=hasPres
    ?`${t.front_left_pressure} / ${t.front_right_pressure} / ${t.rear_left_pressure} / ${t.rear_right_pressure}`
    :'– / – / – / –';
}

// ─── Track map ────────────────────────────────────────────────────────────
const tc=document.getElementById('track-canvas');
const tctx=tc.getContext('2d');
function speedColor(s,mn,mx){const t=Math.max(0,Math.min(1,(s-mn)/(mx-mn||1)));return `hsl(${t*180},100%,50%)`;}
function drawTrack(d){
  const path=selectedLap?.path?.length>5?selectedLap.path:
    (d.current_path?.length>30?d.current_path:(d.laps?.length?d.laps[d.laps.length-1]?.path:null));
  if(path) drawPath(path);
}
function drawPath(path){
  if(!path||path.length<5)return;
  const W=tc.width,H=tc.height;
  tctx.clearRect(0,0,W,H);
  const xs=path.map(p=>p[0]),zs=path.map(p=>p[1]),ss=path.map(p=>p[2]);
  const mnX=Math.min(...xs),mxX=Math.max(...xs),mnZ=Math.min(...zs),mxZ=Math.max(...zs);
  const pad=14,scX=(W-pad*2)/(mxX-mnX||1),scZ=(H-pad*2)/(mxZ-mnZ||1),sc=Math.min(scX,scZ);
  const oX=pad+(W-pad*2-(mxX-mnX)*sc)/2,oZ=pad+(H-pad*2-(mxZ-mnZ)*sc)/2;
  const px=i=>oX+(path[i][0]-mnX)*sc, pz=i=>oZ+(path[i][1]-mnZ)*sc;
  const mnS=Math.min(...ss),mxS=Math.max(...ss);
  tctx.lineWidth=7;tctx.strokeStyle='#0f1a14';
  tctx.beginPath();tctx.moveTo(px(0),pz(0));
  for(let i=1;i<path.length;i++)tctx.lineTo(px(i),pz(i));
  tctx.stroke();
  tctx.lineWidth=2.5;
  for(let i=1;i<path.length;i++){
    tctx.strokeStyle=speedColor(path[i][2],mnS,mxS);
    tctx.beginPath();tctx.moveTo(px(i-1),pz(i-1));tctx.lineTo(px(i),pz(i));tctx.stroke();
  }
  const last=path.length-1;
  tctx.fillStyle='#fff';tctx.beginPath();tctx.arc(px(last),pz(last),4,0,Math.PI*2);tctx.fill();
  document.getElementById('map-pts').textContent=path.length+' pts';
}

// ─── Mini sector chart ────────────────────────────────────────────────────
const mc=document.getElementById('mini-canvas');
const mctx=mc.getContext('2d');
function drawMini(mini){
  if(!mini?.length)return;
  mc.width=mc.offsetWidth||mc.parentElement?.clientWidth||400;
  const W=mc.width,H=mc.height,n=mini.length,bw=W/n;
  mctx.clearRect(0,0,W,H);
  const maxS=Math.max(...mini.map(s=>s.avg_spd),1);
  mini.forEach((s,i)=>{
    const x=i*bw;
    // always draw slot background so structure is visible
    mctx.fillStyle='#0a1010';
    mctx.fillRect(x+1,0,bw-2,H);
    if(s.avg_spd>0){
      const sh=Math.max(3,(s.avg_spd/maxS)*(H-4));
      const hue=(s.avg_spd/maxS)*160;
      mctx.fillStyle=`hsla(${hue},100%,40%,.9)`;
      mctx.fillRect(x+1,H-sh,bw-2,sh);
    }
    if(s.thr_pct>5){
      const ty=H-(s.thr_pct/100)*(H-4)-2;
      mctx.fillStyle='rgba(0,232,122,.85)';
      mctx.fillRect(x+1,ty,bw-2,2);
    }
    if(s.brk_pct>5){
      const by=H-(s.brk_pct/100)*(H-4)-2;
      mctx.fillStyle='rgba(255,50,0,.85)';
      mctx.fillRect(x+1,by,bw-2,2);
    }
    if(i%5===0){
      mctx.fillStyle='rgba(74,90,96,.8)';
      mctx.font='8px Courier New';
      mctx.fillText(i+1,x+2,H-2);
    }
  });
}

// ─── Lap management ───────────────────────────────────────────────────────
async function deleteLap(e, lapNum){
  e.stopPropagation();
  e.preventDefault();
  const row=e.target.closest('tr');
  if(row) row.remove();
  await fetch('/api/delete_lap',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({lap:parseInt(lapNum,10)})});
}
async function resetAllLaps(){
  if(!confirm('Delete all laps?')) return;
  await fetch('/api/reset_laps',{method:'POST'});
}

// ─── Chat ─────────────────────────────────────────────────────────────────
function addMsg(text,type){
  const d=document.createElement('div');
  d.className=type==='system'?'msg-system':`msg msg-${type}`;
  d.textContent=text;
  const c=document.getElementById('chat-messages');
  c.appendChild(d);c.scrollTop=c.scrollHeight;
  return d;
}
const ACK_PHRASES=[
  'Copy, stand by.','Roger, checking.','Copy that.','Stand by.',
  'Understood.','Roger.','On it.','Looking at it now.',
  'Give me a moment.','Checking the data.'
];
async function speakAck(){
  if(Math.random()>0.5) return;
  const phrase=ACK_PHRASES[Math.floor(Math.random()*ACK_PHRASES.length)];
  await speak(phrase);
}
async function chatWithCtx(ctx){
  const ph=addMsg('...','engineer');
  speakAck();
  try{
    const r=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({message:'',lap_context:ctx})});
    const reply=(await r.json()).reply;
    ph.textContent=reply; speak(reply);
  }catch(e){ph.textContent='Connection error.'}
}
async function sendChat(){
  const inp=document.getElementById('chat-input');
  const msg=inp.value.trim(); if(!msg)return;
  addMsg(msg,'user'); inp.value='';
  const ph=addMsg('...','engineer');
  try{
    const r=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({message:msg,lap_context:''})});
    const reply=(await r.json()).reply;
    ph.textContent=reply; speak(reply);
  }catch(e){ph.textContent='Connection error.'}
}
async function resetChat(){
  await fetch('/api/reset_chat',{method:'POST'});
  document.getElementById('chat-messages').innerHTML=
    '<div class="msg-system">Chat reset.</div>';
}
async function analyzeLaps(){
  addMsg('Analysing last 5 laps...','system');
  const eph=addMsg('...','engineer');
  try{
    const r=await fetch('/api/analyze',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
    const reply=(await r.json()).reply;
    eph.textContent=reply;
    speak(reply);
  }catch(e){eph.textContent='Error.';}
}

// ─── Resize ───────────────────────────────────────────────────────────────
function resize(){
  tc.width=tc.parentElement.clientWidth;
  tc.height=Math.round(tc.width*0.65);
  mc.width=mc.offsetWidth;
}
window.addEventListener('resize',resize);
resize();

// ─── Init ─────────────────────────────────────────────────────────────────
document.addEventListener('click',armAudio,{once:true});
setInterval(poll,1000);
setInterval(pollTrig,1200);
setInterval(pollVoiceTrig,400);
poll();
