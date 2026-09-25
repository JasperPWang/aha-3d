"""Real tiny subprocess regression for resumability; no models, Blender or GPU."""
import copy
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from aha3d.io import digest, read, write
from aha3d.workflow import human_runner as runner


FIXTURE = r'''
import json,os,subprocess,sys,time
from pathlib import Path
out,params,inp,audit,deps=map(Path,sys.argv[1:6])
p=json.loads(params.read_text());mode=p.get('mode','normal')
with audit.open('a') as f:f.write(p['name']+'\n')
print('launched',p['name'],flush=True)
if mode=='fail':
 print('deliberate stage failure',flush=True);raise SystemExit(23)
if mode=='fail_once':
 marker=Path(p['marker'])
 if not marker.exists():marker.write_text('first attempt');raise SystemExit(17)
if mode=='sleep':
 Path(p['marker']).write_text(str(os.getpid()));time.sleep(30)
if mode=='background':
 child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'])
 Path(p['marker']).write_text(str(child.pid));raise SystemExit(0)
if mode=='missing':raise SystemExit(0)
if mode=='mutate':inp.write_text('input modified by bad stage')
if mode=='directory':
 assert not out.exists(),'Runner must not create solver output directory'
 out.mkdir(parents=True);(out/'file.txt').write_text('directory payload');raise SystemExit(0)
value={'params':p,'input':json.loads(inp.read_text()) if inp.is_file() and mode!='mutate' else None}
if mode=='gate':value={'allow_render':p['allow']}
if mode=='report':value={'dependency_states':{k:v['status'] for k,v in json.loads(deps.read_text()).items()}}
out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(value))
'''


class HumanRunner(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='human runner test ')
        self.root = Path(self.tmp.name); self.run = self.root/'run'
        self.config = self.root/'config.json'; self.audit = self.root/'launches.txt'
        write(self.root/'source.json', {'source': 'frozen pixels'})
        self.spec = dict(schema_version=1, id='tiny_human_experiment', root=str(self.root), stages=[])

    def tearDown(self):
        self.tmp.cleanup()

    def stage(self, name, needs=(), mode='normal', **params):
        code = self.root/f'{name}.py'; code.write_text(FIXTURE)
        inputs = {'body': {'stage': needs[0], 'output': 'artifact'}} if needs else {'body': {'path':'source.json'}}
        return dict(id=name, needs=list(needs),
            argv=['{python}', str(code), '{output:artifact}', '{params_file}', '{input:body}', str(self.audit), '{dependency_status_file}'],
            inputs=inputs, code=[{'path':str(code)}], outputs={'artifact':'new/out.json'},
            params=dict(name=name, mode=mode, **params))

    def execute(self, **kw):
        write(self.config, self.spec)
        return runner.execute(self.config, self.run, **kw)

    def counts(self):
        lines=self.audit.read_text().splitlines() if self.audit.exists() else []
        return {x:lines.count(x) for x in set(lines)}

    def output(self, result, stage, name='artifact'):
        return self.run/result['stages'][stage]['outputs'][name]['path']

    def test_contact_params_and_code_only_invalidate_descendants(self):
        self.spec['stages']=[self.stage('pi3x'),self.stage('gvhmr',['pi3x']),
            self.stage('contact',['gvhmr'],shift=.01),self.stage('inspect',['contact'])]
        first=self.execute(); before=self.output(first,'gvhmr').read_bytes()
        second=self.execute()
        self.assertTrue(all(x['reused'] for x in second['stages'].values()))
        self.assertEqual(self.counts(),dict(pi3x=1,gvhmr=1,contact=1,inspect=1))
        self.spec['stages'][2]['params']['shift']=.02
        third=self.execute()
        self.assertEqual(self.counts(),dict(pi3x=1,gvhmr=1,contact=2,inspect=2))
        self.assertEqual(self.output(third,'gvhmr').read_bytes(),before)
        with (self.root/'contact.py').open('a') as f:f.write('\n# implementation revision\n')
        fourth=self.execute()
        self.assertEqual(self.counts(),dict(pi3x=1,gvhmr=1,contact=3,inspect=3))
        self.assertEqual(fourth['stages']['pi3x']['attempt'],1)

    def test_missing_corrupt_outputs_and_extra_directory_file_never_reuse(self):
        a=self.stage('body',mode='directory');a['outputs']={'artifact':'solver/body'}
        self.spec['stages']=[a]
        first=self.execute();out=self.output(first,'body')
        (out/'extra.txt').write_text('unrecorded corruption')
        second=self.execute()
        self.assertEqual(second['stages']['body']['attempt'],2)
        self.assertTrue((out/'extra.txt').exists())
        self.assertTrue(second['stages']['body']['invalid_cache'])
        self.output(second,'body').joinpath('file.txt').unlink()
        third=self.execute()
        self.assertEqual(third['stages']['body']['attempt'],3)
        self.assertEqual(self.counts(),{'body':3})

    def test_old_intact_attempt_can_be_reused_after_config_revert(self):
        self.spec['stages']=[self.stage('contact',value=1)]
        first=self.execute();p=self.output(first,'contact')
        self.spec['stages'][0]['params']['value']=2;self.execute()
        self.spec['stages'][0]['params']['value']=1;third=self.execute()
        self.assertTrue(third['stages']['contact']['reused'])
        self.assertEqual(self.output(third,'contact'),p)
        self.assertEqual(self.counts(),{'contact':2})

    def test_failure_keeps_log_and_partial_attempt_resume_skips_ancestors(self):
        self.spec['stages']=[self.stage('gvhmr'),self.stage('contact',['gvhmr'],mode='fail_once',marker=str(self.root/'once')),
            self.stage('render',['contact'])]
        first=self.execute()
        self.assertEqual(first['status'],'failed');self.assertEqual(first['stages']['contact']['exit_code'],17)
        failed_log=self.run/first['stages']['contact']['log']
        self.assertIn('RUNNER_FAILURE',failed_log.read_text())
        self.assertEqual(first['stages']['render']['status'],'blocked_dependency')
        second=self.execute()
        self.assertEqual(second['status'],'completed')
        self.assertEqual(self.counts(),dict(gvhmr=1,contact=2,render=1))
        self.assertTrue(failed_log.is_file())

    def test_numeric_rejection_skips_render_and_runs_settled_report(self):
        inspection=self.stage('inspect',mode='gate',allow=False)
        render=self.stage('render',['inspect'])
        render['gates']=[dict(stage='inspect',output='artifact',pointer='/allow_render',equals=True)]
        report=self.stage('report',['inspect','render'],mode='report')
        report['needs_policy']='settled';report['inputs']={};report['argv'][4]='unused'
        self.spec['stages']=[inspection,render,report]
        result=self.execute()
        self.assertEqual(result['status'],'completed_with_gate_skips')
        self.assertEqual(result['stages']['render']['status'],'skipped_gate')
        self.assertNotIn('render',self.counts())
        self.assertEqual(read(self.output(result,'report'))['dependency_states']['render'],'skipped_gate')
        self.assertFalse((self.run/'stages/render').exists())
        self.spec['stages'][0]['params']['allow']=True
        result=self.execute();self.assertEqual(result['status'],'completed')
        self.assertEqual(self.counts()['render'],1)

    def test_inspection_and_report_continue_after_failed_branch(self):
        failed=self.stage('bad',mode='fail')
        report=self.stage('report',['bad'],mode='report');report['needs_policy']='settled'
        report['inputs']={};report['argv'][4]='unused'
        independent=self.stage('independent')
        self.spec['stages']=[failed,report,independent]
        result=self.execute()
        self.assertEqual(result['status'],'failed')
        self.assertEqual(result['stages']['report']['status'],'completed')
        self.assertEqual(result['stages']['independent']['status'],'completed')
        self.assertEqual(read(self.output(result,'report'))['dependency_states'],{'bad':'failed'})

    def test_pinned_inputs_and_code_reject_changed_files_before_launch(self):
        stage=self.stage('infer');stage['inputs']['body']['sha256']=digest(self.root/'source.json')
        stage['code'][0]['sha256']=digest(self.root/'infer.py')
        self.spec['stages']=[stage];self.execute()
        (self.root/'source.json').write_text('wrong actor')
        result=self.execute();self.assertEqual(result['stages']['infer']['status'],'failed')
        self.assertIn('Pinned SHA256 mismatch',(self.run/result['stages']['infer']['log']).read_text())
        self.assertEqual(self.counts(),{'infer':1})
        write(self.root/'source.json',{'source':'frozen pixels'})
        (self.root/'infer.py').write_text('raise SystemExit(0)')
        result=self.execute();self.assertEqual(result['status'],'failed')
        self.assertEqual(self.counts(),{'infer':1})

    def test_input_mutation_and_missing_output_do_not_create_valid_cache(self):
        for mode in ('mutate','missing'):
            with self.subTest(mode=mode):
                write(self.root/'source.json',{'source':'frozen pixels'})
                self.spec['stages']=[self.stage(mode,mode=mode)]
                result=self.execute()
                self.assertEqual(result['status'],'failed')
                self.assertNotIn('outputs',result['stages'][mode])

    def test_literal_shell_metacharacters_and_fresh_nested_output(self):
        literal='$(touch SHOULD_NOT_EXIST); `touch ALSO_NOT`; spaces'
        self.spec['stages']=[self.stage('literal',text=literal)]
        self.spec['stages'][0]['argv'].append(literal)
        result=self.execute()
        self.assertEqual(result['status'],'completed')
        self.assertEqual(read(self.output(result,'literal'))['params']['text'],literal)
        self.assertFalse((self.root/'SHOULD_NOT_EXIST').exists());self.assertFalse((self.root/'ALSO_NOT').exists())

    def test_config_cycles_unknown_refs_output_escape_fail_without_stages(self):
        a=self.stage('a');b=self.stage('b',['a'])
        bad=[]
        cyc=copy.deepcopy([a,b]);cyc[0]['needs']=['b'];bad.append(cyc)
        escape=copy.deepcopy([a]);escape[0]['outputs']['artifact']='../bad';bad.append(escape)
        overlap=copy.deepcopy([a]);overlap[0]['outputs']={'one':'folder','two':'folder/x'};bad.append(overlap)
        unknown=copy.deepcopy([a,b]);unknown[1]['inputs']['body']['output']='missing';bad.append(unknown)
        field=copy.deepcopy([a]);field[0]['arg']='bad';bad.append(field)
        for stages in bad:
            with self.subTest(stages=stages):
                self.spec['stages']=stages
                with self.assertRaises(ValueError):self.execute()
        self.assertFalse(self.audit.exists())

    def test_timeout_stops_process_and_keeps_failed_receipt(self):
        a=self.stage('sleep',mode='sleep',marker=str(self.root/'started'));a['timeout_seconds']=.15
        self.spec['stages']=[a];result=self.execute()
        self.assertEqual(result['status'],'failed')
        self.assertIn('TimeoutExpired',result['stages']['sleep']['reason'])
        self.assertFalse((self.run/'.execute.lock').exists())

    def test_real_concurrent_run_rejected_and_sigterm_resume(self):
        a=self.stage('sleep',mode='sleep',marker=str(self.root/'started'))
        self.spec['stages']=[a];write(self.config,self.spec)
        env=os.environ.copy();env['PYTHONPATH']=str(Path(runner.__file__).resolve().parents[2])
        proc=subprocess.Popen([sys.executable,'-m','aha3d.workflow.human_runner','execute',str(self.config),'--run-dir',str(self.run)],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            deadline=time.monotonic()+8
            while not (self.root/'started').exists() and time.monotonic()<deadline:
                if proc.poll() is not None:self.fail(proc.communicate())
                time.sleep(.02)
            self.assertTrue((self.root/'started').exists())
            with self.assertRaisesRegex(ValueError,'Already owned'):
                runner.execute(self.config,self.run)
            proc.send_signal(signal.SIGTERM);stdout,stderr=proc.communicate(timeout=8)
            self.assertEqual(proc.returncode,130,(stdout,stderr))
            result=read(self.run/'run.json');self.assertEqual(result['status'],'interrupted')
            self.assertEqual(result['stages']['sleep']['status'],'interrupted')
            self.assertFalse((self.run/'.execute.lock').exists())
            pid=int((self.root/'started').read_text())
            self.assertEqual(result['stages']['sleep']['process_group_id'],pid)
            with self.assertRaises(ProcessLookupError):os.kill(pid,0)
            self.spec['stages'][0]['params']['mode']='normal'
            resumed=self.execute();self.assertEqual(resumed['status'],'completed')
            self.assertEqual(resumed['stages']['sleep']['attempt'],2)
        finally:
            if proc.poll() is None:proc.kill();proc.wait()

    def test_background_writer_is_terminated_and_never_marked_completed(self):
        self.spec['stages']=[self.stage('background',mode='background',marker=str(self.root/'child'))]
        result=self.execute()
        self.assertEqual(result['status'],'failed')
        self.assertIn('background processes',result['stages']['background']['reason'])
        pid=int((self.root/'child').read_text())
        for _ in range(50):
            stat=Path(f'/proc/{pid}/stat')
            if not stat.exists() or stat.read_text().split()[2]=='Z':break
            time.sleep(.02)
        else:self.fail('Background process remained alive')

    def test_corrupt_manifest_and_stale_lock_require_explicit_recovery(self):
        self.spec['stages']=[self.stage('body')];self.execute()
        (self.run/'run.json').write_text('not json')
        with self.assertRaises(ValueError):self.execute()
        (self.run/'.execute.lock').mkdir()
        write(self.run/'.execute.lock/owner.json',{'pid':999999999,'host':'other-host'})
        with self.assertRaisesRegex(ValueError,'Already owned'):self.execute()
        self.assertTrue((self.run/'.execute.lock/owner.json').exists())

    def test_sigkill_retains_lock_and_records_exact_child_for_manual_recovery(self):
        self.spec['stages']=[self.stage('sleep',mode='sleep',marker=str(self.root/'started'))]
        write(self.config,self.spec)
        env=os.environ.copy();env['PYTHONPATH']=str(Path(runner.__file__).resolve().parents[2])
        proc=subprocess.Popen([sys.executable,'-m','aha3d.workflow.human_runner','execute',str(self.config),'--run-dir',str(self.run)],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        child=None
        try:
            deadline=time.monotonic()+8
            while not (self.root/'started').exists() and time.monotonic()<deadline:time.sleep(.02)
            self.assertTrue((self.root/'started').exists())
            child=int((self.root/'started').read_text())
            proc.kill();proc.wait(timeout=5)
            result=read(self.run/'run.json')
            self.assertEqual(result['stages']['sleep']['process_group_id'],child)
            self.assertTrue((self.run/'.execute.lock/owner.json').exists())
            with self.assertRaisesRegex(ValueError,'Already owned'):runner.execute(self.config,self.run)
        finally:
            if proc.poll() is None:proc.kill();proc.wait()
            if child is not None:
                try:os.killpg(child,signal.SIGKILL)
                except ProcessLookupError:pass


if __name__=='__main__':unittest.main()
