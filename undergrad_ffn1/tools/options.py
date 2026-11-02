"""The four authorized switches; one shared source of variant metadata."""
import json
from pathlib import Path
KEYS=('itcm','host_continuous','small_x','small_bias')
def options(root):
    p=Path(root)/'config/optimizations.json'
    data=json.loads(p.read_text()) if p.exists() else {}
    assert not set(data)-set(KEYS), 'Unknown/unauthorized optimization'
    assert all(type(v) is bool for v in data.values())
    return {k:data.get(k,False) for k in KEYS}
def inventory(opts,scope='accelerator'):
    counts={'RAMSP128X16':4*int(opts['small_x'])+4*int(opts['small_bias']),
            'RAMSP1024X16':16+(0 if opts['small_bias'] else 2),
            'RAMSP4096X16':(0 if opts['small_x'] else 2)+(80 if scope=='soc' else 0)}
    return {k:v for k,v in counts.items() if v}
def configure(root,opts=None):
    root=Path(root);opts=options(root) if opts is None else opts
    (root/'config/optimizations.json').write_text(json.dumps(opts,indent=2)+'\n')
    text='// Generated from config/optimizations.json; no optional optimization.\n'
    # Host mode is a simulator argument; it must not change hardware/build hashes.
    for key in ('itcm','small_x','small_bias'):text+=f'`define KWT_{key.upper()} {int(opts[key])}\n'
    (root/'rtl/kwt_options.vh').write_text(text)
    (root/'config/optimization_config.tcl').write_text(
        '# Generated variant settings.\n'+''.join(f'set opt_{k} {int(opts[k])}\n' for k in KEYS))
    return opts
