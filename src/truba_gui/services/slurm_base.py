from abc import ABC, abstractmethod

class SlurmBackend(ABC):
    @abstractmethod
    def squeue(self, user: str) -> str: ...

    @abstractmethod
    def sbatch(self, script_path: str) -> str: ...

    @abstractmethod
    def scancel(self, job_id: str) -> str: ...
