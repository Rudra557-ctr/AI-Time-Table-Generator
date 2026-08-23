// state.js — holds job_id, schemas, per-dataset rows cache, validation
export const LS_KEY='sih_job_id';
export let jobId = localStorage.getItem(LS_KEY) || null;
export let schemas = null;   // {datasets:{...}, required:[], optional:[]}
export let validation = null; // {blockers,warnings,per_dataset,summary}
export let counts = {};
export let jobStatus = {status:'unknown'};
const listeners = new Set();
export function subscribe(fn){ listeners.add(fn); return ()=>listeners.delete(fn); }
function notify(){ listeners.forEach(fn=>{ try{fn();}catch(e){console.error(e)} }); }

export function setJobId(id){
  jobId=id;
  if(id) localStorage.setItem(LS_KEY, id); else localStorage.removeItem(LS_KEY);
  notify();
}
export function setSchemas(s){ schemas=s; notify(); }
export function setValidation(v){ validation=v; notify(); }
export function setCounts(c){ counts=c; notify(); }
export function setJobStatus(s){ jobStatus=s; notify(); }

export async function refreshJob(){
  if(!jobId) return;
  const mod = await import('./api.js');
  const j = await mod.getJob(jobId);
  validation = j.validation;
  counts = j.counts || {};
  jobStatus = {status:j.status, objective:j.objective, output:j.output, counts};
  notify();
  return j;
}
export async function ensureJob(){
  const mod = await import('./api.js');
  if(jobId){
    try{ await mod.getJob(jobId); return jobId; }catch(e){ /* create new */ }
  }
  const j = await mod.createJob();
  setJobId(j.job_id);
  validation = j.validation;
  notify();
  return j.job_id;
}
