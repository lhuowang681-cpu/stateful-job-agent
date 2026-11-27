import json, os, pathlib, subprocess, sys, importlib.metadata
base = pathlib.Path(__file__).resolve().parent
repo = base / 'agent-backend-service'
for key in list(os.environ):
    if key.startswith(('JOB_AGENT_', 'QWEN', 'DEEPSEEK', 'LLM_')) or any(x in key for x in ('API_KEY','ACCESS_TOKEN','AUTH_TOKEN','SECRET')):
        os.environ.pop(key, None)
os.environ.update(PYTHONPATH=str(repo)+':'+str(repo/'src'), PYTEST_DISABLE_PLUGIN_AUTOLOAD='1', OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1', PGCONNECT_TIMEOUT='2', TMPDIR=str(base/'tmp'))
(base/'tmp').mkdir(exist_ok=True)
name = sys.argv[1]
command = [sys.executable, '-u', '-m', 'pytest', '-vv', '--tb=short', '-o', 'faulthandler_timeout=30', '--basetemp='+str(base/('test-'+name)), '--junitxml='+str(base/(name+'.xml')), *sys.argv[2:]]
(base/(name+'-command.json')).write_text(json.dumps(command, indent=2))
with (base/(name+'.log')).open('w') as log:
    completed = subprocess.run(command, cwd=repo, env=os.environ, stdout=log, stderr=subprocess.STDOUT)
(base/(name+'.exit')).write_text(str(completed.returncode))
print(name, 'exit', completed.returncode, flush=True)
