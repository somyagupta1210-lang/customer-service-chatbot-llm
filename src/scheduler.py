"""Minute-driven scheduler. It is deterministic and safe to call from Task Scheduler/cron."""
from __future__ import annotations
from datetime import datetime,timedelta
import json,uuid
from .config import settings
from .storage import get_connection,record_audit,utc_now
from .update_pipeline import UpdatePipeline
class UpdateScheduler:
    def __init__(self,pipeline=None): self.pipeline=pipeline or UpdatePipeline()
    def schedule_for(self,when=None):
        when=when or datetime.now(); job_id=uuid.uuid4().hex[:12]
        with get_connection() as conn: conn.execute("INSERT INTO jobs(job_id,created_at,status,attempt,next_retry_at,details_json) VALUES(?,?,?,?,?,?)",(job_id,utc_now(),"scheduled",0,when.isoformat(),"{}"))
        record_audit("schedule_update","success",details={"job_id":job_id,"run_at":when.isoformat()}); return job_id
    def retry_schedule(self,failed_at=None): return self.pipeline.retry_times(failed_at)
    def process_due(self,now=None,health_ok=True):
        now=now or datetime.now(); results=[]
        with get_connection() as conn: jobs=conn.execute("SELECT * FROM jobs WHERE status IN ('scheduled','retry_waiting') AND next_retry_at<=? ORDER BY created_at",(now.isoformat(),)).fetchall()
        for job in jobs:
            # A pending health window is checked on the next scheduler tick.
            pending=settings.runtime_dir/"health_pending.json"
            if pending.exists():
                data=json.loads(pending.read_text()); deadline=datetime.fromisoformat(data["deadline"])
                if now>=deadline:
                    result=self.pipeline.complete_health_check(data["version"],health_ok)
                    status="completed" if result["status"] in {"healthy","rolled_back"} else "failed"
                    attempt=int(job["attempt"])+1; next_retry=None
                else:
                    # The release is still inside its five-minute health window.
                    # Do not count this as a failed update or consume a retry.
                    result={"status":"health_window_open","version":data["version"],"deadline":data["deadline"]}
                    status="scheduled"; attempt=int(job["attempt"]); next_retry=job["next_retry_at"]
            else:
                result=self.pipeline.run(now=now,health_ok=health_ok)
                status="completed" if result["status"] in {"active","healthy","unchanged","rolled_back"} else "failed"
                attempt=int(job["attempt"])+1; next_retry=None
            if status=="failed" and attempt<=len(settings.retry_delays):
                next_retry=(now+timedelta(minutes=settings.retry_delays[attempt-1])).isoformat(); status="retry_waiting"
            with get_connection() as conn: conn.execute("UPDATE jobs SET status=?,attempt=?,next_retry_at=?,details_json=? WHERE job_id=?",(status,attempt,next_retry,json.dumps(result,default=str),job["job_id"]))
            results.append({"job_id":job["job_id"],"attempt":attempt,"next_retry_at":next_retry,"result":result})
        return {"processed":len(results),"results":results}
