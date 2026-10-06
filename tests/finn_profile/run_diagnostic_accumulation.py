"""Link the stress harness against an actual built gcclassic HEMCO library.

Execute in a compute allocation with the build compiler environment loaded.
Inputs are captured source/layer fields (see the investigation capture receipt).
Original mode reports baseline drift; repaired mode additionally enforces the
unchanged2e-6 closure gate and opt-in invariance assertions in the harness.
"""
from pathlib import Path
import argparse, hashlib, json, shlex, subprocess

ap = argparse.ArgumentParser(description=__doc__)
ap.add_argument('--build-dir', required=True, type=Path)
ap.add_argument('--inputs', required=True, type=Path)
ap.add_argument('--output-dir', required=True, type=Path)
ap.add_argument('--mode', choices=['original', 'repaired'], default='repaired')
a = ap.parse_args()
b, source, inputs = a.build_dir.resolve(), Path(__file__).with_name('test_diagnostic_accumulation.F90').resolve(), a.inputs.resolve()
assert not a.output_dir.exists(); a.output_dir.mkdir(parents=True)
out = a.output_dir.resolve()
command = shlex.split((b/'src/CMakeFiles/gcclassic.dir/link.txt').read_text())
assert sum(x.endswith('main.F90.o') for x in command) == 1
command = [str(source) if x.endswith('main.F90.o') else x for x in command]
binary = out/'test_diagnostic_accumulation'
command[command.index('-o')+1] = str(binary)
command += ['-I'+str(b/'src/HEMCO/mod'), '-ffree-line-length-none', '-fcheck=all', '-g']
if a.mode == 'repaired': command += ['-DNEW_HP']
with (out/'build.log').open('w') as log:
    subprocess.run(command, cwd=b/'src', stdout=log, stderr=subprocess.STDOUT, check=True)
with (out/'run.log').open('w') as log:
    subprocess.run([str(binary), str(inputs)], stdout=log, stderr=subprocess.STDOUT, check=True)
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
(out/'RECEIPT.json').write_text(json.dumps({'status': 'COMPLETE', 'mode': a.mode,
    'build_dir': str(b), 'link_command': command, 'inputs': str(inputs),
    'input_sha256': sha(inputs), 'harness_sha256': sha(source), 'binary_sha256': sha(binary),
    'scope': 'Actual diagnostic-library stress test; not reconstruction of historical timesteps.'}, indent=2)+'\n')
print('COMPLETE', a.mode)
