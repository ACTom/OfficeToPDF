import asyncio
import os
import shutil
import signal
import uuid
from dataclasses import dataclass, field
from typing import Dict, Optional, List

from .config import (
    DATA_DIR,
    CONVERT_TIMEOUT,
    MAX_CONCURRENCY,
    MAX_RETRIES,
    MAX_QUEUE_SIZE,
    JOB_RECORD_TTL_SECONDS,
)
from .logger import setup_logger
from .models import JobStatus


log = setup_logger("queue")


@dataclass
class Job:
    id: str
    infile_path: str
    outdir: str
    convert_to: Optional[str]
    status: JobStatus = JobStatus.queued
    message: Optional[str] = None
    outfile_path: Optional[str] = None
    retries: int = 0
    max_retries: int = MAX_RETRIES
    finished_at: Optional[float] = None


class ConvertQueue:
    def __init__(self):
        self.sem = asyncio.Semaphore(MAX_CONCURRENCY)
        self.jobs: Dict[str, Job] = {}
        self.pending: List[str] = []  # job ids in queued order
        self.started_at = asyncio.get_event_loop().time()

    def create_job(self, infile_path: str, convert_to: Optional[str]) -> Job:
        job_id = str(uuid.uuid4())
        outdir = os.path.join(DATA_DIR, job_id)
        os.makedirs(outdir, exist_ok=True)
        job = Job(
            id=job_id,
            infile_path=infile_path,
            outdir=outdir,
            convert_to=convert_to,
        )
        self.jobs[job_id] = job
        log.info(f"Job created {job_id} for {infile_path} -> {convert_to}")
        return job

    def get(self, job_id: str) -> Optional[Job]:
        return self.jobs.get(job_id)

    def enqueue(self, job: Job):
        # Only enqueue async jobs that will wait on semaphore
        if MAX_QUEUE_SIZE and len(self.pending) >= MAX_QUEUE_SIZE:
            job.status = JobStatus.failed
            job.message = "Queue is full"
            log.error(f"Job {job.id} rejected: queue full ({MAX_QUEUE_SIZE})")
            return
        if job.id not in self.pending:
            self.pending.append(job.id)
            job.status = JobStatus.queued
            log.info(f"Job {job.id} enqueued")

    def waiting_count(self, job_id: str) -> Optional[int]:
        try:
            idx = self.pending.index(job_id)
            return idx
        except ValueError:
            return None

    def counters(self):
        total = len(self.jobs)
        queue_len = len([j for j in self.jobs.values() if j.status == JobStatus.queued])
        running = len([j for j in self.jobs.values() if j.status == JobStatus.running])
        done = len([j for j in self.jobs.values() if j.status == JobStatus.done])
        failed = len([j for j in self.jobs.values() if j.status == JobStatus.failed])
        return {
            "total": total,
            "queue_len": queue_len,
            "running": running,
            "done": done,
            "failed": failed,
        }

    async def run_job(self, job: Job, runner):
        async with self.sem:
            # When we obtain a slot, remove from pending and mark running
            if job.id in self.pending:
                try:
                    self.pending.remove(job.id)
                except ValueError:
                    pass
            job.status = JobStatus.running
            log.info(f"Job {job.id} started")
            try:
                job.outfile_path = await self._attempt_with_retries(job, runner)
                job.status = JobStatus.done
                job.finished_at = asyncio.get_event_loop().time()
                log.info(f"Job {job.id} finished: {job.outfile_path}")
            except Exception as e:
                job.status = JobStatus.failed
                job.message = str(e)
                job.finished_at = asyncio.get_event_loop().time()
                log.error(f"Job {job.id} failed: {e}")

    async def _attempt_with_retries(self, job: Job, runner):
        last_err: Optional[Exception] = None
        for attempt in range(job.max_retries + 1):
            job.retries = attempt
            try:
                return await self._run_once(job, runner)
            except Exception as e:
                last_err = e
                log.warning(f"Job {job.id} attempt {attempt} failed: {e}")
                await asyncio.sleep(0.2)
        raise last_err if last_err else RuntimeError("Unknown conversion failure")

    async def _run_once(self, job: Job, runner):
        # runner should return output file path
        return await runner(job)

    def cleanup_job(self, job_id: str):
        job = self.jobs.get(job_id)
        if not job:
            return
        try:
            shutil.rmtree(job.outdir, ignore_errors=True)
            # Mark job as cleaned but keep record for status queries
            job.outfile_path = None
            job.status = JobStatus.cleaned
            job.message = "Cleaned up after retention period"
            job.finished_at = job.finished_at or asyncio.get_event_loop().time()
            if job_id in self.pending:
                try:
                    self.pending.remove(job_id)
                except ValueError:
                    pass
            log.info(f"Job {job_id} cleaned up and marked as cleaned")
        except Exception as e:
            log.error(f"Cleanup error {job_id}: {e}")

    def evict_old_jobs(self):
        # Remove job records to prevent unbounded memory growth
        if JOB_RECORD_TTL_SECONDS <= 0:
            return
        now = asyncio.get_event_loop().time()
        to_delete: List[str] = []
        for jid, job in self.jobs.items():
            if job.status in {JobStatus.done, JobStatus.failed, JobStatus.cleaned}:
                if job.finished_at is not None and (now - job.finished_at) > JOB_RECORD_TTL_SECONDS:
                    to_delete.append(jid)
        for jid in to_delete:
            try:
                del self.jobs[jid]
                log.info(f"Evicted job record {jid} after TTL")
            except Exception:
                pass