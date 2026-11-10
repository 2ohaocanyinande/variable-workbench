import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import common_modules
import telemetry
import tuning_advisor as advisor


class TuningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.base=Path(cls.temp.name)
        cls.records={r['info']['tuning_scenario']:r for r in advisor.demos(cls.base)['records']}

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def config(self,scenario='oscillating'):
        snapshot=self.records[scenario]['info']['snapshot']
        return {**snapshot,'mapping':{'angle':'angle_deg','target':'target_deg','gyro':'gyro_dps','output':'control_out','integral':'i_out','derivative':'d_out'},
                'tolerance':.3,'parameters_confirmed':True,'feedback_verified':True}

    def diagnose(self,scenario,**changes):
        config=self.config(scenario);config.update(changes)
        return advisor.diagnose(self.base,self.records[scenario]['id'],config)

    def test_persistent_frequency_and_single_gain_trial(self):
        r=self.diagnose('oscillating')
        self.assertIn('oscillation',[f['code'] for f in r['findings']])
        self.assertAlmostEqual(r['metrics']['frequency_hz'],1.2,delta=.03)
        self.assertEqual(r['proposal']['parameter'],'kp');self.assertEqual(r['proposal']['after'],14.25)
        self.assertEqual(r['source'],'simulation');self.assertTrue(Path(r['report_path']).is_file())

    def test_damped_curve_no_trial(self):
        r=self.diagnose('damped');self.assertIsNone(r['proposal'])
        self.assertLess(r['metrics']['tail_rms_error'],.02)
        self.assertIsNotNone(r['metrics']['settling_seconds'])

    def test_derivative_noise(self):
        r=self.diagnose('noise');self.assertIn('derivative_noise',[f['code'] for f in r['findings']]);self.assertIsNone(r['proposal'])

    def test_windup(self):
        r=self.diagnose('windup');self.assertIn('windup',[f['code'] for f in r['findings']]);self.assertEqual(r['metrics']['saturation_fraction'],1);self.assertIsNone(r['proposal'])

    def test_unconfirmed_no_numeric_trial(self):
        for condition in ['parameters_confirmed','feedback_verified']:
            self.assertIsNone(self.diagnose('oscillating',**{condition:False})['proposal'])

    def test_angle_wrap_blocks_trial(self):
        with tempfile.TemporaryDirectory() as folder:
            import shutil
            identifier=self.records['oscillating']['id'];source=telemetry.record_path(self.base,identifier);target=telemetry.record_path(folder,identifier)
            shutil.copytree(source,target)
            rows=[json.loads(line) for line in (target/'samples.jsonl').read_text().splitlines()]
            rows[300]['values']['angle_deg']=359
            (target/'samples.jsonl').write_text('\n'.join(json.dumps(row) for row in rows),encoding='utf-8')
            report=advisor.diagnose(folder,identifier,self.config())
            self.assertIsNone(report['proposal']);self.assertTrue(any('半圈' in warning for warning in report['warnings']))

    def test_no_output_or_period_mismatch_no_trial(self):
        c=self.config();c['mapping']['output']=''
        self.assertIsNone(advisor.diagnose(self.base,self.records['oscillating']['id'],c)['proposal'])
        self.assertIsNone(self.diagnose('oscillating',sample_dt=.1)['proposal'])

    def test_compare_and_identical_rejected(self):
        a,b=self.records['oscillating']['id'],self.records['damped']['id']
        r=advisor.compare(self.base,a,b,self.config());self.assertGreater(r['rms_reduction_percent'],99)
        self.assertEqual(r['snapshots']['before']['pid']['kp'],15)
        self.assertEqual(r['snapshots']['after']['pid']['kp'],14.25)
        with self.assertRaises(ValueError):advisor.compare(self.base,a,a,self.config())

    def test_unknown_mapping_and_invalid_config(self):
        for config in [None,[],{'mapping':{'angle':'missing','target':'target_deg'}}]:
            with self.assertRaises(ValueError):advisor.diagnose(self.base,self.records['oscillating']['id'],config)

    def test_short_or_bad_time_blocks_trial(self):
        with tempfile.TemporaryDirectory() as folder:
            recorder=telemetry.Recorder(folder);r=recorder.start('simulation')
            for i in range(30):recorder.sample(i*.02,{'angle_deg':i,'target_deg':0})
            recorder.stop()
            with self.assertRaises(ValueError):advisor.diagnose(folder,r['id'],{**self.config(),'mapping':{'angle':'angle_deg','target':'target_deg'}})
            data=copy.deepcopy(self.records['oscillating']);origin=telemetry.record_path(self.base,data['id'])
            target=telemetry.record_path(folder,data['id']);target.mkdir()
            (target/'meta.json').write_text(json.dumps(data),encoding='utf-8')
            rows=[json.loads(line) for line in (origin/'samples.jsonl').read_text().splitlines()];rows[250]['t']=rows[249]['t']
            (target/'samples.jsonl').write_text('\n'.join(json.dumps(row) for row in rows),encoding='utf-8')
            report=advisor.diagnose(folder,data['id'],self.config());self.assertIsNone(report['proposal']);self.assertGreater(report['metrics']['time_anomalies'],0)

    def test_draft_is_traceable_and_preserves_original(self):
        import workbench as w
        old=w.STATE,w.SCAN,w.RECORDER
        try:
            with tempfile.TemporaryDirectory() as directory:
                root=Path(directory);project=root/'project';project.mkdir();source=project/'main.c';source.write_text('float kp=15;\n')
                sha=hashlib.sha256(source.read_bytes()).hexdigest();w.STATE=root/'state';w.STATE.mkdir()
                import shutil
                shutil.copytree(telemetry.record_path(self.base,self.records['oscillating']['id']),w.STATE/'records'/self.records['oscillating']['id'])
                w.RECORDER=telemetry.Recorder(w.STATE/'records')
                loop={'id':'test-loop','symbol':'balance','gains':{'kp':{'field':'kp','sources':[]},'ki':{'field':'ki','sources':[]}},'evidence':[]}
                w.SCAN={'root':str(project),'project_hash':'a'*64,'files':{'main.c':sha},'pid':{'loops':[loop],'draft':{'loops':[{'id':'test-loop','name':'角度环','category':'角度环','gains':{'ki':{'value':2,'source_index':None}}}]}}}
                config=self.config();config['loop_id']='test-loop';snapshot=w.tuning_snapshot(config)
                report=advisor.diagnose(w.STATE/'records',self.records['oscillating']['id'],config,snapshot)
                request={'record_id':report['record_id'],'diagnosis_id':report['id']}
                result=w.tuning_to_draft(request)
                self.assertEqual(result['draft']['loops'][0]['gains']['kp'],{'value':14.25,'source_index':None})
                self.assertEqual(result['draft']['loops'][0]['gains']['ki'],{'value':2,'source_index':None})
                self.assertEqual(result['draft']['diagnostic_origin']['source'],'simulation')
                self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),sha)
                source.write_text('float kp=16;\n')
                with self.assertRaises(ValueError):w.tuning_to_draft(request)
        finally:w.STATE,w.SCAN,w.RECORDER=old


class NineAxisTests(unittest.TestCase):
    def hint(self,code,family='MODULE'):
        endpoint={'family':family,'handle':'LSM6DSR','channel':'','path':'IMU963RA.c','calls':[],'evidence_ids':['s']}
        return common_modules.hints(endpoint,{'s':{'code':code,'path':'IMU963RA.c','line':1}})

    def test_header_is_not_sampling(self):
        code='#define LSM6DSR_ID 1\n#define QMC5883L_ADDR 0x0d\nvoid IMU963RA_GetAccel(void);\nvoid IMU963RA_GetGyro(void);'
        hint=self.hint(code)[0];self.assertIn('九轴',hint['module_model'])
        self.assertIn('初检片段仅见寄存器定义',hint['components'][2]['state'])
        self.assertNotIn('实现',hint['components'][0]['state'])

    def test_read_entry_and_pwm_not_promoted(self):
        code='#define LSM6DSR_ID 1\n#define QMC5883L_ADDR 0x0d\nvoid IMU963RA_GetMag(void) { qmc5883l_read(); }'
        self.assertIn('初检片段有读取相关标识',self.hint(code)[0]['components'][2]['state'])
        self.assertEqual(self.hint(code,'PWM'),[])


if __name__=='__main__':unittest.main()
