# TRUBA Client GUI (Unofficial)

A **client-side GUI application** developed to manage **SSH + Slurm + (optional) X11 workflows**
in **TRUBA and similar Slurm-based HPC systems** from a single interface.

> ⚠️ This software is **NOT an official TRUBA tool**.  
> It is intended for use on **TRUBA or similar Slurm/SSH-based infrastructures**.

---

## Features

- SSH session management (client-side)
- Slurm job monitoring / basic job operations (via `squeue`, `sacct`, etc.)
- Remote file manager (copy/move/paste, drag & drop, resume, progress/cancel, undo-move)
- i18n: Turkish / English
- Centralized logging: `~/.truba_slurm_gui/app.log` (rotating)
- X11 runs **in the background**: `plink.exe -X` + `VcXsrv` (no dedicated X11 UI tab)

---

## Installation & Running

### Option A — Standalone (EXE)  ✅ Recommended

In this mode, **Python is NOT required**.

1) Download the latest package from **GitHub Releases** (Windows).  
2) (Optional: if you will use X11) Install **VcXsrv**.  
3) Obtain **PuTTY / plink**:
   - Place `plink.exe` next to the application **or**
   - Specify the `plink.exe` path in application settings (if available).
4) Run the EXE.

**External dependencies (NOT bundled in the EXE):**
- `plink.exe` (PuTTY)
- `VcXsrv` (required only for X11)
- Institutional firewall / antivirus policies (may require permission in some environments)

---

### Option B — From Source (Developer Mode)

**Requirements**
- Windows 10/11
- Python 3.10+ (recommended)
- (Optional) VcXsrv + plink.exe

**Setup**
```powershell
# In the project root directory
python -m venv .venv
.\.venv\Scripts\Activate.ps1

pip install -r requirements.txt
# or: pip install -e .
