# TRUBA Client GUI — Quick Start

> This application is an **unofficial, client-side GUI** that simplifies **SSH + Slurm + (when needed) X11** workflows on **TRUBA** and other **Slurm-based HPC systems**.

## First run in 5 minutes

1. **Connect**
   - Enter the server (hostname), username, and (if needed) key/password.
2. **Copy your files**
   - Copy your working files **Home → Scratch** (or into your project directory).
3. **Run a Slurm job**
   - From the terminal, submit with: `sbatch job.sh`
4. **Monitor**
   - Track the job state in the job list (PENDING/RUNNING/COMPLETED).
5. **Use X11 only if needed**
   - X11 is required for **GUI applications** (e.g., MATLAB/ParaView). It is not needed for terminal-only jobs.

## Notes
- **This is not an official TRUBA tool.**
- If something goes wrong, check the log file: `~/.truba_slurm_gui/app.log`

👉 For detailed usage and common commands, click the **❓ Help** icon in the main window.
