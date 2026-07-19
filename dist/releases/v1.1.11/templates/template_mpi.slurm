#!/bin/bash
#SBATCH -p orfoz
#SBATCH --nodes=2
#SBATCH --ntasks=64
#SBATCH --cpus-per-task=1
#SBATCH --time=01:00:00
#SBATCH --job-name=mpi_job
#SBATCH --output=logs/%x_%j.out
#SBATCH --error=logs/%x_%j.err

set -euo pipefail
module purge
# module load openmpi
# srun ./mpi_app
