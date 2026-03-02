#!/bin/bash
#SBATCH -p orfoz
#SBATCH -C weka
#SBATCH -A USERNAME
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=55
#SBATCH --job-name=fluent_run
#SBATCH --output=fluent_output.txt
#SBATCH --error=fluent_error.txt
#SBATCH --time=00:30:00
#SBATCH --exclusive
#SBATCH --hint=nomultithread
