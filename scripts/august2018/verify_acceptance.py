"""Command-line acceptance guard used by Slurm job wrappers."""
from workflow_common import verify_acceptance
if __name__ == '__main__':
    verify_acceptance()
