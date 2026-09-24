"""Bounded subprocess execution; caller runs this on a GUI worker thread."""
from pathlib import Path
import json
import os
import re
import shutil
import subprocess
import time
import psutil
from .scad_analysis import analyze_scad, masked


def find_openscad(configured=''):
    if configured:
        path=Path(configured).expanduser()
        if not path.is_file():raise ValueError('La ruta de OpenSCAD no existe.')
        return str(path.resolve())
    found=shutil.which('openscad')
    if found:return found
    for path in [Path(os.environ.get('ProgramFiles','C:/Program Files'))/'OpenSCAD/openscad.exe',
                 Path('/Applications/OpenSCAD.app/Contents/MacOS/OpenSCAD')]:
        if path.is_file():return str(path)
    return None


def check_dependencies(source, directory):
    """OpenSCAD is not a sandbox. Reject dynamic/external paths before local execution."""
    clean=masked(source)
    # Also reject library directives (even if inside modules), rather than accessing host files.
    if re.search(r'\b(?:include|use)\s*<',clean):
        raise ValueError('Validación local: aplana/revisa las librerías externas antes de ejecutar. El código original se conserva al exportar.')
    analysis=analyze_scad(source)
    literals={p['scad_variable']:p['default'] for p in analysis['parameters']}
    for match in re.finditer(r'\b(?:import|surface)\s*\(\s*(?:file\s*=\s*)?("(?:\\.|[^"\\])*"|[A-Za-z_]\w*)\s*([,)])',clean):
        raw=match[1]
        value=json.loads(raw) if raw.startswith('"') else literals.get(raw)
        if not isinstance(value,str) or not re.fullmatch(r'(?:assets/[a-f0-9]{64}\.stl|default\.(?:stl|svg|png))',value):
            raise ValueError('Importación externa o dinámica bloqueada en la validación local.')
        path=(Path(directory)/value).resolve()
        if not path.is_relative_to(Path(directory).resolve()) or not path.is_file():
            raise ValueError('Falta el asset requerido dentro del paquete.')
    found=len(re.findall(r'\b(?:import|surface)\s*\(',clean))
    recognized=len(list(re.finditer(r'\b(?:import|surface)\s*\(\s*(?:file\s*=\s*)?("(?:\\.|[^"\\])*"|[A-Za-z_]\w*)\s*([,)])',clean)))
    if found!=recognized:raise ValueError('No se ejecutan importaciones con expresiones dinámicas.')
    # Require literal imports for every source; a comment is never a trust boundary.
    for m in re.finditer(r'\b(?:import|surface)\s*\(\s*(?:file\s*=\s*)?([^\s])',clean):
        if m[1]!='"':raise ValueError('SCAD importado: usa rutas literales del paquete para validación local.')


def run_openscad(directory, executable='', *, cancel=None, timeout=90, progress=None):
    directory=Path(directory).resolve()
    binary=find_openscad(executable)
    if not binary: return dict(available=False,ok=False,logs='OpenSCAD no está instalado. Configura su ruta.',outputs=[])
    source=(directory/'model.scad').read_text(encoding='utf-8')
    check_dependencies(source,directory)
    logs=[];outputs=[];ok=True
    environment=dict(os.environ,QT_QPA_PLATFORM='offscreen')
    for index,(name,extra) in enumerate([('syntax.csg',[]),('generated.stl',[]),('generated.3mf',[]),('render.png',['--imgsize=512,512','--viewall','--autocenter'])]):
        if cancel and cancel():raise ValueError('Operación cancelada.')
        output=directory/name
        output.unlink(missing_ok=True)
        logpath=directory/'openscad.log'
        with logpath.open('wb') as log:
            kwargs={'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {'start_new_session':True}
            process=subprocess.Popen([binary,'-o',str(output),*extra,str(directory/'model.scad')],cwd=directory,
                                     stdout=log,stderr=subprocess.STDOUT,env=environment,**kwargs)
            start=time.monotonic()
            stop=''
            try:
                while process.poll() is None:
                    if cancel and cancel():stop='Cancelado'
                    elif time.monotonic()-start>timeout:stop='Tiempo máximo de OpenSCAD agotado'
                    elif logpath.stat().st_size>2_000_000:stop='Límite de logs alcanzado'
                    elif output.exists() and output.stat().st_size>128_000_000:stop='Salida demasiado grande'
                    try:
                        if psutil.Process(process.pid).memory_info().rss > 2_000_000_000:stop='Límite de memoria OpenSCAD alcanzado (2 GB)'
                    except (psutil.NoSuchProcess,psutil.AccessDenied):pass
                    if stop:process.kill();break
                    time.sleep(.05)
            finally:
                if process.poll() is None:process.kill()
                process.wait()
        text=logpath.read_bytes()[:2_000_000].decode('utf-8',errors='replace')
        logs.append(f'[{name}]\n{stop}\n{text}')
        success=not stop and process.returncode==0 and output.exists() and output.stat().st_size>0 and 'ERROR:' not in text
        if success:outputs.append(name)
        else:
            output.unlink(missing_ok=True)
            if name!='render.png':ok=False
        if progress:progress(round((index+1)*100/4))
        if name=='syntax.csg' and not success or stop:break
    logtext='\n'.join(logs)
    (directory/'validation.log').write_text(logtext,encoding='utf-8')
    return dict(available=True,ok=ok,logs=logtext,outputs=outputs)
