"""Analytic fixtures; core tests never need Qt."""
import json
import zipfile
import struct
from pathlib import Path
import numpy as np
import pytest
from PIL import Image
from jarvis_bambu.core.stl_color_map import analyze_model, _build_height_map, export_height_map_json
from jarvis_bambu.core.height_raster import rasterize_top, CancelledError
from jarvis_bambu.core.dsc_export import export_dsc


def quad(x0,y0,x1,y1,z):
    return np.array([[[x0,y0,z],[x1,y0,z],[x1,y1,z]],[[x0,y0,z],[x1,y1,z],[x0,y1,z]]],float)


def stepped():
    return np.concatenate([quad(0,0,10,10,0),quad(0,0,10,10,1),quad(2,2,8,8,2),quad(4,4,6,6,3)])


def model(tris=None):
    return _build_height_map(Path('steps.stl'), stepped() if tris is None else tris, sample_count=80,source_type='stl')


def test_visible_surface_matches_analytic_steps():
    raster=model().top_raster(256)
    y,x=np.mgrid[:256,:256]
    wx=(x+.5-128)/raster.pixels_per_mm+5
    wy=-(y+.5-128)/raster.pixels_per_mm+5
    expected=np.full((256,256),-np.inf)
    for low,high,z in [(0,10,1),(2,8,2),(4,6,3)]:
        expected[(wx>=low)&(wx<=high)&(wy>=low)&(wy<=high)]=z
    np.testing.assert_allclose(raster.depth,expected)
    labels=raster.labels([1.5,2.5]); masks=[raster.rgba(labels,zone=i,neutral=True) for i in range(3)]
    union=sum((m[:,:,3]>0).astype(int) for m in masks)
    np.testing.assert_array_equal(union,raster.face>=0)
    assert labels[128,128]==2


def test_slopes_cross_in_depth_not_mean_depth_sorting():
    triangles=np.array([[[0,0,0],[10,0,10],[0,10,0]],[[0,0,10],[10,0,0],[0,10,10]]],float)
    raster=rasterize_top(triangles,256)
    y,x=np.mgrid[:256,:256];wx=(x+.5-128)/raster.pixels_per_mm+5
    expected=np.maximum(wx,10-wx); visible=raster.face>=0
    np.testing.assert_allclose(raster.depth[visible],expected[visible],atol=1e-12)
    np.testing.assert_allclose(raster.depth,rasterize_top(triangles[::-1,::-1],256).depth)


def test_orientation_aspect_ratio_and_vertical_faces():
    tris=np.concatenate([quad(0,0,20,10,1),quad(1,7,3,9,2), np.array([[[10,0,0],[10,10,0],[10,10,100]]])])
    r=rasterize_top(tris,256)
    ys,xs=np.where(r.depth==2)
    assert xs.mean()<128 and ys.mean()<128
    ys,xs=np.where(r.face>=0)
    assert abs((xs.max()-xs.min())/(ys.max()-ys.min())-2)<.03
    assert r.depth.max()==2


def test_boundary_only_upper_interval():
    r=model().top_raster(256);labels=r.labels([1,2])
    assert np.all(labels[r.depth==1]==1)
    assert np.all(labels[r.depth==2]==2)
    assert np.all(labels[r.depth==3]==2)


def test_cache_cut_edits_and_resolution_limit():
    m=model();r=m.top_raster(256)
    for cuts in ([1.2],[1.5,2.5],[]):r.labels(cuts)
    assert m.top_raster(256) is r
    m.top_raster(512);m.top_raster(1024)
    assert len(m._rasters)==2


def test_export_alignment_and_json(tmp_path):
    m=model();path=export_dsc(tmp_path/'test.zip',m,[1.5,2.5],size=256)
    with zipfile.ZipFile(path) as z:
        manifest=json.loads(z.read('model-map.json'))
        base=np.array(Image.open(z.open('preview.png')))
        masks=[np.array(Image.open(z.open(f'color_{i}.png'))) for i in (1,2,3)]
        assert all(mask.shape==base.shape for mask in masks)
        np.testing.assert_array_equal(sum(mask[:,:,3].astype(int) for mask in masks),base[:,:,3])
        assert all(set(np.unique(mask[:,:,3]))<={0,255} for mask in masks)
        assert manifest['preview']['layers'][1]=={'field_id':'color_2','mask_image':'color_2.png'}
        assert manifest['view']['projection']=='orthographic'
    export_height_map_json(tmp_path/'map.json',m,[1.5,2.5])
    assert len(json.loads((tmp_path/'map.json').read_text())['zones'])==3


def test_cancel_keeps_existing_export(tmp_path):
    p=tmp_path/'model.zip';p.write_bytes(b'previous')
    with pytest.raises(CancelledError):export_dsc(p,model(),[1.5],cancel=lambda:True)
    assert p.read_bytes()==b'previous' and list(tmp_path.iterdir())==[p]


@pytest.mark.parametrize('tris',[np.empty((0,3,3)),np.zeros((2,3,3)),np.array([[[0,0,0],[0,0,1],[0,0,2]]],float),np.full((1,3,3),np.nan)])
def test_degenerate_and_empty(tris):
    with pytest.raises(ValueError):model(tris)


def test_binary_stl_multiple_steps(tmp_path):
    triangles=stepped();data=bytearray(80)+struct.pack('<I',len(triangles))
    for tri in triangles:data+=struct.pack('<12fH',0,0,0,*tri.flatten(),0)
    path=tmp_path/'steps.stl';path.write_bytes(data);m=analyze_model(path)
    assert m.summary.triangle_count==8 and m.top_raster(256).depth[128,128]==3


def write_3mf(path, *, painting='', resources='', attrs='', unit='millimeter', vertices=None):
    vertices=vertices or [(0,0,0),(10,0,1),(0,10,1)]
    xml=f'<model xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" unit="{unit}"><resources>{resources}<object id="1" {attrs}><mesh><vertices>'+''.join(f'<vertex x="{x}" y="{y}" z="{z}"/>' for x,y,z in vertices)+f'</vertices><triangles><triangle v1="0" v2="1" v3="2" {painting}/></triangles></mesh></object></resources><build><item objectid="1"/></build></model>'
    with zipfile.ZipFile(path,'w') as z:z.writestr('3D/3dmodel.model',xml)
    return path


def test_3mf_no_color_units_and_materials(tmp_path):
    p=write_3mf(tmp_path/'plain.3mf',unit='inch');m=analyze_model(p)
    assert not m.detected_colors and m.z_max==25.4
    p=write_3mf(p,resources='<basematerials id="2"><base name="red" displaycolor="#FF0000"/></basematerials>',attrs='pid="2" pindex="0"')
    assert analyze_model(p).detected_colors[0].color=='#FF0000'


def test_subdivided_paint_warns(tmp_path):
    p=write_3mf(tmp_path/'painted.3mf',painting='paint_color="1F"')
    assert 'subdivididas' in ' '.join(analyze_model(p).warnings)


def test_empty_3mf_and_bad_indices(tmp_path):
    p=tmp_path/'empty.3mf'
    with zipfile.ZipFile(p,'w') as z:z.writestr('3D/3dmodel.model','<model xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"><resources/><build/></model>')
    with pytest.raises(ValueError,match='mallas'):analyze_model(p)
    write_3mf(p,vertices=[(0,0,0)])
    with pytest.raises(ValueError,match='índices'):analyze_model(p)


def test_repeated_colors_and_overlap_warning():
    from jarvis_bambu.core.stl_color_map import _detected_colors, propose_color_guided_map, color_height_warnings
    tris=np.concatenate([quad(0,0,10,10,z) for z in (0,1,2,3)]);slots=np.repeat([1,2,1,2],2)
    colors=_detected_colors(tris,slots,{1:'#FFFFFF',2:'#FF0000'})
    assert len(propose_color_guided_map(tris,slots,colors,0,3).cuts)==3
    tris=np.concatenate([quad(0,0,5,10,1),quad(5,0,10,10,1),quad(0,0,10,10,0)])
    assert color_height_warnings(tris,np.array([1,1,2,2,1,1]))
