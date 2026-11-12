"""Validate the isolated source set; optionally elaborate and simulate with ModelSim."""
from pathlib import Path
import argparse, hashlib, json, os, re, shutil, subprocess, sys, tempfile
ROOT=Path(__file__).resolve().parents[1]

def sources(technology=False):
    return [ROOT / p.strip() for p in (ROOT/'sources.f').read_text().splitlines() if p.strip()] + [ROOT/('dc' if technology else 'sim')/'kwt_sram16.sv']

def run(command,cwd):
    result=subprocess.run([str(x) for x in command],cwd=cwd,text=True,errors="replace",stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    out=ROOT/'output';out.mkdir(exist_ok=True)
    (out/'last-command.log').write_text(result.stdout,encoding='utf-8')
    if result.returncode:
        report=json.loads((out/'checks.json').read_text()) if (out/'checks.json').exists() else {}
        report['simulation']='BLOCKED_LICENSE' if 'license' in result.stdout.lower() else 'FAILED'
        (out/'checks.json').write_text(json.dumps(report,indent=2)+'\n')
        raise RuntimeError(f"Command failed ({result.returncode}): {command}\n{result.stdout}")
    return result.stdout

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--simulate',action='store_true');parser.add_argument('--modelsim-bin',default='')
    args=parser.parse_args();files=sources();report={'source_files':len(files),'top':'kwt_encoder_dc_top'}
    text='\n'.join(p.read_text() for p in files)
    forbidden=r'\b(?:z100_\w*|DSP48E1|RAMB\w*|IBUF\w*|BUFG\w*|processing_system7\w*)\b|ram_style|use_dsp'
    assert not re.search(forbidden,text), 'FPGA-specific dependency in isolated source set'
    assert all(p.is_file() for p in files)
    assert '.PROJECTION_K4(2)' in text and '.ATTENTION_K16(2)' in text and '.GELU_CYCLES(2)' in text
    for item in json.loads((ROOT/'provenance.json').read_text())['files']:
        actual=hashlib.sha256((ROOT/item['destination']).read_bytes().replace(b'\r\n',b'\n')).hexdigest()
        assert actual==item['extracted_sha256'], 'Unexpected change to extracted source: '+item['destination']
    report['source_contract']='PASS'
    try:
        import pyslang
    except ImportError:
        if (ROOT/'output/python').is_dir():sys.path.insert(0,str(ROOT/'output/python'))
        try: import pyslang
        except ImportError:pyslang=None
    if pyslang:
        from pyslang.driver import Driver
        os.chdir(ROOT)
        def elaborate(paths,top):
            driver=Driver();driver.addStandardArgs()
            command='slang --single-unit --timescale=1ns/1ps --top '+top+' -Irtl '+' '.join(p.relative_to(ROOT).as_posix() for p in paths)
            if not driver.parseCommandLine(command) or not driver.processOptions():raise RuntimeError('slang options failed')
            if not driver.parseAllSources():raise RuntimeError('SystemVerilog parsing failed')
            compilation=driver.createCompilation()
            driver.reportCompilation(compilation,True)
            if not driver.reportDiagnostics(True) or compilation.hasIssuedErrors:raise RuntimeError('SystemVerilog elaboration failed')
        elaborate(files,'kwt_encoder_dc_top')
        elaborate(files+[ROOT/'tests/tb_mmio.sv'],'tb_mmio')
        elaborate(sources(True)+[ROOT/'tests/macro_models.sv'],'kwt_encoder_dc_top')
        elaborate([ROOT/'dc/kwt_sram16.sv',ROOT/'tests/macro_models.sv',ROOT/'tests/tb_memories.sv'],'tb_memories')
        report['elaboration']='PASS: portable top, MMIO test, native macro top and memory test'
    else:report['elaboration']='NOT_RUN: install pyslang or use --simulate with ModelSim'
    out=ROOT/'output';out.mkdir(exist_ok=True)
    report['simulation']='NOT_RUN'
    (out/'checks.json').write_text(json.dumps(report,indent=2)+'\n')
    if args.simulate:
        # Older ModelSim cannot open libraries under Windows Unicode paths.
        stage=Path(tempfile.gettempdir())/'kwt-encoder-dc-validation'
        stage.mkdir(parents=True,exist_ok=True)
        for folder in ['rtl','sim','dc','tests']:
            (stage/folder).mkdir(exist_ok=True)
            for source in (ROOT/folder).glob('*.s*'):
                shutil.copy2(source,stage/folder/source.name)
            for source in (ROOT/folder).glob('*.vh'):
                shutil.copy2(source,stage/folder/source.name)
        work=stage/'build';work.mkdir(exist_ok=True)
        def exe(name):return str(Path(args.modelsim_bin)/(name+('.exe' if os.name=='nt' else ''))) if args.modelsim_bin else name
        run([exe('vlib'),'work'],work)
        inputs=[str(Path('..')/p.relative_to(ROOT)) for p in files]
        run([exe('vlog'),'-sv','+incdir+../rtl',*inputs,'../tests/tb_mmio.sv'],work)
        log=run([exe('vsim'),'-c','tb_mmio','-do','run -all; quit -f'],work)
        if 'ASIC_MMIO_PASS' not in log:raise RuntimeError(log)
        run([exe('vlog'),'-sv','../dc/kwt_sram16.sv','../tests/macro_models.sv','../tests/tb_memories.sv'],work)
        log+=run([exe('vsim'),'-c','tb_memories','-do','run -all; quit -f'],work)
        if 'ASIC_MEMORY_PASS' not in log:raise RuntimeError(log)
        result_dir=ROOT/'output/simulation';result_dir.mkdir(parents=True,exist_ok=True)
        (result_dir/'tests.log').write_text(log)
        report['simulation']='PASS'
    else:report['simulation']='NOT_RUN'
    out=ROOT/'output';out.mkdir(exist_ok=True)
    (out/'checks.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
if __name__=='__main__':main()
