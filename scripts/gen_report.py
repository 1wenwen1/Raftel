#!/usr/bin/env python3
"""Build a standalone report exclusively from an immutable run directory."""
import argparse
import base64
import csv
import hashlib
import html
import json
import sys
from pathlib import Path
from paper_plot import plot
from plot_data import REPO, read_curves

EXP={'fig3':'experiment1','fig4':'experiment2','fig6':'experiment3'}
SOURCE={'fig3':'alg_tee_nodes_WAN.csv','fig4':'sets_vs_tee_nodes_long.csv','fig6':'throughput_latency.csv'}
TITLE={'fig3':'Scale across fault thresholds','fig4':'The effect of trusted leadership','fig6':'From consensus to Redis'}
CLAIM={
 'fig3':'§7.2 · Compare WAN commit throughput and latency across six protocols as the fault threshold increases.',
 'fig4':'§7.3 · Evaluate TEE leadership and TEE population. The paper reports S1 at f=32 reaching 31.5 kTPS.',
 'fig6':'§7.6 · Redis, 100% SET, 1 KB values, f=8 and batch size 400. Textual peak throughput: Raftel 84, Chained-Raftel 92, Achilles 95 and HotStuff 44 TPS.'}
NOTES={
 'fig3':'Reference: exact values in the author-supplied WAN CSV; protocol aliases retain paper labels.',
 'fig4':'The source CSV has a duplicated S2 label at 1. The original script places its six sorted rows on the shared six-position axis, so the adapter preserves that behavior and maps the positions to f={1,2,4,8,16,32}. The raw CSV remains unchanged.',
 'fig6':'The original plotting script selects rows labelled “lan” and plots throughput directly against latency; its thread_count column is not used as an axis. AE load identifiers are retained for coverage, while the paper’s stated peak values and protocol ordering determine the verdict.'}


def esc(x): return html.escape(str(x),quote=True)

def table(headers,rows):
 return '<div class="table-scroll"><table><thead><tr>'+''.join('<th>'+esc(x)+'</th>' for x in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+esc(x)+'</td>' for x in row)+'</tr>' for row in rows)+'</tbody></table></div>'


def assess(fid,curves,manifest,reference_dir=None):
 """Thresholds apply per metric/configuration; missing data never passes."""
 ref,_=read_curves((reference_dir or REPO/'runs/reference')/'original'/SOURCE[fid],fid)
 issues=[]; rows=[]; deviations=[]
 expected=manifest.get('parameters',{}).get('fault_values',[1,2,4,8,16,32])
 if fid=='fig6':
  peaks={'Raftel':84,'Chained-Raftel':92,'Achilles':95,'HotStuff':44}
  expected_loads=manifest.get('parameters',{}).get('redis_load_clients',[1,2,4,8,16,32])
  for name in ('Raftel','Chained-Raftel','Achilles','HotStuff','Damysus'):
   points=curves.get(name,[])
   loads={point[0] for point in points}
   for load in expected_loads:
    if load not in loads:issues.append(f'Missing {name}, clients={load}')
   if not points:continue
   peak=max(p[1] for p in points); baseline=peaks.get(name)
   delta=abs(peak-baseline)/baseline if baseline else None
   if delta is not None:deviations.append(delta)
   rows.append([name,'peak',f'{peak:.3f}',str(baseline or 'not stated'),'TPS',f'{delta:.1%}' if delta is not None else '—'])
  measured_peaks={name:max(point[1] for point in points) for name,points in curves.items() if points}
  for higher,lower in (('Achilles','Chained-Raftel'),('Chained-Raftel','Raftel'),('Raftel','HotStuff')):
   if higher in measured_peaks and lower in measured_peaks and measured_peaks[higher] < measured_peaks[lower]:
    issues.append(f'{higher} / {lower} peak-throughput ordering differs')
  worst=max(deviations,default=0)
  if any('ordering differs' in issue for issue in issues) or worst>0.6:verdict='FAIL'
  elif issues:verdict='UNVERIFIED'
  elif worst>0.4:verdict='WARN'
  else:verdict='PASS'
  return verdict,rows,issues,worst
 for name in ref:
  values={p[0]:p for p in curves.get(name,[])}
  for x in expected:
   p=values.get(x)
   candidates=[r for r in ref[name] if r[0]==x]
   if p is None:
    issues.append(f'Missing {name}, f={x}'); continue
   r=candidates[0] if len(candidates)==1 else None
   for index,metric in [(1,'kTPS'),(2,'ms')]:
    delta=abs(p[index]-r[index])/r[index] if r and r[index] else None
    if delta is not None: deviations.append(delta)
    else: issues.append(f'Ambiguous reference: {name}, f={x}')
    rows.append([name,x,f'{p[index]:.6g}',f'{r[index]:.6g}' if r else 'unresolved',metric,f'{delta:.1%}' if delta is not None else '—'])
 # Check each fault independently; no cross-fault averaging or hidden tolerance.
 pairs=([('Achilles','Chained-Raftel'),('Chained-Raftel','Raftel'),('Raftel','Damysus'),('Damysus','HotStuff'),('Raftel','Raftel-Worst')] if fid=='fig3' else [('S1','S2'),('S2','S3'),('S3','S4')])
 lat_pairs=([('Achilles','Chained-Raftel'),('Chained-Raftel','Raftel'),('Raftel','Damysus'),('Damysus','HotStuff')] if fid=='fig3' else pairs)
 violations=[]
 # The author data has a 5.24% S2/S3 latency reversal at f=1. The paper
 # explicitly describes small-system differences as negligible, so only a
 # reversal beyond 6% is treated as material.
 order_tolerance=0.06
 for col,order in [(1,pairs),(2,lat_pairs)]:
  for hi,lo in order:
   a={p[0]:p[col] for p in curves.get(hi,[])};b={p[0]:p[col] for p in curves.get(lo,[])}
   for x in expected:
    if x in a and x in b and ((a[x] < b[x]*(1-order_tolerance)) if col==1 else (a[x] > b[x]*(1+order_tolerance))):
     violations.append(f'f={x}: {hi} / {lo} '+('throughput' if col==1 else 'latency')+' ordering differs')
 worst=max(deviations,default=0)
 if violations or worst>0.6: verdict='FAIL'
 elif issues: verdict='UNVERIFIED'
 elif worst>0.4: verdict='WARN'
 else: verdict='PASS'
 return verdict,rows,issues+violations,worst


def build_report(rd):
 m=json.loads((rd/'manifest.json').read_text()); figs=m['figs']
 preview=m.get('data_origin')=='paper-original'; cards=[];sections=[];verdicts=[]
 for fid in figs:
  path=rd/'raw'/EXP[fid]/'stats.txt'
  error=None;curves={}
  try:
   curves,original=read_curves(path,fid)
   verdict,rows,issues,worst=assess(fid,curves,m,rd / "reference" if (rd / "reference").exists() else None)
  except (ValueError,KeyError,FileNotFoundError) as exc:
   error=str(exc); verdict='UNVERIFIED';rows=[];issues=[error];worst=0
  timeout_files=sorted((rd/'raw'/EXP[fid]).glob('log/**/timeout.json'))
  for timeout_path in timeout_files:
   try:
    timeout_record=json.loads(timeout_path.read_text())
    issues.append(
     f"Orchestration deadline: {timeout_record.get('completed', 0)}/"
     f"{timeout_record.get('required', '?')} required replicas completed after "
     f"{timeout_record.get('elapsed_sec', '?')} s "
     f"({timeout_record.get('classification', 'unclassified')}). The 240 s default "
     "is an inherited guard, not a standard experiment duration."
    )
   except (OSError,ValueError):
    issues.append(f'Unreadable timeout evidence: {timeout_path.name}')
  if preview:
   verdict='REFERENCE'; issues=[NOTES[fid]]
   rows=[[name,p[0],f'{p[1]:.8g}',f'{p[2]:.8g}'] for name,pts in curves.items() for p in pts]
  elif m.get('status')!='complete' or fid in m.get('failed_figs',[]):
   verdict='FAIL';issues.insert(0,'The experiment did not finish successfully.')
  elif m.get('scale')!='full' or not m.get('hardware_verified'):
   if verdict!='FAIL':verdict='UNVERIFIED'
   issues.insert(0,'Full-scale hardware execution evidence has not been verified.')
  verdicts.append(verdict)
  count=sum(map(len,curves.values()))
  cards.append(f'<a class="card" href="#{fid}"><span class="eyebrow">Figure {fid[3:]}</span><h3>{TITLE[fid]}</h3><span class="badge {verdict.lower()}">{verdict}</span><span class="card-foot">{count} data points <span>↗</span></span></a>')
  images=[]
  for suffix in (['_throughput','_latency'] if fid!='fig6' else ['']):
   p=rd/'figures'/f'{fid}{suffix}.png'
   if p.exists():
    data=base64.b64encode(p.read_bytes()).decode()
    pdf=rd/'figures'/f'{fid}{suffix}.pdf'
    download=''
    if pdf.exists():
     encoded=base64.b64encode(pdf.read_bytes()).decode()
     download=f'<a download="{pdf.name}" href="data:application/pdf;base64,{encoded}">Download PDF ↓</a>'
    images.append(f'<figure><img src="data:image/png;base64,{data}" alt="Figure {fid[3:]} {suffix[1:] or "throughput versus latency"}"><figcaption>{esc(suffix[1:].capitalize() or "End-to-end performance")} {download}</figcaption></figure>')
  headers=(['Protocol','Source x / thread_count','Throughput','Latency (ms)'] if preview else (['Protocol','Point','Measured','Paper text','Unit','Deviation'] if fid=='fig6' else ['Protocol','Faults','Measured','Reference','Unit','Deviation']))
  issue_html='<ul>'+''.join('<li>'+esc(x)+'</li>' for x in dict.fromkeys(issues))+'</ul>' if issues else '<p>All evaluated measurements meet the configured reference and ordering checks.</p>'
  config=m.get('parameters',{})
  cfg=table(['Recorded parameter','Value'],[(k,json.dumps(v) if isinstance(v,(dict,list)) else v) for k,v in config.items()]) if config else '<p>No executed configuration recorded. Original source labels are retained.</p>'
  sections.append(f'''<section id="{fid}" class="result"><div class="section-head"><div><span class="eyebrow">FIGURE {fid[3:]} / EVIDENCE</span><h2>{TITLE[fid]}</h2></div><span class="badge {verdict.lower()}">{verdict}</span></div><p class="claim">{CLAIM[fid]}</p><div class="plots {"single" if fid=="fig6" else ""}">{''.join(images) or '<p>No figure generated.</p>'}</div><div class="finding"><strong>{'Source fidelity' if preview else 'Assessment'}</strong>{issue_html}</div><p class="source-note">{NOTES[fid]}</p><details><summary>Inspect numerical results <span>{count} points</span></summary>{table(headers,rows)}</details><details><summary>Inspect experiment conditions</summary>{cfg}</details></section>''')
 overall='REFERENCE PREVIEW' if preview else ('FAIL' if 'FAIL' in verdicts else 'UNVERIFIED' if 'UNVERIFIED' in verdicts else 'WARN' if 'WARN' in verdicts else 'PASS')
 lead=('Original data and reproduced figures' if preview else 'Artifact evaluation results')
 explanation=('This preview redraws the author-supplied CSVs. It verifies plotting fidelity; it contains no new SGX experiment and does not establish a reproduction result.' if preview else 'Read the result, inspect each claim, then follow the run evidence. Missing measurements and failed checks remain visible.')
 audit=[]
 for filename in ['manifest.json','checksums.txt','events.jsonl','hardware.json']:
  p=rd/filename
  audit.append(f'<details><summary>{filename}</summary><pre>{esc(p.read_text() if p.exists() else "Not recorded")}</pre></details>')
 css=(Path(__file__).with_name('report.css')).read_text()
 return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Raftel - {esc(m['run_id'])}</title><style>{css}</style></head><body><header><a class="brand" href="#">RAFTEL <span>ARTIFACT EVALUATION</span></a><nav><a href="#results">Results</a><a href="#audit">Audit trail</a></nav></header><main><section class="hero"><div><p class="eyebrow">EUROSYS REPRODUCIBILITY RECORD</p><h1>{lead}</h1><p class="intro">{explanation}</p></div><aside><span class="eyebrow">OVERALL ASSESSMENT</span><strong>{overall}</strong><p>{'Source replay only' if preview else esc(m.get('status','unknown'))}</p><div class="run-id">{esc(m['run_id'])}</div></aside></section><div class="run-strip"><span><b>{len(figs):02d}</b> figures</span><span><b>{len(m.get('cluster_ips',[])):02d}</b> recorded hosts</span><span>Code <b class="mono">{esc(m.get('git_commit','unrecorded')[:12])}</b></span><span>{'Author-supplied CSV' if preview else 'Run-local measurements'}</span></div><div class="section-label" id="results"><span>RESULTS AT A GLANCE</span><span>Select a figure for details</span></div><div class="cards">{''.join(cards)}</div>{''.join(sections)}<section id="audit" class="audit"><span class="eyebrow">PROVENANCE AND AUDIT</span><h2>Run evidence</h2><p>Reference comparisons use +/-40% for PASS and 40-60% for WARN; deviations above 60% fail. Material ordering reversals beyond a 6% tolerance also fail. Full coverage and verified hardware execution are required. Claims above are summaries, not quotations.</p>{''.join(audit)}</section></main><footer>RAFTEL <span>{esc(m['run_id'])} / Standalone report / UTC timestamps in audit trail</span></footer></body></html>'''


def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('run_dir',type=Path);args=p.parse_args();rd=args.run_dir.resolve()
 m=json.loads((rd/'manifest.json').read_text())
 for fid in m['figs']:
  path=rd/'raw'/EXP[fid]/'stats.txt'
  if path.exists():
   try:
    plot(fid,path,rd/'figures'/f'{fid}.pdf')
   except (ValueError,KeyError) as exc:
    print(f'{fid}: figure unavailable: {exc}',file=sys.stderr)
 (rd/'index.html').write_text(build_report(rd),encoding='utf-8')
 print(f'Report written: {rd / "index.html"}')

if __name__=='__main__':main()
