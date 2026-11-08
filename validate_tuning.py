"""Local synthetic-data integration check, never writes source projects."""
import json
from pathlib import Path
import urllib.request
import tuning_advisor
import workbench as w


def run(base):
    generated=tuning_advisor.demos(base)
    records={r['info']['tuning_scenario']:r for r in generated['records']};reports={}
    for scenario,record in records.items():
        config={**record['info']['snapshot'],'mapping':{'angle':'angle_deg','target':'target_deg','gyro':'gyro_dps','output':'control_out','integral':'i_out','derivative':'d_out'},'tolerance':.3,'parameters_confirmed':True,'feedback_verified':True}
        reports[scenario]=tuning_advisor.diagnose(base,record['id'],config)
    config=reports['oscillating']['config']
    comparison=tuning_advisor.compare(base,records['oscillating']['id'],records['damped']['id'],config)
    result={'records':{k:r['id'] for k,r in records.items()},'diagnoses':{k:{'metrics':r['metrics'],'proposal':r['proposal'],'codes':[f['code'] for f in r['findings']],'report_path':r['report_path']} for k,r in reports.items()},'comparison':comparison}
    path=Path(base).parent/'tuning-check.json';path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'report':str(path),'metrics':{k:r['metrics'] for k,r in reports.items()},'rms_reduction_percent':comparison['rms_reduction_percent']},indent=2))


if __name__=='__main__':run(w.STATE/'records')
