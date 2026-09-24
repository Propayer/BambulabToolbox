"""Conservative lexical analyzer: literal top-level parameters, no SCAD execution."""
import json
import re
from .model import parameter, validate_parameters, literal

TOKEN = re.compile(r'//[^\n]*|/\*[\s\S]*?\*/|"(?:\\.|[^"\\])*"|[A-Za-z_$][\w$]*|\s+|.', re.MULTILINE)


def masked(source):
    # Preserve offsets and quoted strings; blank comments (not their newlines).
    return TOKEN.sub(lambda m: re.sub(r'[^\n]', ' ', m[0]) if m[0].startswith(('//', '/*')) else m[0], source)


def analyze_scad(source):
    if len(source.encode('utf-8')) > 2_000_000: raise ValueError('SCAD demasiado grande (2 MB).')
    clean = masked(source)
    params, derived, spans = [], [], {}
    depth = paren = bracket = 0
    start = 0
    for token in TOKEN.finditer(clean):
        char = token[0]
        if char.startswith('"'): continue
        if char == '{': depth += 1
        elif char == '}':
            depth -= 1
            if depth == 0: start = token.end()
        elif char == '(': paren += 1
        elif char == ')': paren -= 1
        elif char == '[': bracket += 1
        elif char == ']': bracket -= 1
        elif char == ';' and depth == paren == bracket == 0:
            segment = clean[start:token.start()]
            match = re.fullmatch(r'\s*([A-Za-z_][\w]*)\s*=\s*(.*?)\s*', segment, re.S)
            if match:
                key, expr = match[1], match[2]
                begin, end = start+match.start(2), start+match.end(2)
                tail = source[token.end():].split('\n', 1)[0]
                groups = re.findall(r'/\*\s*\[([^]]+)\]\s*\*/', source[:start])
                group = groups[-1].strip() if groups else ''
                try:
                    value = json.loads(expr)
                    if type(value) not in (str, float, int, bool): raise ValueError()
                    kind = 'boolean' if isinstance(value, bool) else 'number' if isinstance(value, (float, int)) else 'text'
                    if re.match(r'\s*//\s*color\b', tail): kind = 'color'
                    if re.match(r'\s*//\s*font\b', tail): kind = 'font'
                    p = parameter(key, kind, value, group=group, hidden=group.lower() == 'hidden')
                    spec = re.search(r'//\s*\[([^]]+)\]', tail)
                    if spec:
                        spec = spec[1]
                        numbers = spec.split(':')
                        try:
                            values = [float(x) for x in numbers]
                            if len(values) not in (2, 3) or kind != 'number': raise ValueError()
                            p.update(min=values[0], max=values[-1])
                            if len(values) == 3: p['step'] = values[1]
                        except ValueError:
                            opts = []
                            for opt in spec.split(','):
                                v, _, label = opt.strip().partition(':')
                                try: v = json.loads(v)
                                except ValueError: pass
                                opts.append(dict(value=v, label=label or str(v)))
                            p.update(type='select', options=opts)
                    params.append(p); spans[key] = (begin, end)
                except (ValueError, TypeError):
                    derived.append(dict(id=key, expression=expr[:2000]))
            start = token.end()
    modules = re.findall(r'\bmodule\s+([A-Za-z_]\w*)\s*\(', clean)
    libraries = re.findall(r'\b(?:use|include)\s*<([^>]+)>', clean)
    assets = re.findall(r'\b(?:import|surface)\s*\(\s*(?:file\s*=\s*)?([^,)]+)', clean)
    warnings = []
    if derived: warnings.append('Expresiones derivadas/vectores: conservados en SCAD, sin evaluarlos en Python.')
    if libraries: warnings.append('Librerías externas: no se descargan ni se aplanan automáticamente.')
    if assets: warnings.append('Assets externos: revisa disponibilidad y usa default.stl/svg/png en PMM.')
    if 'mw_assembly_view' in modules or any(m.startswith('mw_plate_') for m in modules):
        warnings.append('Multi-plate PMM: la validación local puede requerir un wrapper de salida; no se añade automáticamente.')
    return dict(parameters=params, derived=derived, modules=modules,
                plate_modules=[m for m in modules if re.fullmatch(r'mw_plate_\d+', m)],
                assembly='mw_assembly_view' in modules, libraries=libraries, assets=assets,
                parametric_text=bool(re.search(r'\btext\s*\(', clean)), spans=spans, warnings=warnings)


def update_source(source, parameters):
    validate_parameters(parameters)
    analysis = analyze_scad(source)
    changes = []
    for p in parameters:
        if p['scad_variable'] not in analysis['spans']:
            raise ValueError('La variable no existe como literal editable en el SCAD.')
        begin, end = analysis['spans'][p['scad_variable']]
        binding = p.get('color_binding', {})
        value = literal(p['default'])
        if p['type'] == 'color' and binding.get('mode') == 'inherit':
            value = next(q['scad_variable'] for q in parameters if q['id'] == binding['source'])
        changes.append((begin, end, value))
    for begin, end, value in sorted(changes, reverse=True): source = source[:begin]+value+source[end:]
    return source
