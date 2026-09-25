import importlib.util
from pathlib import Path
import unittest
import sys
import numpy as np
spec=importlib.util.spec_from_file_location('layout_config',Path(__file__).resolve().parents[1]/'tools/layout_inspection/config.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class CommonFrame(unittest.TestCase):
    def test_hybrid_defaults_show_background_and_not_people(self):
        selected=m.reference_layers({},True)
        self.assertTrue({'static','context','glass','mirror','context_points'}.issubset(selected))
        self.assertNotIn('person',selected)
        self.assertEqual(m.reference_layers({},False),['static'])
        self.assertEqual(m.reference_layers({'reference_layers':['static']},True),['static'])
    def config(self):
        return {'model_to_world':np.eye(4).tolist(),'model_transform_reason':'already authored in reviewed basis','views':{x:{'location':[0,0,10],'target':[0,0,0],'ortho_scale':8,'crop_xyz_m':[[-4,4],[-4,4],[0,4]]} for x in ('top','front','side')}}
    def test_transform_mismatch_rejected(self):
        t=np.eye(4);t[0,3]=1
        with self.assertRaises(ValueError):m.validate(self.config(),t,np.eye(4))
    def test_explicit_common_frame(self):
        np.testing.assert_array_equal(m.validate(self.config(),np.eye(4),np.eye(4)),np.eye(4))
    def test_inverted_slice_rejected(self):
        c=self.config();c['views']['top']['crop_xyz_m'][2]=[4,0]
        with self.assertRaises(ValueError):m.validate(c,np.eye(4),np.eye(4))
    def test_no_implicit_registration(self):
        c=self.config();del c['model_transform_reason']
        with self.assertRaises(ValueError):m.validate(c,np.eye(4),np.eye(4))
@unittest.skipUnless(importlib.util.find_spec('bpy'), 'Requires background Blender')
class RenderableSurfaces(unittest.TestCase):
    def test_bulk_lines_match_curve_geometry_without_selection_side_effects(self):
        import bpy
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools/layout_inspection'))
        from render_blender import feature_edges,collection
        bpy.ops.wm.read_factory_settings(use_empty=True)
        for endpoint in [(1,0,0),(0,1,0),(0,0,1),(0,0,-1),(1,2,3),(-2,1,-3)]:
            mesh=bpy.data.meshes.new('wire');mesh.from_pydata([(0,0,0),endpoint],[(0,1)],[])
            curve=bpy.data.curves.new('reference','CURVE');curve.dimensions='3D'
            curve.bevel_depth=.1;curve.bevel_resolution=0;curve.resolution_u=1
            spline=curve.splines.new('POLY');spline.points.add(1)
            for point,co in zip(spline.points,[(0,0,0),endpoint]):point.co=(*co,1)
            ref=bpy.data.objects.new('reference',curve);bpy.context.scene.collection.objects.link(ref)
            bpy.context.view_layer.objects.active=ref;ref.select_set(True)
            bpy.ops.object.convert(target='MESH');ref=bpy.context.object
            selected=list(bpy.context.selected_objects)
            actual=feature_edges(mesh,collection('edges'),'bulk',.2,.5)
            self.assertEqual(list(bpy.context.selected_objects),selected)
            self.assertEqual(bpy.context.view_layer.objects.active,ref)
            x=np.array([tuple(v.co) for v in actual.data.vertices]);y=np.array([tuple(v.co) for v in ref.data.vertices])
            self.assertEqual(x.shape,y.shape)
            self.assertLess(np.linalg.norm(x[:,None,:]-y[None,:,:],axis=2).min(axis=1).max(),1e-6)
            self.assertEqual(len(actual.data.polygons),len(ref.data.polygons))
            ref.select_set(False)

    def test_bulk_lines_suppress_coplanar_diagonals_and_handle_empty_mesh(self):
        import bpy
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools/layout_inspection'))
        from render_blender import feature_edges,collection
        bpy.ops.wm.read_factory_settings(use_empty=True)
        mesh=bpy.data.meshes.new('plane')
        mesh.from_pydata([(0,0,0),(1,0,0),(1,1,0),(0,1,0)],[],[(0,1,2),(0,2,3)])
        self.assertEqual(len(feature_edges(mesh,collection('plane'),'plane',.02,.5).data.vertices),32)
        empty=bpy.data.meshes.new('empty')
        self.assertEqual(len(feature_edges(empty,collection('empty'),'empty',.02,.5).data.vertices),0)

    def test_cache_preserves_cuts_edges_and_invalidates_edge_settings(self):
        import bpy
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools/layout_inspection'))
        from render_blender import ModelViewCache,collection,clipped,feature_edges,color
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.mesh.primitive_cube_add()
        base=bpy.context.object.data.copy()
        original=[tuple(v.co) for v in base.vertices]
        cache=ModelViewCache()
        def vertices(mesh):
            return sorted(tuple(round(float(x),6) for x in v.co) for v in mesh.vertices)
        crops=[[[-2,2]]*3,[[-3,3]]*3,[[-2,0],[-2,2],[-2,2]]]
        pairs=[]
        for index,crop in enumerate(crops):
            model=collection('model'+str(index));edges=collection('edges'+str(index))
            reused=cache.add('cube',base,crop,model,edges,.02,.5)
            self.assertEqual(reused,index==1)
            mesh=model.objects[0].data;edge=edges.objects[0].data
            expected=base.copy();clipped(expected,crop);color(expected,[.78]*3)
            expected_edge=feature_edges(expected,collection('expected'+str(index)),'expected',.02,.5).data
            self.assertEqual(vertices(mesh),vertices(expected))
            self.assertEqual(vertices(edge),vertices(expected_edge))
            self.assertEqual(len(mesh.polygons),len(expected.polygons))
            self.assertEqual(len(edge.polygons),len(expected_edge.polygons))
            pairs.append((mesh,edge))
        self.assertEqual(pairs[0],pairs[1])
        self.assertNotEqual(pairs[0],pairs[2])
        self.assertEqual([tuple(v.co) for v in base.vertices],original)
        self.assertFalse(cache.add('wide',base,crops[0],collection('wide'),collection('wide edges'),.04,.5))
        self.assertFalse(cache.add('angle',base,crops[0],collection('angle'),collection('angle edges'),.02,1.0))

    def test_beveled_curve_survives_inspection_with_visibility_filters(self):
        import bpy
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools/layout_inspection'))
        from render_blender import eligible_sources
        bpy.ops.wm.read_factory_settings(use_empty=True)
        scene=bpy.context.scene
        def curve(name):
            data=bpy.data.curves.new(name, 'CURVE')
            data.dimensions='3D';data.bevel_depth=.05
            spline=data.splines.new('POLY');spline.points.add(2)
            for point,coordinate in zip(spline.points,[(0,0,0,1),(0,0,1,1),(1,0,1,1)]):
                point.co=coordinate
            obj=bpy.data.objects.new(name,data);scene.collection.objects.link(obj)
            return obj
        visible=curve('visible faucet arch')
        hidden=curve('render-hidden curve');hidden.hide_render=True
        excluded=curve('configured exclusion')
        hidden_collection=bpy.data.collections.new('hidden collection')
        scene.collection.children.link(hidden_collection);hidden_collection.hide_render=True
        in_hidden=curve('hidden collection curve')
        scene.collection.objects.unlink(in_hidden);hidden_collection.objects.link(in_hidden)
        bpy.context.view_layer.update()
        selected=eligible_sources(scene,{'exclude_objects':[excluded.name]})
        self.assertEqual([o.name for o in selected],[visible.name])
        mesh=bpy.data.meshes.new_from_object(visible.evaluated_get(bpy.context.evaluated_depsgraph_get()))
        try:
            self.assertGreater(len(mesh.polygons),0)
            self.assertGreater(max(v.co.z for v in mesh.vertices),.99)
        finally:bpy.data.meshes.remove(mesh)

if __name__=='__main__':unittest.main(argv=[__file__])
