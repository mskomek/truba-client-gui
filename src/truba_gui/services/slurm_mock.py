from .slurm_base import SlurmBackend

class MockSlurmBackend(SlurmBackend):
    def squeue(self, user: str) -> str:
        return (
            "JOBID PARTITION     NAME     USER ST       TIME  NODES NODELIST(REASON)\n"
            "12345   short   testjob   {u}  R       0:12      1 node001\n"
            "12346   short   coolrun   {u}  PD      0:00      1 (Resources)\n"
        ).format(u=user or "user")

    def sbatch(self, script_path: str) -> str:
        return f"Submitted batch job 12347 (mock) for {script_path}"

    def scancel(self, job_id: str) -> str:
        return f"Cancelled job {job_id} (mock)"

    def sacct(self, user: str) -> str:
        return (
            "JobID           JobName    State    Elapsed   MaxRSS\n"
            "12345           testjob    COMPLETED 00:10:12 1024M\n"
            "12346           coolrun    PENDING   00:00:00 0K\n"
        )

    def scontrol_show_job(self, job_id: str) -> str:
        return (
            f"JobId={job_id} JobName=mock_job UserId=mock(1000) "
            "JobState=RUNNING Partition=short Nodes=1"
        )

    def lssrv(self) -> str:
        return (
            "SERVER     STATE     CPU  MEMORY\n"
            "node001    available  32   128G\n"
            "node002    busy       64   256G\n"
        )

    def active_job_ids(self, user: str) -> str:
        return "12345\n12346\n"

    def job_state(self, job_id: str) -> str:
        return "COMPLETED\n"
