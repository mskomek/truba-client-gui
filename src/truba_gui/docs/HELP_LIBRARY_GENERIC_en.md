# Generic Slurm/HPC Help Library

This page is a portable playbook for Slurm-based clusters beyond TRUBA.

## 1) Environment adaptation checklist

- Login host name(s)
- SSH auth mode (key/password/MFA)
- Storage paths (home, scratch, project)
- Slurm partition/queue names
- Time/memory/CPU/GPU limits
- Module system in use (Environment Modules / Lmod)

## 2) Portable Slurm command set

- Submit: `sbatch job.sh`
- Queue status: `squeue -u $USER`
- Cancel: `scancel <JOBID>`
- Accounting: `sacct -j <JOBID>`
- Job details: `scontrol show job <JOBID>`
- Partition view: `sinfo`

## 3) Robust script template

```bash
#!/bin/bash
#SBATCH -J myjob
#SBATCH -p <partition>
#SBATCH -N 1
#SBATCH -n 1
#SBATCH -c 4
#SBATCH --mem=8G
#SBATCH -t 01:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

set -euo pipefail
module purge
module load <your-module>
./run.sh
```

## 4) X11 and GUI workloads

- Keep GUI/X11 flow separate from regular SSH command execution.
- With key-based auth, system `ssh -Y` is often enough.
- On Windows + password-based auth, `plink -X` can be more reliable.
- Always follow your institution's security/network policy.

## 5) Performance and reliability

- Use scratch/project areas for heavy data.
- Avoid inode explosions from massive tiny files.
- Plan checkpoint/restart for long runs.
- Name outputs with job id (`%j`) and keep logs in a dedicated folder.

## 6) Operational security

- Prefer strict host key verification where possible.
- Never store credentials in script/history/logs.
- Standardize permissions and shared project layout in team environments.

## References

- Slurm docs index: https://slurm.schedmd.com/documentation.html
- Sbatch: https://slurm.schedmd.com/sbatch.html
- Squeue: https://slurm.schedmd.com/squeue.html
- Scontrol: https://slurm.schedmd.com/scontrol.html
- Sacct: https://slurm.schedmd.com/sacct.html
