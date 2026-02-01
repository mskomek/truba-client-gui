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
