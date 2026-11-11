"""Validate strict-window clock edges and exact timing/profile equivalence."""
import re
from prepare import CASES,gate_paths
def parse(name,text,windows):
 design=next(d for d in CASES if d['name']==name)
 expected_gates={label:bits for label,path,bits in gate_paths(design)}
 summaries={};activity={}
 for task,roots,gates in re.findall(r'^CG_WINDOW task=(\d+) root_edges=(\d+) gates=(\d+)\s*$',text,re.M):
  task=int(task)
  if task in summaries:raise ValueError('Duplicate CG window')
  summaries[task]=dict(root_edges=int(roots),gates=int(gates))
 for task,gate,edges,expected,roots,bits in re.findall(r'^CG_ACTIVITY task=(\d+) gate=(\w+) edges=(\d+) expected=(\d+) root_edges=(\d+) bits=(\d+)\s*$',text,re.M):
  task=int(task);group=activity.setdefault(task,{})
  if gate in group:raise ValueError('Duplicate gate activity')
  group[gate]=dict(edges=int(edges),expected=int(expected),root_edges=int(roots),bits=int(bits))
 ids={w['task'] for w in windows}
 if set(summaries)!=ids or set(activity)-ids:raise ValueError('CG task coverage mismatch')
 result=[]
 for w in windows:
  task=w['task'];summary=summaries[task];group=activity.get(task,{})
  if summary['root_edges']!=w['end_cycle']-w['begin_cycle']+1:raise ValueError('CG root-window edge mismatch')
  if summary['gates']!=len(expected_gates) or set(group)!=set(expected_gates):raise ValueError('Missing/extra clock gates')
  for name,record in group.items():
   if record['bits']!=expected_gates[name] or record['root_edges']!=summary['root_edges']:raise ValueError('Gate sink/window mismatch')
   if record['edges']!=record['expected'] or not 0<record['edges']<record['root_edges']:raise ValueError('Gating ineffective/incorrect')
  before=sum(expected_gates.values())*summary['root_edges']
  after=sum(r['bits']*r['edges'] for r in group.values())
  result.append(dict(task=task,root_edges=summary['root_edges'],gates=group,
   ungated_register_bit_edges=before,gated_register_bit_edges=after,
   suppressed_register_clock_edges_percent=100*(1-after/before) if before else 0))
 return result

def equal(reference,actual,label):
 if len(reference['windows'])!=len(actual['windows']):raise ValueError(label+': task count changed')
 for a,b in zip(reference['windows'],actual['windows']):
  if a['task']!=b['task'] or a['duration_fs']!=b['duration_fs']:raise ValueError(label+': strict per-task cycle change')
 def canonical(p):return {str(k):{str(i):v for i,v in row.items()} for k,row in p.items()}
 if canonical(reference['profiles'])!=canonical(actual['profiles']):raise ValueError(label+': performance counters changed')
