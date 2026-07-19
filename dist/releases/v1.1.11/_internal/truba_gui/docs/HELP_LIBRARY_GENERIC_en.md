# Generic Slurm/HPC Help Library

This guide is designed to be portable across Slurm clusters beyond TRUBA.
Goal: start from zero and reach production-grade usage with correct resource requests, monitoring, debugging, and safer operations.

## 1) Before you start: identify your environment

Run these on first login:

```bash
hostname
whoami
sinfo
sacctmgr show qos format=Name,MaxWall,MaxTRES%50 2>/dev/null
```

Verify:

- Login host(s) and authentication mode (SSH key, password, MFA).
- Which partitions/queues are available to your account.
- Time, CPU, RAM, GPU limits (can differ by account/QOS).
- Storage areas: `home`, `scratch`, `project` (quota and purge policies).
- Module stack: `module avail`, `module spider`, `module list`.

## 2) Core Slurm commands (daily workflow)

- Submit a job: `sbatch job.sh`
- Queue status: `squeue -u $USER`
- Job details: `scontrol show job <JOBID>`
- Accounting/history: `sacct -j <JOBID> --format=JobID,JobName,Partition,State,Elapsed,MaxRSS,ExitCode`
- Cancel job: `scancel <JOBID>`
- Partition status: `sinfo -o "%P %a %l %D %C %m %f"`

Useful filters:

```bash
squeue -u $USER -t PD,R
squeue -u $USER --sort=-t,i
sacct -S now-1days -u $USER
```

## 3) First successful job: minimal example

`hello.slurm`:

```bash
#!/bin/bash
#SBATCH -J hello
#SBATCH -p <partition>
#SBATCH -N 1
#SBATCH -n 1
#SBATCH -c 1
#SBATCH --mem=1G
#SBATCH -t 00:05:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

set -euo pipefail
echo "Host: $(hostname)"
echo "Date: $(date)"
echo "User: $(whoami)"
```

Submit and monitor:

```bash
mkdir -p logs
sbatch hello.slurm
squeue -u $USER
```

## 4) Job script anatomy (request resources correctly)

Most important `#SBATCH` fields:

- `-p` partition
- `-t` wall time (`HH:MM:SS`)
- `-c` CPUs/threads per task
- `--mem` or `--mem-per-cpu`
- `-N` node count
- `-n` total task count (MPI)
- `--gres=gpu:<N>` GPU request (policy-dependent)

Impact of bad resource requests:

- Too low -> OOM/timeout failures.
- Too high -> long queue wait and poor utilization.

Rule of thumb: start small, observe, then scale.

## 5) Templates for CPU, MPI, and GPU jobs

CPU:

```bash
#!/bin/bash
#SBATCH -J cpu_job
#SBATCH -p <cpu_partition>
#SBATCH -c 8
#SBATCH --mem=16G
#SBATCH -t 02:00:00
#SBATCH -o logs/%x_%j.out

set -euo pipefail
module purge
module load python
python train.py
```

MPI:

```bash
#!/bin/bash
#SBATCH -J mpi_job
#SBATCH -p <partition>
#SBATCH -N 2
#SBATCH -n 64
#SBATCH -t 01:00:00
#SBATCH -o logs/%x_%j.out

set -euo pipefail
module purge
module load openmpi
srun ./mpi_app
```

GPU:

```bash
#!/bin/bash
#SBATCH -J gpu_job
#SBATCH -p <gpu_partition>
#SBATCH --gres=gpu:1
#SBATCH -c 8
#SBATCH --mem=32G
#SBATCH -t 04:00:00
#SBATCH -o logs/%x_%j.out

set -euo pipefail
module purge
module load cuda
nvidia-smi
python train_gpu.py
```

## 6) Interactive mode (debug and quick tests)

Quick shell on compute node:

```bash
srun -p <partition> -c 2 --mem=4G -t 00:30:00 --pty bash
```

Allocate first, test repeatedly:

```bash
salloc -p <partition> -c 4 --mem=8G -t 01:00:00
srun hostname
```

Note: do not keep interactive allocations idle.

## 7) Job arrays and dependencies (pipeline workflows)

Array jobs:

```bash
sbatch --array=1-100%10 array_job.slurm
```

- `1-100`: 100 tasks
- `%10`: max 10 running in parallel

Dependent jobs:

```bash
jid1=$(sbatch step1.slurm | awk '{print $4}')
sbatch --dependency=afterok:${jid1} step2.slurm
```

Common dependency modes:

- `afterok:<jobid>`: run if previous job succeeded
- `afterany:<jobid>`: run regardless of result
- `afternotok:<jobid>`: run if previous job failed

## 8) Debugging workflow

1. Check state with `squeue` (`PD`, `R`, `CG`).
2. Inspect pending reason via `scontrol show job <JOBID>`.
3. Read `logs/%x_%j.out` and `.err` files.
4. After completion, inspect `sacct -j <JOBID>` for `State`, `ExitCode`, `MaxRSS`.
5. If OOM, increase memory or reduce workload/batch size.
6. If timeout, increase wall time or split with checkpointing.

Common terminal states:

- `COMPLETED`: success
- `FAILED`: application/script failure
- `TIMEOUT`: exceeded wall time
- `OUT_OF_MEMORY`: memory exhausted
- `CANCELLED`: cancelled by user/system

## 9) Data layout and I/O performance

- Keep heavy temporary data on `scratch`.
- Avoid inode explosions from many tiny files:
  - archive batches (`tar`, `zip`),
  - perform bulk I/O where possible.
- Keep logs in a dedicated directory: `logs/<jobname>_<jobid>.out`.
- Include job id (`%j`) in output naming to avoid collisions.

## 10) Software environments (modules/conda/containers)

Modules:

```bash
module purge
module load gcc/XX python/3.X
```

Conda (if supported):

```bash
source ~/miniconda3/etc/profile.d/conda.sh
conda activate myenv
python app.py
```

Containers (Apptainer/Singularity, policy-dependent):

```bash
apptainer exec myimage.sif python app.py
```

## 11) Security and operational best practices

- Prefer strict SSH host key verification when possible.
- Never place passwords/tokens in scripts or logs.
- Standardize project permissions (`umask`, group ownership).
- Script repeated commands to reduce manual mistakes.

## 12) Frequent errors and quick fixes

- `Invalid account or account/partition combination`:
  - Wrong `-A`/`-p`; verify valid account-partition mapping.
- `QOSMaxWallDurationPerJobLimit`:
  - Wall time too high; reduce `-t` or request another QOS.
- `AssocMaxCpuPerJobLimit`:
  - CPU request too high; lower `-c/-n`.
- `OUT_OF_MEMORY`:
  - Increase `--mem`, reduce data footprint, add checkpointing.
- Job stays `PD` too long:
  - Use `Reason` in `scontrol show job` and tune request accordingly.

## 13) Pre-production checklist

- Does script include `set -euo pipefail`?
- Are log paths and naming (`%x_%j`) correct?
- Are resource requests close to real usage?
- Was a short pilot run executed on sample input?
- Is restart/checkpoint behavior defined?

## References

- Slurm docs index: https://slurm.schedmd.com/documentation.html
- sbatch: https://slurm.schedmd.com/sbatch.html
- squeue: https://slurm.schedmd.com/squeue.html
- scontrol: https://slurm.schedmd.com/scontrol.html
- sacct: https://slurm.schedmd.com/sacct.html
- srun: https://slurm.schedmd.com/srun.html
- job array: https://slurm.schedmd.com/job_array.html
