import asyncio
import contextlib
import os
import shlex
import signal
import subprocess
import shutil
from pathlib import Path
from typing import Optional

from .config import CONVERT_TIMEOUT
from .logger import setup_logger


log = setup_logger("converter")


def _find_output_pdf(input_path: str, output_dir: str) -> Optional[str]:
    base = os.path.splitext(os.path.basename(input_path))[0]
    # LibreOffice places output in output_dir with same base name and target extension
    for name in os.listdir(output_dir):
        if name.startswith(base) and name.lower().endswith(".pdf"):
            return os.path.join(output_dir, name)
    return None


async def run_libreoffice_convert(input_path: str, output_dir: str, convert_to: Optional[str]):
    os.makedirs(output_dir, exist_ok=True)
    # Create a per-job LibreOffice user profile directory to avoid global locks
    profile_dir = os.path.join(output_dir, "lo_profile")
    os.makedirs(profile_dir, exist_ok=True)
    profile_uri = Path(profile_dir).resolve().as_uri()  # e.g., file:///tmp/o2pdata/<job>/lo_profile
    # Build command
    # Example: soffice --headless --convert-to pdf --outdir /out file.docx
    args = [
        "soffice",
        "--headless",
        f"-env:UserInstallation={profile_uri}",
        "--norestore",
        "--nodefault",
        "--nolockcheck",
        "--nofirststartwizard",
        "--convert-to",
        convert_to or "pdf",
        "--outdir",
        output_dir,
        input_path,
    ]

    log.info(f"Executing: {' '.join(shlex.quote(a) for a in args)}")

    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,  # ensure soffice becomes a new session leader; its children join same group
    )

    stdout_text = ""
    stderr_text = ""
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=CONVERT_TIMEOUT)
        stdout_text = stdout.decode(errors="ignore") if stdout else ""
        stderr_text = stderr.decode(errors="ignore") if stderr else ""
        if stdout_text:
            log.info(f"LibreOffice stdout: {stdout_text}")
        if stderr_text:
            log.info(f"LibreOffice stderr: {stderr_text}")
    except asyncio.TimeoutError:
        log.warning("Conversion timeout. Terminating LibreOffice process group.")
        pgid = None
        with contextlib.suppress(ProcessLookupError):
            try:
                pgid = os.getpgid(proc.pid)
            except Exception:
                pgid = None
        # First try SIGTERM on the whole group
        with contextlib.suppress(ProcessLookupError):
            if pgid and hasattr(os, "killpg"):
                os.killpg(pgid, signal.SIGTERM)
            else:
                proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except asyncio.TimeoutError:
            log.warning("Process group did not terminate after SIGTERM; issuing SIGKILL.")
            with contextlib.suppress(ProcessLookupError):
                if pgid and hasattr(os, "killpg"):
                    os.killpg(pgid, signal.SIGKILL)
                else:
                    proc.kill()
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(proc.wait(), timeout=3)
        raise RuntimeError("Conversion timed out")
    finally:
        # Clean up the per-job user profile directory
        shutil.rmtree(profile_dir, ignore_errors=True)

    if proc.returncode != 0:
        # Include stderr/stdout details to surface real cause (e.g., bad filter, doc issues)
        details = (stderr_text or stdout_text or "Unknown error").strip()
        raise RuntimeError(f"LibreOffice failed (code {proc.returncode}): {details}")

    out = _find_output_pdf(input_path, output_dir)
    if not out:
        # Even when return code is 0, LibreOffice may log errors and produce no file.
        # Bubble up those details to the caller.
        details = (stderr_text or stdout_text or "No output produced").strip()
        raise RuntimeError(f"Output file not created: {details}")
    return out