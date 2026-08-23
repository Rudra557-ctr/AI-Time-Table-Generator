import * as api from './api.js';
import * as state from './state.js';
import { el, badgeFor, issueList, toast, tableEditor, matrixEditor } from './components.js';

const STEPS = [
  {id:'universities', label:'1. University', datasets:['universities']},
  {id:'departments', label:'2. Departments', datasets:['departments']},
  {id:'programs', label:'3. Programs', datasets:['programs']},
  {id:'terms', label:'4. Terms', datasets:['academic_terms']},
  {id:'timeslots', label:'5. Time Slots', datasets:['time_slots'], special:'timeslots'},
  {id:'rooms', label:'6. Rooms', datasets:['rooms']},
  {id:'faculty', label:'7. Faculty', datasets:['faculty']},
  {id:'sections', label:'8. Sections', datasets:['sections']},
  {id:'students', label:'9. Students', datasets:['students','student_enrollments'], desc:'Students + enrollments (bulk import recommended)'},
  {id:'courses', label:'10. Courses', datasets:['courses']},
  {id:'assignments', label:'11. Assignments', datasets:['faculty_courses']},
  {id:'offerings', label:'12. Offerings', datasets:['course_offerings']},
  {id:'availability', label:'13. Availability', datasets:['faculty_availability','room_availability'], special:'availability'},
  {id:'electives', label:'14. Electives', datasets:['elective_groups','elective_group_courses']},
  {id:'events', label:'15. Fixed Events', datasets:['fixed_events']},
  {id:'advanced', label:'Advanced', datasets:['academic_rules'], readonly:true},
  {id:'review', label:'Review & Solve', datasets:[], special:'review'},
];

let currentStep = location.hash.slice(1) || null;
let cache = {}; // dataset -> rows

function totalRowCount(){
  return Object.values(state.counts||{}).reduce((a,b)=> a+(b||0), 0);
}

async function boot(){
  // schemas
  try{
    const sc = await api.getSchema();
    state.setSchemas(sc);
  }catch(e){ console.error(e); }
  // job
  await state.ensureJob();
  await state.refreshJob();
  bindHeader();
  window.addEventListener('hashchange', ()=>{ currentStep = location.hash.slice(1) || null; render(); });
  state.subscribe(render);
  // No explicit step in the URL and nothing entered yet -> lead with upload,
  // not "step 1 of 16" blank forms. Direct links to a step (bookmarked, or
  // #review after an upload) always skip this and go straight there.
  if(!currentStep && totalRowCount()===0){
    render();
    return;
  }
  currentStep = currentStep || STEPS[0].id;
  await refreshCacheForStep(currentStep);
  render();
}

function bindHeader(){
  const sel=document.getElementById('jobSelect');
  const btn=document.getElementById('newJobBtn');
  btn.onclick = async()=>{ const j=await api.createJob(); state.setJobId(j.job_id); await state.refreshJob(); cache={}; currentStep=null; location.hash=''; render(); };
  // populate known jobs from localStorage? simple: show current
  sel.innerHTML='';
  sel.appendChild(el('option',{text: state.jobId || 'no job', value: state.jobId||''}));
  sel.onchange=async(e)=>{
    const v=e.target.value.trim();
    if(v){ state.setJobId(v); await state.refreshJob(); cache={}; render(); }
  };
}

async function routeToFirstGap(){
  await state.refreshJob();
  const per = state.validation?.per_dataset || {};
  let target = 'review';
  for(const st of STEPS){
    if(!st.datasets.length) continue;
    const blockers = st.datasets.reduce((sum,ds)=> sum + (per[ds]?.blockers||0), 0);
    if(blockers>0){ target = st.id; break; }
  }
  cache = {};
  currentStep = target;
  location.hash = target;
  await refreshCacheForStep(target);
  render();
}

async function refreshCacheForStep(stepId){
  const step = STEPS.find(s=>s.id===stepId);
  if(!step) return;
  for(const ds of step.datasets){
    try{ const j=await api.getDataset(state.jobId, ds); cache[ds]=j.rows; }catch(e){ cache[ds]=[]; }
  }
  // for availability we need faculty/rooms/time_slots as well
  if(step.special==='availability'){
    for(const ds of ['faculty','rooms','time_slots']){
      if(!(ds in cache)){ try{ const j=await api.getDataset(state.jobId, ds); cache[ds]=j.rows; }catch(_){}}
    }
  }
}

function overallProgress(){
  const per = state.validation?.per_dataset || {};
  let total=0, ok=0;
  for(const ds of Object.keys(per)){
    total++;
    if((per[ds].blockers||0)===0) ok++;
  }
  return total? Math.round(100*ok/total):0;
}

function render(){
  renderNav();
  renderSide();
  renderMain();
}

function renderNav(){
  const nav=document.getElementById('nav');
  nav.innerHTML='';
  for(const st of STEPS){
    const perAgg = st.datasets.length ? aggregate(st.datasets) : null;
    const row=el('div',{class:'step'+(st.id===currentStep?' active':'') , onclick: async()=>{ location.hash=st.id; if(!cacheForStepLoaded(st)) await refreshCacheForStep(st.id); }}, [
      el('div',{class:'left'},[
        el('span',{text: st.label}),
      ]),
      perAgg ? badgeFor(st.id, perAgg) : (st.id==='review' ? badgeFor('review', {blockers: state.validation?.summary?.total_blockers||0, warnings: state.validation?.summary?.total_warnings||0, rows:0}) : el('span'))
    ]);
    nav.appendChild(row);
  }
  function aggregate(dss){
    const per=state.validation?.per_dataset||{};
    let rows=0, blockers=0, warnings=0;
    for(const ds of dss){
      const p=per[ds]; if(p){ rows+=p.rows; blockers+=p.blockers; warnings+=p.warnings; }
    }
    return {rows, blockers, warnings};
  }
  function cacheForStepLoaded(st){ return st.datasets.every(ds=> ds in cache); }
}

function renderSide(){
  const side=document.getElementById('side');
  side.innerHTML='';
  const v=state.validation;
  if(!v){ side.appendChild(el('div',{text:'Loading validation…'})); return; }
  const pct=overallProgress();
  side.appendChild(el('h3',{text:'Progress'}));
  const bar=el('div',{class:'progress'},[el('div',{style:`width:${pct}%`})]);
  side.appendChild(bar);
  side.appendChild(el('div',{class:'sub', text:`${pct}% datasets without BLOCKERs · ${v.summary.total_blockers} blocker(s), ${v.summary.total_warnings} warning(s)`, style:'font-size:11px;color:var(--muted)'}));
  side.appendChild(el('div',{style:'height:8px'}));
  const can = v.summary.can_solve;
  side.appendChild(el('div',{class: can ? 'notice ok':'notice err', text: can ? 'Solve enabled — 0 BLOCKERs' : `Solve blocked — fix ${v.summary.total_blockers} BLOCKER(s)`}));
  side.appendChild(el('div',{style:'height:10px'}));
  side.appendChild(el('h3',{text:'Issues'}));
  const all = [...(v.blockers||[]), ...(v.warnings||[])];
  side.appendChild(issueList(all));
  const jobId=state.jobId;
  if(jobId){
    side.appendChild(el('div',{style:'margin-top:10px'},[
      el('a',{href:`/api/templates/all.zip`, text:'⬇ Download all templates (ZIP)'}),
    ]));
  }
}

async function renderMain(){
  const main=document.getElementById('main');
  main.innerHTML='';
  if(!currentStep){
    renderStart(main);
    return;
  }
  const step = STEPS.find(s=>s.id===currentStep) || STEPS[0];
  main.appendChild(el('div',{class:'card'},[
    el('h2',{text: step.label}),
    step.desc ? el('div',{class:'desc', text: step.desc}) : null,
    el('div',{class:'sub', text: step.datasets.length? `Datasets: ${step.datasets.join(', ')}` : 'Final review and solve'}),
  ]));

  if(step.special==='review'){
    await renderReview(main);
    return;
  }
  if(step.special==='timeslots'){
    await renderTimeSlots(main);
    // also render generic table below as fallback editor
  }
  if(step.special==='availability'){
    await renderAvailability(main);
    return;
  }
  // generic table editors for each dataset in step
  for(const ds of step.datasets){
    const card=el('div',{class:'card'});
    const fields = state.schemas?.datasets?.[ds] || [];
    card.appendChild(el('h2',{text: ds}));
    if(fields.length) card.appendChild(el('div',{class:'desc', text: fields.map(f=>f.name).join(' · ')}));
    const tb = el('div',{class:'toolbar'});
    const btnAdd = el('button',{class:'btn small', text:'+ Add row', onclick:()=>{ editor.addRow({}); }});
    const btnSave = el('button',{class:'btn primary small', text:'Save'});
    const btnClear = el('button',{class:'btn small', text:'Clear', onclick:()=>{ if(confirm('Clear all rows?')){ cache[ds]=[]; editor.rebuildRows([]); }}});
    const aTpl = el('a',{class:'btn small', href: api.templateUrl(ds), text:'⬇ Template', target:'_blank'});
    const inpFile = el('input',{type:'file', accept:'.csv,.xlsx,.xls'});
    inpFile.style.display='none';
    const btnImport = el('button',{class:'btn small', text:'Import CSV/XLSX'});
    btnImport.onclick=()=> inpFile.click();
    inpFile.onchange=async()=>{
      if(!inpFile.files[0]) return;
      btnImport.textContent='Importing…'; btnImport.disabled=true;
      try{
        const res=await api.importDataset(state.jobId, ds, inpFile.files[0]);
        toast(`Imported ${res.imported} rows into ${ds}`, 'ok');
        cache[ds]= (await api.getDataset(state.jobId, ds)).rows;
        await state.refreshJob();
        // rebuild editor with new rows
        editor.rebuildRows(cache[ds]);
      }catch(e){
        const body=e.body||{};
        let msg=e.message;
        if(body.validation){
          const iss=[...(body.validation.blockers||[]), ...(body.validation.warnings||[])];
          main.prepend(issueList(iss));
          msg = `Import failed: ${iss.slice(0,2).map(i=>i.message).join(' | ')}`;
        }
        toast(msg,'err');
      }finally{ btnImport.textContent='Import CSV/XLSX'; btnImport.disabled=false; inpFile.value=''; }
    };
    tb.appendChild(btnAdd); tb.appendChild(btnSave); tb.appendChild(btnClear); tb.appendChild(aTpl); tb.appendChild(btnImport); tb.appendChild(inpFile);
    card.appendChild(tb);
    const rows = cache[ds]||[];
    // ensure at least params for tableEditor
    const editor = makeDatasetEditor(card, ds, fields, rows, btnSave);
    main.appendChild(card);
  }
}

function makeDatasetEditor(card, ds, fields, rows, saveBtn){
  // create table editor inside card
  const holder=el('div');
  card.appendChild(holder);
  const ro = rows.map(r=> ({...r}));
  // ensure at least one empty row hint if empty and dataset is small
  const ed = tableEditor(fields, ro, {});
  holder.appendChild(ed.wrap);
  // expose rebuild
  ed.rebuildRows = (newRows)=>{
    ro.length=0; newRows.forEach(r=>ro.push({...r}));
    holder.innerHTML=''; const ed2=tableEditor(fields, ro, {}); holder.appendChild(ed2.wrap);
    // rebind save
    saveBtn.onclick = async()=> doSave(ds, fields, ed2);
  };
  saveBtn.onclick = async()=> doSave(ds, fields, ed);
  async function doSave(dataset, _fields, editor){
    const outRows = editor.getRows();
    // strip empty trailing row if completely blank
    const filtered = outRows.filter(r=> Object.values(r).some(v=> String(v).trim()!==''));
    saveBtn.textContent='Saving…'; saveBtn.disabled=true;
    try{
      await api.putDataset(state.jobId, dataset, filtered);
      toast(`Saved ${dataset} (${filtered.length} rows)`,'ok');
      cache[dataset]=filtered;
      await state.refreshJob();
      renderNav(); renderSide();
    }catch(e){
      const body=e.body||{};
      const iss=[...(body.validation?.blockers||[]), ...(body.validation?.warnings||[])];
      if(iss.length) holder.prepend(issueList(iss));
      toast(e.message,'err');
    }finally{ saveBtn.textContent='Save'; saveBtn.disabled=false; }
  }
  return ed;
}

async function renderTimeSlots(main){
  const card=el('div',{class:'card'});
  card.appendChild(el('h2',{text:'Time Slots — preset generator'}));
  card.appendChild(el('div',{class:'desc', text:'Generates Mon–Fri × 7 periods (09:00–10:00 … 16:00–17:00, lunch 13:00–14:00 free). Edits below; saving overwrites the table.'}));
  const btnGen = el('button',{class:'btn primary small', text:'Generate Mon–Fri × 7 preset'});
  const hint = el('div',{class:'notice', text:'Click Generate to fill the table editor below. You can then edit individual slots.'});
  card.appendChild(el('div',{class:'toolbar'},[btnGen]));
  card.appendChild(hint);
  btnGen.onclick=async()=>{
    const slots=[];
    const days=['MON','TUE','WED','THU','FRI'];
    const periods=[
      [1,'09:00','10:00'], [2,'10:00','11:00'], [3,'11:00','12:00'], [4,'12:00','13:00'],
      [5,'14:00','15:00'], [6,'15:00','16:00'], [7,'16:00','17:00'],
    ];
    for(const d of days) for(const [n,s,e] of periods) slots.push({slot_id:`${d}_${s.replace(':','')}`, day:d, period_number:String(n), start_time:s, end_time:e, is_break:'False'});
    cache['time_slots']=slots;
    // find the time_slots editor holder below and rebuild (simple: re-render step)
    await api.putDataset(state.jobId, 'time_slots', slots).catch(()=>{});
    await state.refreshJob();
    location.reload();
  };
  main.appendChild(card);
}

async function renderAvailability(main){
  // Need faculty, rooms, time_slots caches
  for(const ds of ['faculty','rooms','time_slots','faculty_availability','room_availability']){
    if(!(ds in cache)){
      try{ cache[ds]=(await api.getDataset(state.jobId, ds)).rows; }catch(_){ cache[ds]=[]; }
    }
  }
  const facs = cache['faculty']||[];
  const rooms = cache['rooms']||[];
  const slots = (cache['time_slots']||[]).filter(s=> String(s.is_break).toLowerCase()!=='true');
  const facIds = facs.map(r=> r.faculty_id).filter(Boolean);
  const roomIds = rooms.map(r=> r.room_id).filter(Boolean);
  const slotIds = slots.map(s=> s.slot_id).filter(Boolean);

  // Faculty availability matrix
  const cardF=el('div',{class:'card'});
  cardF.appendChild(el('h2',{text:'Faculty availability'}));
  cardF.appendChild(el('div',{class:'desc', text:'Checked = available (HC06). One checkbox per faculty × slot.'}));
  const setF=new Set((cache['faculty_availability']||[]).filter(r=> String(r.available).toLowerCase()==='true').map(r=> `${r.faculty_id}|${r.slot_id}`));
  if(!facIds.length || !slotIds.length){
    cardF.appendChild(el('div',{class:'notice warn', text:'Add Faculty and Time Slots first to use the matrix, or import faculty_availability.csv.'}));
  } else {
    cardF.appendChild(el('div',{class:'grid-shortcuts'},[
      el('button',{class:'btn small', text:'All available', onclick:()=>{ facIds.forEach(f=> slotIds.forEach(s=> setF.add(`${f}|${s}`))); cardF.querySelectorAll('input[type=checkbox]').forEach(cb=> cb.checked=true); }}),
      el('button',{class:'btn small', text:'Clear', onclick:()=>{ setF.clear(); cardF.querySelectorAll('input[type=checkbox]').forEach(cb=> cb.checked=false); }}),
    ]));
    cardF.appendChild(matrixEditor(facIds, slotIds, setF));
    const btnSaveF=el('button',{class:'btn primary small', text:'Save faculty availability'});
    btnSaveF.onclick=async()=>{
      const rows=[]; for(const f of facIds) for(const s of slotIds){
        rows.push({faculty_id:f, slot_id:s, available: setF.has(`${f}|${s}`)?'True':'False', preference_score:'3'});
      }
      btnSaveF.textContent='Saving…'; btnSaveF.disabled=true;
      try{ await api.putDataset(state.jobId, 'faculty_availability', rows); toast('Saved faculty_availability','ok'); cache['faculty_availability']=rows; await state.refreshJob(); renderNav(); renderSide(); }catch(e){ toast(e.message,'err'); }finally{ btnSaveF.textContent='Save faculty availability'; btnSaveF.disabled=false; }
    };
    cardF.appendChild(el('div',{class:'toolbar'},[btnSaveF, el('a',{class:'btn small', href:api.templateUrl('faculty_availability'), text:'⬇ Template'})]));
  }
  main.appendChild(cardF);

  const cardR=el('div',{class:'card'});
  cardR.appendChild(el('h2',{text:'Room availability'}));
  cardR.appendChild(el('div',{class:'desc', text:'Checked = available (HC07).'}));
  const setR=new Set((cache['room_availability']||[]).filter(r=> String(r.available).toLowerCase()==='true').map(r=> `${r.room_id}|${r.slot_id}`));
  if(!roomIds.length || !slotIds.length){
    cardR.appendChild(el('div',{class:'notice warn', text:'Add Rooms and Time Slots first to use the matrix.'}));
  } else {
    cardR.appendChild(el('div',{class:'grid-shortcuts'},[
      el('button',{class:'btn small', text:'All available', onclick:()=>{ roomIds.forEach(rid=> slotIds.forEach(s=> setR.add(`${rid}|${s}`))); cardR.querySelectorAll('input[type=checkbox]').forEach(cb=> cb.checked=true); }}),
      el('button',{class:'btn small', text:'Clear', onclick:()=>{ setR.clear(); cardR.querySelectorAll('input[type=checkbox]').forEach(cb=> cb.checked=false); }}),
    ]));
    cardR.appendChild(matrixEditor(roomIds, slotIds, setR));
    const btnSaveR=el('button',{class:'btn primary small', text:'Save room availability'});
    btnSaveR.onclick=async()=>{
      const rows=[]; for(const rid of roomIds) for(const s of slotIds){
        rows.push({room_id:rid, slot_id:s, available: setR.has(`${rid}|${s}`)?'True':'False'});
      }
      btnSaveR.textContent='Saving…'; btnSaveR.disabled=true;
      try{ await api.putDataset(state.jobId, 'room_availability', rows); toast('Saved room_availability','ok'); cache['room_availability']=rows; await state.refreshJob(); renderNav(); renderSide(); }catch(e){ toast(e.message,'err'); }finally{ btnSaveR.textContent='Save room availability'; btnSaveR.disabled=false; }
    };
    cardR.appendChild(el('div',{class:'toolbar'},[btnSaveR, el('a',{class:'btn small', href:api.templateUrl('room_availability'), text:'⬇ Template'})]));
  }
  main.appendChild(cardR);

  // also allow raw table fallback as import path
  main.appendChild(el('div',{class:'notice', text:'Tip: Matrices save as faculty_availability / room_availability datasets. You can also Import CSV per-dataset from the table steps.'}));
}

async function renderReview(main){
  const v=state.validation;
  const card=el('div',{class:'card'});
  card.appendChild(el('h2',{text:'Validation summary'}));
  const per=v?.per_dataset||{};
  const rows = Object.entries(per).map(([ds, p])=> el('tr',{},[el('td',{text: ds}), el('td',{text: String(p.rows)}), el('td',{text: String(p.blockers)}), el('td',{text: String(p.warnings)})]));
  const tbl=el('table',{},[
    el('thead',{},[el('tr',{},[el('th',{text:'dataset'}), el('th',{text:'rows'}), el('th',{text:'blockers'}), el('th',{text:'warnings'})])]),
    el('tbody',{}, rows),
  ]);
  const wrap=el('div',{class:'table-wrap'}); wrap.appendChild(tbl);
  card.appendChild(wrap);
  const sum=v?.summary||{total_blockers:0,total_warnings:0,can_solve:false};
  card.appendChild(el('div',{class: sum.can_solve ? 'notice ok':'notice err', text: sum.can_solve ? `Ready to solve — 0 BLOCKERs (${sum.total_warnings} warning(s))` : `Fix ${sum.total_blockers} BLOCKER(s) before solving`, style:'margin-top:8px'}));
  const tb=el('div',{class:'toolbar'});
  const solveBtn=el('button',{class:'btn primary', text: sum.can_solve ? 'Solve (CP-SAT)':'Solve (blocked)'});
  solveBtn.disabled=!sum.can_solve;
  const timeInp=el('input',{type:'number', value:'60', style:'width:90px'});
  const timeLbl=el('span',{text:' time limit (s) '});
  tb.appendChild(timeLbl); tb.appendChild(timeInp); tb.appendChild(solveBtn);
  card.appendChild(tb);
  const progress=el('div',{style:'margin-top:10px'});
  const log=el('div',{style:'margin-top:6px'});
  card.appendChild(progress); card.appendChild(log);
  let pollIv=null, elapsedIv=null;
  function stopTimers(){ if(pollIv) clearInterval(pollIv); if(elapsedIv) clearInterval(elapsedIv); pollIv=null; elapsedIv=null; }
  solveBtn.onclick=async()=>{
    stopTimers();
    progress.innerHTML=''; log.innerHTML=''; solveBtn.disabled=true; solveBtn.textContent='Solving…';
    const startedAt=Date.now();
    progress.appendChild(el('div',{class:'notice', text:'Hard + soft constraints solving together — this can take up to 2 minutes for a full timetable. Keep this tab open.'}));
    const elapsedEl=el('div',{class:'sub', style:'margin-top:4px;font-size:11px;color:var(--muted)', text:'Elapsed: 0s'});
    progress.appendChild(elapsedEl);
    elapsedIv=setInterval(()=>{ elapsedEl.textContent=`Elapsed: ${Math.round((Date.now()-startedAt)/1000)}s`; }, 1000);
    try{
      const r=await api.solveJob(state.jobId, parseInt(timeInp.value||'60',10));
      log.appendChild(el('div',{class:'notice', text: `Job ${r.job_id}: ${r.status}`}));
      // poll /api/status
      pollIv=setInterval(async()=>{
        const st=await api.getStatus(state.jobId);
        log.innerHTML=`<div class="notice">Status: ${st.status}${st.objective?` · objective ${st.objective}`:''}</div>`;
        if(st.status && (String(st.status).includes('OPTIMAL') || String(st.status).includes('FEASIBLE'))){
          stopTimers();
          solveBtn.textContent='Done';
          progress.innerHTML='';
          log.appendChild(el('div',{class:'notice ok', text: `Done! `}));
          const a1=el('a',{href:`/api/download/${state.jobId}`, text:'⬇ timetable.csv', target:'_blank', class:'btn small'});
          const wrap2=el('div',{class:'toolbar'}); wrap2.appendChild(a1);
          // per-section downloads
          const secs = [...new Set((cache['course_offerings']||[]).map(r=>r.section_id).filter(Boolean))];
          secs.slice(0,12).forEach(sec=> wrap2.appendChild(el('a',{href:`/api/download_class/${state.jobId}/${sec}`, text: sec, class:'btn small', target:'_blank'})));
          log.appendChild(wrap2);
        }
        if(String(st.status).startsWith('ERROR')){ stopTimers(); solveBtn.textContent='Error'; progress.innerHTML=''; log.appendChild(el('div',{class:'notice err', text: st.trace||st.status})); }
        if(String(st.status)==='UNKNOWN'){ /* keep polling a bit then stop */ }
      }, 2000);
    }catch(e){
      stopTimers(); progress.innerHTML='';
      const body=e.body||{}; if(body.validation) log.appendChild(issueList([...(body.validation.blockers||[]), ...(body.validation.warnings||[])]));
      else log.appendChild(el('div',{class:'notice err', text: e.message}));
      solveBtn.disabled=false; solveBtn.textContent='Solve (CP-SAT)';
    }
  };
  main.appendChild(card);
  // bulk import shortcut, in case they still have gaps to patch from another file
  renderUploadWidget(main, {
    title: 'Bulk import more files (ZIP/CSV/XLSX)',
    desc: 'Already uploaded once? Add more files here to patch remaining gaps — same fuzzy-matching import as the start screen.',
  });
}

function renderStart(main){
  main.appendChild(el('div',{class:'card'},[
    el('h2',{text:"Let's build your timetable"}),
    el('div',{class:'desc', text:"Fastest way in: upload whatever you already have — even a messy Excel export or last year's CSVs — and we'll show you exactly what's missing. No need to fill every form by hand."}),
  ]));
  renderUploadWidget(main, {
    title: '⬆ Upload your existing data (recommended)',
    desc: 'ZIP of CSVs, or individual CSV/XLSX files. We auto-detect each file\'s dataset and fuzzy-match its columns.',
    onDone: routeToFirstGap,
  });
  const blankCard=el('div',{class:'card'});
  blankCard.appendChild(el('h2',{text:'Or start from blank forms'}));
  blankCard.appendChild(el('div',{class:'desc', text:'16 guided steps, one dataset at a time. Only worth it if you have nothing to upload yet — most colleges have something.'}));
  blankCard.appendChild(el('button',{class:'btn small', text:'Start from blank forms', onclick:()=>{ currentStep=STEPS[0].id; location.hash=STEPS[0].id; refreshCacheForStep(STEPS[0].id).then(render); }}));
  main.appendChild(blankCard);
}

// Shared upload widget — used both on the Start screen (upload-first landing)
// and as a "patch more gaps" shortcut at the bottom of Review & Solve.
function renderUploadWidget(main, opts={}){
  const upCard=el('div',{class:'card'});
  upCard.appendChild(el('h2',{text: opts.title || 'Bulk import (ZIP/CSV/XLSX)'}));
  upCard.appendChild(el('div',{class:'desc', text: opts.desc || 'Upload a ZIP of CSVs or individual files.'}));
  const drop=el('div',{class:'drop', text:'Drag & drop files here or choose'});
  const finp=el('input',{type:'file', multiple:true, accept:'.csv,.zip,.xlsx,.xls'});
  const chkId='fillChk_'+Math.random().toString(36).slice(2);
  const chk=el('label',{},[el('input',{type:'checkbox', id:chkId}), ' Fill missing with demo data (?fill=true)']);
  const btnUp=el('button',{class:'btn primary small', text:'Upload'});
  upCard.appendChild(drop); upCard.appendChild(finp); upCard.appendChild(chk); upCard.appendChild(btnUp);
  drop.addEventListener('dragover', e=>{e.preventDefault(); drop.classList.add('dragover')});
  drop.addEventListener('dragleave', ()=> drop.classList.remove('dragover'));
  drop.addEventListener('drop', e=>{e.preventDefault(); drop.classList.remove('dragover'); finp.files=e.dataTransfer.files});
  btnUp.onclick=async()=>{
    if(!finp.files.length) return alert('Choose files');
    const fill=document.getElementById(chkId).checked;
    btnUp.textContent='Uploading…'; btnUp.disabled=true;
    try{
      const j=await api.uploadFiles(finp.files, fill);
      state.setJobId(j.job_id); await state.refreshJob(); toast('Upload complete','ok');
      if(j.validation){
        const iss=[...(j.validation.blockers||[]), ...(j.validation.warnings||[])];
        if(iss.length) upCard.appendChild(issueList(iss));
      }
      if(opts.onDone) await opts.onDone();
      else { cache={}; renderNav(); renderSide(); }
    }catch(e){ toast(e.message,'err'); }finally{ btnUp.textContent='Upload'; btnUp.disabled=false; }
  };
  main.appendChild(upCard);
}

boot();
