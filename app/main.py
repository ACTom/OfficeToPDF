import asyncio
import os
import time
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Form, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from .auth import require_api_key
from .config import DATA_DIR, CLEANUP_AFTER_SECONDS, LOG_DIR, CONVERT_TIMEOUT, MAX_CONCURRENCY
from .logger import setup_logger
from .models import ConvertRequest, ConvertResponse, StatusResponse, JobStatus, SystemStatusResponse
from .queue import ConvertQueue
from .converter import run_libreoffice_convert


log = setup_logger("app")
app = FastAPI(title="OfficeToPDF API", description="Convert Office documents to PDF using LibreOffice")

queue = ConvertQueue()


async def save_upload_to(path: str, upload: UploadFile):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # Stream save to reduce memory
    with open(path, "wb") as f:
        while True:
            chunk = await upload.read(1024 * 1024)
            if not chunk:
                break
            f.write(chunk)
    await upload.close()


async def runner(job):
    # job has infile_path, outdir, convert_to
    return await run_libreoffice_convert(job.infile_path, job.outdir, job.convert_to)


@app.post("/convert/sync", response_model=ConvertResponse, dependencies=[Depends(require_api_key)])
async def convert_sync(file: UploadFile = File(...), convert_to: Optional[str] = Form(None)):
    # Create a job context but execute synchronously while honoring concurrency limit
    job = queue.create_job(infile_path="", convert_to=convert_to)
    infile = os.path.join(job.outdir, "input", file.filename)
    await save_upload_to(infile, file)
    job.infile_path = infile

    # Use semaphore to limit concurrency
    async with queue.sem:
        job.status = JobStatus.running
        log.info(f"[sync] job={job.id} start convert_to={convert_to} file={file.filename}")
        try:
            outfile = await queue._attempt_with_retries(job, runner)
            job.outfile_path = outfile
            job.status = JobStatus.done
            log.info(f"[sync] job={job.id} done outfile={outfile}")
        except Exception as e:
            job.status = JobStatus.failed
            job.message = str(e)
            log.error(f"[sync] job={job.id} failed: {e}")
            raise HTTPException(status_code=500, detail=f"Conversion failed: {e}")

    download_url = f"/download/{job.id}"
    return ConvertResponse(job_id=job.id, status=job.status, download_url=download_url)


@app.post("/convert/async", response_model=ConvertResponse, dependencies=[Depends(require_api_key)])
async def convert_async(file: UploadFile = File(...), convert_to: Optional[str] = Form(None)):
    job = queue.create_job(infile_path="", convert_to=convert_to)
    infile = os.path.join(job.outdir, "input", file.filename)
    await save_upload_to(infile, file)
    job.infile_path = infile

    log.info(f"[async] job={job.id} queued convert_to={convert_to} file={file.filename}")
    queue.enqueue(job)
    asyncio.create_task(queue.run_job(job, runner))
    return ConvertResponse(job_id=job.id, status=job.status)


@app.get("/status/{job_id}", response_model=StatusResponse, dependencies=[Depends(require_api_key)])
async def status(job_id: str):
    job = queue.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    download_url = f"/download/{job.id}" if job.status == JobStatus.done and job.outfile_path else None
    waiting = None
    if job.status == JobStatus.queued:
        waiting = queue.waiting_count(job.id)
    return StatusResponse(
        job_id=job.id,
        status=job.status,
        message=job.message,
        download_url=download_url,
        waiting_count=waiting,
        retries=job.retries,
    )


@app.get("/download/{job_id}", dependencies=[Depends(require_api_key)])
async def download(job_id: str):
    job = queue.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != JobStatus.done or not job.outfile_path:
        raise HTTPException(status_code=400, detail="File not ready")
    log.info(f"[download] job={job.id} path={job.outfile_path}")
    return FileResponse(job.outfile_path, filename=os.path.basename(job.outfile_path))


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/system/status", response_model=SystemStatusResponse, dependencies=[Depends(require_api_key)])
async def system_status():
    c = queue.counters()
    now = asyncio.get_event_loop().time()
    uptime = int(now - queue.started_at)
    # disk usage stats
    def disk_stats(path: str):
        try:
            st = os.statvfs(path)
            total = st.f_frsize * st.f_blocks
            free = st.f_frsize * st.f_bavail
            used = total - free
            return used, free
        except Exception:
            return 0, 0
    return SystemStatusResponse(
        status="ok",
        uptime_seconds=uptime,
        convert_timeout=CONVERT_TIMEOUT,
        max_concurrency=MAX_CONCURRENCY,
        cleanup_after_seconds=CLEANUP_AFTER_SECONDS,
        total_jobs=c["total"],
        queue_length=c["queue_len"],
        running_jobs=c["running"],
        done_jobs=c["done"],
        failed_jobs=c["failed"],
        cpu_cores=os.cpu_count() or 1,
        data_dir_used_bytes=disk_stats(DATA_DIR)[0],
        data_dir_free_bytes=disk_stats(DATA_DIR)[1],
        log_dir_used_bytes=disk_stats(LOG_DIR)[0],
        log_dir_free_bytes=disk_stats(LOG_DIR)[1],
    )


async def cleanup_task():
    while True:
        now = time.time()
        try:
            for entry in os.listdir(DATA_DIR):
                dir_path = os.path.join(DATA_DIR, entry)
                if not os.path.isdir(dir_path):
                    continue
                try:
                    mtime = os.path.getmtime(dir_path)
                    if now - mtime > CLEANUP_AFTER_SECONDS:
                        log.info(f"Cleaning {dir_path}")
                        # also drop from job map if present
                        try:
                            queue.cleanup_job(entry)
                        except Exception:
                            pass
                        # ensure dir removed even if not tracked
                        import shutil
                        shutil.rmtree(dir_path, ignore_errors=True)
                except FileNotFoundError:
                    pass
        except Exception as e:
            log.error(f"Cleanup cycle error: {e}")
        # Periodically evict old job records to avoid memory buildup
        try:
            queue.evict_old_jobs()
        except Exception:
            pass
        await asyncio.sleep(60)


@app.on_event("startup")
async def on_startup():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(LOG_DIR, exist_ok=True)
    asyncio.create_task(cleanup_task())


# Serve a simple test UI
@app.get("/ui", response_class=HTMLResponse)
async def ui():
    return HTMLResponse(
        """
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <title>OfficeToPDF API 测试</title>
  <style>
    body { font-family: sans-serif; margin: 2rem; }
    .card { border: 1px solid #ddd; padding: 1rem; margin-bottom: 1rem; }
    input[type=text] { width: 360px; }
    pre { background: #f7f7f7; padding: 0.5rem; }
  </style>
  <script>
    async function callSync(){
      const file = document.getElementById('file').files[0];
      const convert_to = document.getElementById('convert_to').value;
      const apikey = document.getElementById('apikey').value;
      const fd = new FormData();
      fd.append('file', file);
      if(convert_to) fd.append('convert_to', convert_to);
      const res = await fetch('/convert/sync', { method: 'POST', headers: { 'X-API-Key': apikey }, body: fd });
      const json = await res.json();
      document.getElementById('sync_result').textContent = JSON.stringify(json, null, 2);
    }
    async function callAsync(){
      const file = document.getElementById('file_async').files[0];
      const convert_to = document.getElementById('convert_to_async').value;
      const apikey = document.getElementById('apikey').value;
      const fd = new FormData();
      fd.append('file', file);
      if(convert_to) fd.append('convert_to', convert_to);
      const res = await fetch('/convert/async', { method: 'POST', headers: { 'X-API-Key': apikey }, body: fd });
      const json = await res.json();
      document.getElementById('async_result').textContent = JSON.stringify(json, null, 2);
      if(json.job_id){ document.getElementById('job_id').value = json.job_id; }
    }
    async function checkStatus(){
      const job_id = document.getElementById('job_id').value;
      const apikey = document.getElementById('apikey').value;
      const res = await fetch(`/status/${job_id}`, { headers: { 'X-API-Key': apikey } });
      const json = await res.json();
      document.getElementById('status_result').textContent = JSON.stringify(json, null, 2);
    }
    function download(){
      const job_id = document.getElementById('job_id').value;
      const apikey = document.getElementById('apikey').value;
      fetch(`/download/${job_id}`, { headers: { 'X-API-Key': apikey } }).then(async (res)=>{
        if(!res.ok){
          const text = await res.text();
          alert('下载失败: '+text);
          return;
        }
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `output-${job_id}.pdf`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
      })
    }
    async function checkSystem(){
      const apikey = document.getElementById('apikey').value;
      const res = await fetch('/system/status', { headers: { 'X-API-Key': apikey } });
      const json = await res.json();
      document.getElementById('sys_result').textContent = JSON.stringify(json, null, 2);
    }
  </script>
</head>
<body>
  <h1>OfficeToPDF API 测试</h1>
  <div class="card">
    <label>API Key: <input id="apikey" type="text" placeholder="在.env或环境变量设置APIKEY" /></label>
  </div>

  <div class="card">
    <h3>系统状态</h3>
    <button onclick="checkSystem()">查看系统状态</button>
    <pre id="sys_result"></pre>
  </div>

  <div class="card">
    <h3>同步转换</h3>
    <input type="file" id="file" />
    <label>convert_to: <input type="text" id="convert_to" placeholder="例如: pdf:writer_pdf_Export" /></label>
    <button onclick="callSync()">转换</button>
    <pre id="sync_result"></pre>
  </div>

  <div class="card">
    <h3>异步转换</h3>
    <input type="file" id="file_async" />
    <label>convert_to: <input type="text" id="convert_to_async" placeholder="例如: pdf:writer_pdf_Export" /></label>
    <button onclick="callAsync()">提交任务</button>
    <pre id="async_result"></pre>
  </div>

  <div class="card">
    <h3>查询与下载</h3>
    <label>Job ID: <input id="job_id" type="text" /></label>
    <button onclick="checkStatus()">查询状态</button>
    <button onclick="download()">下载PDF</button>
    <pre id="status_result"></pre>
  </div>

  <p>API 文档可通过 <a href="/docs">/docs</a> 查看。</p>
</body>
</html>
        """
    )

# Simple request logging middleware
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    duration = (time.time() - start) * 1000
    try:
        log.info(
            f"{request.method} {request.url.path} -> {response.status_code} {duration:.1f}ms"
        )
    except Exception:
        pass
    return response