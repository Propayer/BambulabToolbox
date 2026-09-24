import copy
import importlib
import json
import os
from pathlib import Path
import sys
import zipfile
from dataclasses import replace
import numpy as np
import pytest
from PIL import Image
from jarvis_bambu.core.dsc_export import export_dsc
from jarvis_bambu.core.dsc_live_fields import validate_field, validate_fields, import_template, COORDINATES
from jarvis_bambu.core.dsc_validation import validate_package
from test_height_raster import model, write_3mf
from jarvis_bambu.core.stl_color_map import analyze_model

FIELD = dict(field_id='pet_name',label='Nombre',type='text',default='LUNA',enabled=True,hitbox=dict(x=.24,y=.41,width=.52,height=.14))


@pytest.mark.parametrize('size',[256,512,1024])
@pytest.mark.parametrize('version',[1,2])
def test_packages_binary_and_real_importer(tmp_path,size,version):
    m=model();zones=[replace(z,id=f'zone_{i}') for i,z in enumerate(m.zones([1,2,3]))]
    fields=[FIELD,dict(FIELD,field_id='number',type='number',default=12,hitbox=None)] if version==2 else []
    path=export_dsc(tmp_path/'test.zip',m,[1,2,3],zones=zones,size=size,version=version,live_fields=fields)
    manifest=validate_package(path)
    assert manifest['package_schema']==f'dsc.preview-package.v{version}'
    assert manifest['view']['pixels_per_mm']==size*.88/10
    assert manifest['view']['center_xy_mm']==[5,5]
    with zipfile.ZipFile(path) as z:
        mask=np.asarray(Image.open(z.open('color_1.png')))
        assert not mask.any() # Exact z=1 belongs to upper interval; lower zone is hidden.
        assert manifest['preview']['layers'][0]['field_id']=='zone_0'
    if os.environ.get('DSC_PROJECT'):
        sys.path.insert(0,os.environ['DSC_PROJECT'])
        importer=importlib.import_module('app.preview_package').import_preview_package
        result=importer(path.read_bytes(),tmp_path/'images')
        assert len(result['fields'])==len(zones)+len(fields)
        if version==2:
            got=result['fields'][-2]
            assert got['id']=='pet_name' and got['default']=='LUNA'
            assert got['live_preview']['hitbox']==FIELD['hitbox']


def test_template_roundtrip(tmp_path):
    path=tmp_path/'dsc-live-field-pet_name.json'
    template=dict(schema='dsc.live-field-template.v1',package_schema='dsc.preview-package.v2',field=dict(id='pet_name',label='Nombre',type='text',default='LUNA'),enabled=True,coordinate_system=COORDINATES,hitbox=FIELD['hitbox'])
    path.write_text(json.dumps(template));assert import_template(path)==FIELD
    template['hitbox']=None;path.write_text(json.dumps(template));assert import_template(path)['hitbox'] is None
    for key,value in [('schema','wrong'),('coordinate_system',dict(COORDINATES,reference='model_bounds'))]:
        bad=dict(template);bad[key]=value;path.write_text(json.dumps(bad))
        with pytest.raises(ValueError):import_template(path)


@pytest.mark.parametrize('patch',[{'field_id':'constructor'},{'field_id':'BAD'},{'field_id':'__proto__'},{'label':'x'*101},{'default':'x'*201},{'enabled':1},{'type':'color'},{'unknown':True},{'type':'number','default':'12'},{'type':'number','default':True},{'type':'number','default':float('nan')},{'type':'number','default':1e-6},{'type':'number','default':1.1234567}])
def test_invalid_fields(patch):
    with pytest.raises(ValueError):validate_field(dict(FIELD,**patch))


@pytest.mark.parametrize('patch',[{'x':-.1},{'width':0},{'width':.9},{'y':True},{'height':float('inf')},{'rotation_deg':90},{'extra':0}])
def test_invalid_hitboxes(patch):
    with pytest.raises(ValueError):validate_field(dict(FIELD,hitbox=dict(FIELD['hitbox'],**patch)))


def test_limits_and_atomic_rejection(tmp_path):
    with pytest.raises(ValueError):validate_fields([FIELD],['pet_name'])
    with pytest.raises(ValueError):validate_fields([dict(FIELD,field_id=f'f_{i}') for i in range(40)],['color_1'])
    path=tmp_path/'existing.zip';path.write_bytes(b'keep')
    with pytest.raises(ValueError):export_dsc(path,model(),[1],version=1,live_fields=[FIELD])
    assert path.read_bytes()==b'keep'


def test_validator_rejects_corruption(tmp_path):
    path=export_dsc(tmp_path/'test.zip',model(),[1.5,2.5])
    with zipfile.ZipFile(path) as z:files={n:z.read(n) for n in z.namelist()}
    files['color_2.png']=files['color_1.png']
    with zipfile.ZipFile(path,'w') as z:
        for n,data in files.items():z.writestr(n,data)
    with pytest.raises(ValueError,match='solapan'):validate_package(path)


def test_build_transform_3mf(tmp_path):
    path=write_3mf(tmp_path/'transform.3mf')
    with zipfile.ZipFile(path) as z:xml=z.read('3D/3dmodel.model').decode()
    xml=xml.replace('<item objectid="1"/>','<item objectid="1" transform="1 0 0 0 1 0 0 0 1 20 30 4"/>')
    with zipfile.ZipFile(path,'w') as z:z.writestr('3D/3dmodel.model',xml)
    m=analyze_model(path)
    assert list(m.summary.bounds_min)==[20,30,4]
    assert list(m.summary.bounds_max)==[30,40,5]


def test_live_fields_do_not_change_pixels_or_reread(tmp_path,monkeypatch):
    m=model();r=m.top_raster(512)
    a=export_dsc(tmp_path/'a.zip',m,[1.5,2.5],live_fields=[])
    def no_io(*args,**kwargs):raise AssertionError('Model was reread')
    monkeypatch.setattr('jarvis_bambu.core.stl_color_map.analyze_model',no_io)
    b=export_dsc(tmp_path/'b.zip',m,[1.5,2.5],live_fields=[FIELD])
    assert m.top_raster(512) is r
    with zipfile.ZipFile(a) as za,zipfile.ZipFile(b) as zb:
        for name in ('preview.png','color_1.png','color_2.png','color_3.png'):
            assert za.read(name)==zb.read(name)


def test_real_dsc_endpoint_v2(tmp_path):
    root=os.environ.get('DSC_PROJECT')
    if not root:pytest.skip('Define DSC_PROJECT con el proyecto DSC real para la integración HTTP.')
    sys.path.insert(0,root)
    from app import create_app
    app=create_app({'TESTING':True,'DATABASE':str(tmp_path/'db.sqlite3'),'ADMIN_PASSWORD':'test-password-12345','COOKIE_SECURE':False,'PUBLIC_ORIGIN':'','PREVIEW_UPLOAD_DIR':str(tmp_path/'images')})
    client=app.test_client();headers={'X-Requested-With':'DSC','Origin':'http://localhost'}
    headers['X-CSRF-Token']=client.post('/api/login',json={'password':'test-password-12345'},headers=headers).json['csrf']
    path=export_dsc(tmp_path/'model.zip',model(),[1.5,2.5],live_fields=[FIELD])
    from io import BytesIO
    result=client.post('/api/admin/uploads/preview-package',data={'file':(BytesIO(path.read_bytes()),'model.zip')},headers=headers)
    assert result.status_code==200,result.json
    f=next(f for f in result.json['fields'] if f['id']=='pet_name')
    assert f['default']=='LUNA' and f['live_preview']['hitbox']==FIELD['hitbox']
    catalog=client.get('/api/admin/catalog').json
    target=next(m for m in catalog['models'] if m['id']=='collar_01')
    target['preview']=result.json['preview']
    existing={f['id']:f for f in target['fields']}
    for field in result.json['fields']:
        if field['id'] not in existing:target['fields'].append(field)
        elif 'live_preview' in field:
            existing[field['id']]['live_preview']=field['live_preview']
            if existing[field['id']]['default']=='':existing[field['id']]['default']=field['default']
    saved=client.put('/api/admin/models/collar_01',json=target,headers=headers)
    assert saved.status_code==200,saved.json
    public=next(m for m in client.get('/api/catalog').json['models'] if m['id']=='collar_01')
    field=next(f for f in public['fields'] if f['id']=='pet_name')
    assert field['live_preview']['hitbox']==FIELD['hitbox'] and field['default']=='LUNA'
