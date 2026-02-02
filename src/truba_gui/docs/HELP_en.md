# TRUBA Client GUI — Help

> **Unofficial client-side GUI** to simplify **SSH / Slurm / X11 workflows** on the **TRUBA HPC system** or any similar **Slurm-based HPC**.
>
> This software is **not an official TRUBA tool**.

---

## For first-time users

The mental model is simple:

- **SSH**: connect to the HPC remotely.
- **Slurm**: submits and runs your jobs on allocated resources.
- **X11**: only needed for **graphical** apps (MATLAB, ParaView, etc.).

### Your first job in 5 minutes

1. **Connect**
2. Copy input/script/data to **Scratch / project directory**
3. Create a simple `job.sh`
4. Submit:
   - `sbatch job.sh`
5. Check status:
   - `squeue -u $USER`

### When do I need X11?

- ✅ MATLAB, ParaView, other GUI applications
- ❌ Not needed for terminal workloads (Python scripts, batch CFD, training jobs)

### If something doesn’t work

- The GUI should not freeze; errors are written to the **log file**.
- Log path:
  - `~/.truba_slurm_gui/app.log`
- When asking for help, sharing this log makes troubleshooting much faster.

---

## What does it do?

- Manage SSH connections (client-side)
- Monitor Slurm jobs (queue, status, outputs)
- Manage remote files (copy/move/rename/delete, upload/download, resume, queue)
- Run X11 apps via **PuTTY plink** + **VcXsrv** in the background (no dedicated X11 tab)

---

## Install & run

### Standalone (EXE)

- **Python is not required**.
- When needed, the app can **download 3rd‑party tools with your consent**:
  - `plink.exe` (PuTTY) → `~/.truba_slurm_gui/third_party/putty/`
  - VcXsrv runtime (for X11) → `~/.truba_slurm_gui/third_party/vcxsrv/`

Steps:
1. Download and run the EXE package.
2. If you use X11/GUI apps, the app will ask permission to download VcXsrv/plink when required.
3. Connect → manage files → submit/monitor jobs.

Note:
- Some corporate networks block downloads; in that case, point the app to an existing `plink.exe` or use an approved PuTTY installation.


### From source

Requirements:

- Python 3.10+

Install & run:

- `pip install -r requirements.txt`
- `python -m truba_gui`

---

## TRUBA notes

- Prefer **Scratch** for large data and long runs.
- Scratch may be periodically cleaned by the HPC administrators; keep important outputs in Home or project storage.

---

## Other Slurm-based HPC systems

This app is not TRUBA-locked. It should work if:

- SSH access is available
- Slurm commands exist (`sbatch`, `squeue`, `sacct`, ...)
- X11 forwarding is allowed (only if you need GUI apps)

If your site prints banners/warnings that affect command output, parsing may degrade, but the app should fail **softly** and log the details.

---

## Security

- Passwords/tokens are never written to command history or UI.
- The app uses a rotating log file:
  - `~/.truba_slurm_gui/app.log`

---

## Limitations

- Windows-first UX
- Slurm output parsing may vary by site customization
- X11 performance depends heavily on network quality

---

## Support

- Please attach the log file when opening an issue:
  - `~/.truba_slurm_gui/app.log`

---

## SLURM Quick Commands

### Submit a job

- `sbatch job.sh`
- `sbatch --time=01:00:00 --mem=8G --cpus-per-task=4 job.sh`

### List jobs

- `squeue -u $USER`
- `squeue -j <JOBID>`

### Cancel jobs

- `scancel <JOBID>`
- `scancel -u $USER`  *(careful: cancels all your jobs)*

### Partitions / resources

- `sinfo`
- `sinfo -o "%P %a %l %D %t"`

### Accounting / history

- `sacct -u $USER --format=JobID,JobName,State,Elapsed,MaxRSS,AllocTRES`
- `sacct -j <JOBID> --format=JobID,State,ExitCode,Elapsed,MaxRSS`

### Inspect a job

- `scontrol show job <JOBID>`

### Interactive allocation (debug / GUI prep)

- `salloc -N 1 -n 1 -c 4 --mem=8G -t 01:00:00`
- `srun --pty bash`
