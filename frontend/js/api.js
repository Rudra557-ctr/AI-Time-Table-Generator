// api.js — thin wrappers over new backend endpoints

// Minimal access-gate support: if the backend has SIH_API_KEY set, it will
// 401 any /api/* request missing a matching X-API-Key header. We keep the
// key in localStorage (per-browser, never sent anywhere but this backend)
// and prompt for it once, lazily, the first time a request is rejected.
function _apiKeyHeaders(extra){
  const key = localStorage.getItem('sih_api_key');
  return key ? {...extra, 'X-API-Key': key} : (extra || {});
}
async function _withKeyRetry(doFetch){
  let r = await doFetch();
  if(r.status === 401){
    const key = window.prompt('This server requires an access key (ask whoever shared this link with you):');
    if(key){ localStorage.setItem('sih_api_key', key); r = await doFetch(); }
  }
  return r;
}

export async function jget(url){
  const r = await _withKeyRetry(()=> fetch(url, {headers: _apiKeyHeaders()}));
  const j = await r.json().catch(()=> ({}));
  if(!r.ok) throw Object.assign(new Error(j.error || r.statusText), {status:r.status, body:j});
  return j;
}
export async function jput(url, body){
  const r = await _withKeyRetry(()=> fetch(url, {method:'PUT', headers:_apiKeyHeaders({'Content-Type':'application/json'}), body: JSON.stringify(body)}));
  const j = await r.json().catch(()=> ({}));
  if(!r.ok) throw Object.assign(new Error(j.error || r.statusText), {status:r.status, body:j});
  return j;
}
export async function jpost(url, body){
  const r = await _withKeyRetry(()=> fetch(url, {method:'POST', headers: _apiKeyHeaders(body ? {'Content-Type':'application/json'} : undefined), body: body?JSON.stringify(body):undefined}));
  const j = await r.json().catch(()=> ({}));
  if(!r.ok) throw Object.assign(new Error(j.error || r.statusText), {status:r.status, body:j});
  return j;
}
export async function createJob(){ return jpost('/api/jobs'); }
export async function getJob(jobId){ return jget(`/api/jobs/${jobId}`); }
export async function getDataset(jobId, ds){ return jget(`/api/jobs/${jobId}/data/${ds}`); }
export async function putDataset(jobId, ds, rows){ return jput(`/api/jobs/${jobId}/data/${ds}`, {rows}); }
export async function getSchema(){ return jget('/api/schema'); }
export async function getSchemaOne(ds){ return jget(`/api/schema/${ds}`); }
export async function importDataset(jobId, ds, file){
  const fd=new FormData(); fd.append('file', file);
  const r=await _withKeyRetry(()=> fetch(`/api/jobs/${jobId}/import/${ds}`, {method:'POST', headers:_apiKeyHeaders(), body: fd}));
  const j=await r.json().catch(()=>({}));
  if(!r.ok) throw Object.assign(new Error(j.error || r.statusText), {status:r.status, body:j});
  return j;
}
export async function solveJob(jobId, timeLimit=60){
  const r=await _withKeyRetry(()=> fetch(`/api/solve/${jobId}?time_limit=${timeLimit}`, {method:'POST', headers:_apiKeyHeaders()}));
  const j=await r.json().catch(()=>({}));
  if(!r.ok) throw Object.assign(new Error(j.error || r.statusText), {status:r.status, body:j});
  return j;
}
export async function getStatus(jobId){ return jget(`/api/status/${jobId}`); }
export async function uploadFiles(files, fill){
  const fd = new FormData();
  for(const f of files) fd.append('files', f);
  const r = await _withKeyRetry(()=> fetch('/api/upload'+(fill?'?fill=true':''), {method:'POST', headers:_apiKeyHeaders(), body: fd}));
  const j = await r.json().catch(()=>({}));
  if(!r.ok) throw Object.assign(new Error(j.error || r.statusText), {status:r.status, body:j});
  return j;
}
export function templateUrl(ds){ return `/api/templates/${ds}`; }
export function allTemplatesUrl(){ return `/api/templates/all.zip`; }
