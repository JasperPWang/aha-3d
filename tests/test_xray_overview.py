import copy
import json
from pathlib import Path
import tempfile
import unittest
from PIL import Image
from tools.layout_inspection.overview import draw_overview,write_overviews
from tools.layout_inspection.overlay import write_report


class XrayOverview(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.image=self.root/'view_reference.png'
        Image.new('RGB',(300,200),(60,70,80)).save(self.image)
        self.objects=[dict(id='floor',semantic_class='structure/floor',color=[100,150,220]),
                      dict(id='door',semantic_class='structure/door',color=[220,140,60]),
                      dict(id='chair',semantic_class='furniture/chair',color=[230,50,150])]
        self.view=dict(size=[300,200],settings=dict(crop_xyz_m=[[-1,1]]*3),objects={
            'floor':dict(paths=[[[5,5],[295,5],[295,195],[5,195]]]),
            'door':dict(paths=[[[200,40],[260,40],[260,150],[200,150]]]),
            'chair':dict(paths=[[[100,70],[160,70],[160,150],[100,150]]])})

    def test_overview_keeps_architecture_opening_and_furniture_without_internal_floor_lines(self):
        before=copy.deepcopy((self.objects,self.view))
        image,present=draw_overview(self.image,self.view,self.objects)
        self.assertEqual(set(present),{'floor','door','chair'})
        self.assertEqual(image.getpixel((50,100)),(60,70,80))
        self.assertEqual(image.getpixel((100,110)),(230,50,150))
        self.assertNotEqual(image.getpixel((200,100)),(60,70,80))
        self.assertEqual((self.objects,self.view),before)
        self.assertGreater(image.height,200)
        other,_=draw_overview(self.image,self.view,list(reversed(self.objects)))
        self.assertEqual(image.tobytes(),other.tobytes())

    def test_inventory_and_raster_mismatch_fail(self):
        with self.assertRaises(ValueError):draw_overview(self.image,self.view,self.objects[:-1])
        with self.assertRaises(ValueError):draw_overview(self.image,dict(self.view,size=[1,1]),self.objects)

    def test_report_promotes_overview_keeps_detailed_passes_and_declares_limits(self):
        report=dict(objects=self.objects,views={'view':self.view})
        outlines=self.root/'outlines';outlines.mkdir()
        manifest=write_overviews(outlines,report,self.root)
        self.assertEqual(len(manifest['images']),1)
        self.assertIn('enclosed holes',manifest['limitations'][0])
        for mode in ('overlay_xray','overlay_depth','model','uncertainty'):
            Image.new('RGB',(300,200)).save(self.root/f'view_{mode}.png')
        original=self.root/'report.html';original.write_text('Immutable upstream report')
        target=outlines/'comparison.html'
        write_report(self.root,dict(source_scene='scene.blend',views=report['views']),overview_dir=outlines,report_path=target)
        self.assertEqual(original.read_text(),'Immutable upstream report')
        html=target.read_text()
        self.assertLess(html.index('Object overview on Pi3X reference'),html.index('Detailed feature edges and depth comparison'))
        self.assertIn('X-ray: orange model edges always on top',html)
