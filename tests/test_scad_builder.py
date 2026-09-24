import zipfile
import pytest
from jarvis_bambu.core.scad_builder.model import parameter, validate_parameters
from jarvis_bambu.core.scad_builder.scad_analysis import analyze_scad, update_source
from jarvis_bambu.core.scad_builder.makerworld import analyze_url, NO_SOURCE, validate_url
from jarvis_bambu.core.scad_builder.three_mf import analyze_3mf
from jarvis_bambu.core.scad_builder.reconstruction import new_document, set_mode
from jarvis_bambu.core.scad_builder.generator import prepare_package, export_package, open_package
from jarvis_bambu.core.scad_builder.runner import run_openscad, find_openscad, check_dependencies
from jarvis_bambu.core.scad_builder.validation import compare


def fixture_3mf(path):
    vertices=[(0,0,0),(60,0,0),(60,24,0),(0,24,0),(0,0,3),(60,0,3),(60,24,3),(0,24,3)]
    faces=[(0,2,1),(0,3,2),(4,5,6),(4,6,7),(0,1,5),(0,5,4),(1,2,6),(1,6,5),(2,3,7),(2,7,6),(3,0,4),(3,4,7)]
    objects=[]
    for oid,name,verts in [(1,'base',vertices),(2,'possible_text',[(x*.5+12,y*.4+6,z*.4+3) for x,y,z in vertices])]:
        vs=''.join(f'<vertex x="{x}" y="{y}" z="{z}"/>' for x,y,z in verts)
        ts=''.join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a,b,c in faces)
        objects.append(f'<object id="{oid}" name="{name}" type="model"><mesh><vertices>{vs}</vertices><triangles>{ts}</triangles></mesh></object>')
    model='<model xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" unit="millimeter"><resources>'+''.join(objects)+'</resources><build><item objectid="1"/><item objectid="2"/></build></model>'
    with zipfile.ZipFile(path,'w') as z:z.writestr('3D/3dmodel.model',model)
    return path


def test_scad_literals_ranges_modules_and_derived():
    code='''/* [Main] */
name = "LUNA";
color_value = "#FFFF00"; // color
font_name = "Roboto"; // font
size = 12; // [1:0.5:20]
style = "S"; // [S:Small, L:Large]
on = true;
derived = size * 2;
module mw_plate_1() { local = 99; text(name); }
module mw_assembly_view() {}
'''
    a=analyze_scad(code)
    assert len(a['parameters'])==6 and a['assembly'] and a['parametric_text']
    assert a['parameters'][3]['step']==.5
    assert a['derived'][0]['id']=='derived'
    a['parameters'][0]['default']='"; cube(999); //'
    edited=update_source(code,a['parameters'])
    assert analyze_scad(edited)['parameters'][0]['default']=='"; cube(999); //'


def test_color_cycles_and_invalid_types():
    p=[parameter('a','color','#FFFFFF'),parameter('b','color','#000000')]
    p[0]['color_binding']={'mode':'inherit','source':'b'}
    p[1]['color_binding']={'mode':'inherit','source':'a'}
    with pytest.raises(ValueError):validate_parameters(p)
    with pytest.raises(ValueError):validate_parameters([parameter('n','number',float('nan'))])


def test_public_source_and_blocked_fallback():
    url='https://makerworld.com/en/models/123-example'
    a=analyze_url(url,fetch=lambda u:'<meta property="og:title" content="Public"><pre>name="Luna"; text(name);</pre>')
    assert a['original_scad_available'] and a['title']=='Public'
    b=analyze_url(url,fetch=lambda u:'<title>No SCAD</title>')
    assert NO_SOURCE in b['warnings']
    with pytest.raises(ValueError):validate_url('http://127.0.0.1/private')
    with pytest.raises(ValueError):validate_url('https://makerworld.com.evil.test/en/models/1')


def test_3mf_reconstruction_export_and_reopen(tmp_path):
    ref=analyze_3mf(fixture_3mf(tmp_path/'input.3mf'))
    assert len(ref.parts)==2 and 'text' in ref.parts[1].hints
    doc=new_document(ref);set_mode(doc,'part_2','text')
    package=tmp_path/'package';prepared=prepare_package(package,doc,ref)
    source=(package/'model.scad').read_text()
    assert 'linear_extrude' in source and 'color(base_color)' in source and 'import(' in source
    assert 'default.stl' in (package/'makerworld.scad').read_text()
    z=export_package(tmp_path/'result.zip',doc,ref)
    restored,assets=open_package(z)
    assert restored['parameters']==prepared['parameters']
    prepare_package(tmp_path/'restored',restored,assets=assets)
    assert (tmp_path/'restored/model.scad').read_text()==source


def test_hostile_zip_and_xml_rejected(tmp_path):
    for name,data in [('../x','bad'),('3D/3dmodel.model','<!DOCTYPE model><model/>')]:
        p=tmp_path/'bad.3mf'
        with zipfile.ZipFile(p,'w') as z:z.writestr(name,data)
        with pytest.raises(ValueError):analyze_3mf(p)


def test_compare_identical_and_displaced(tmp_path):
    ref=analyze_3mf(fixture_3mf(tmp_path/'input.3mf'))
    c=compare(ref.triangles,ref.triangles)
    assert c['top_silhouette_iou']==1 and c['dimensions_delta_mm']==[0,0,0]
    assert compare(ref.triangles,ref.triangles+[4,0,0])['position_delta_mm']==[4,0,0]


def test_runner_rejects_external_assets(tmp_path):
    for source in ['import("/etc/passwd");','include <evil.scad>;','import(str("/",name));']:
        with pytest.raises(ValueError):check_dependencies(source,tmp_path)


@pytest.mark.skipif(not find_openscad(),reason='OpenSCAD no instalado')
def test_actual_openscad_render(tmp_path):
    ref=analyze_3mf(fixture_3mf(tmp_path/'input.3mf'));doc=new_document(ref)
    set_mode(doc,'part_2','text')
    prepare_package(tmp_path/'result',doc,ref)
    result=run_openscad(tmp_path/'result',timeout=30)
    assert result['ok'],result['logs']
    assert 'generated.stl' in result['outputs'] and 'generated.3mf' in result['outputs']


def test_nested_comments_and_scad_scope():
    a=analyze_scad('/* a = 123; */\n label="{a}; // text";\nmodule x() { inner=4; }\nlast=7;')
    assert [p['id'] for p in a['parameters']]==['label','last']


def test_forged_comment_does_not_allow_dynamic_import(tmp_path):
    with pytest.raises(ValueError):
        check_dependencies('// reconstructed SCAD\nfile="default.stl";\nmodule bad() {file="/etc/passwd";import(file);}bad();',tmp_path)


def test_cancel_before_openscad(tmp_path):
    if not find_openscad():pytest.skip('OpenSCAD no instalado')
    (tmp_path/'model.scad').write_text('cube(1);')
    with pytest.raises(ValueError,match='cancelada'):
        run_openscad(tmp_path,cancel=lambda:True)
