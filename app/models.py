from enum import Enum
from typing import Optional
from pydantic import BaseModel


class JobStatus(str, Enum):
    queued = "queued"
    running = "running"
    done = "done"
    failed = "failed"
    cleaned = "cleaned"


class ConvertRequest(BaseModel):
    convert_to: Optional[str] = None  # e.g. "pdf:writer_pdf_Export"


class ConvertResponse(BaseModel):
    job_id: str
    status: JobStatus
    download_url: Optional[str] = None
    message: Optional[str] = None


class StatusResponse(BaseModel):
    job_id: str
    status: JobStatus
    message: Optional[str] = None
    download_url: Optional[str] = None
    waiting_count: Optional[int] = None
    retries: Optional[int] = None


class SystemStatusResponse(BaseModel):
    status: str
    uptime_seconds: float
    convert_timeout: int
    max_concurrency: int
    cleanup_after_seconds: int
    total_jobs: int
    queue_length: int
    running_jobs: int
    done_jobs: int
    failed_jobs: int
    cpu_cores: int
    data_dir_used_bytes: int
    data_dir_free_bytes: int
    log_dir_used_bytes: int
    log_dir_free_bytes: int