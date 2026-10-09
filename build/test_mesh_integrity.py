"""Geometry truth wins over forged JSON/CSV flags and quantity claims."""
import copy
import csv
import json
from pathlib import Path
import unittest

import numpy as np
import rhino3dm as r
from check_delivery import verify_geometry
from mesh_integrity import arrays, topology, triangulate

ROOT = Path(__file__).resolve().parent.parent
BOX = np.array([[0,0,0],[1000,0,0],[1000,1000,0],[0,1000,0],
                [0,0,1000],[1000,0,1000],[1000,1000,1000],[0,1000,1000]],float)
FACES = np.array([[0,3,2,1],[4,5,6,7],[0,1,5,4],
                  [1,2,6,5],[2,3,7,6],[3,0,4,7]],dtype=np.int64)


def csv_records(quality):
    return [{k: '' if v is None else str(v) for k,v in record.items()}
            for record in quality['components']]


class TopologyTests(unittest.TestCase):
    def test_quad_cube_known_area_and_volume(self):
        actual=topology(BOX,FACES)
        self.assertTrue(actual['is_solid'])
        self.assertEqual(actual['area_m2'],6)
        self.assertEqual(actual['volume_m3'],1)
        self.assertEqual(len(triangulate(BOX,FACES)),12)

    def test_coincident_seam_vertices_weld_without_closing_real_gap(self):
        positions=BOX[FACES].reshape(-1,3)
        faces=np.arange(24,dtype=np.int64).reshape(6,4)
        self.assertTrue(topology(positions,faces)['is_solid'])
        positions[0,0]+=.001
        actual=topology(positions,faces)
        self.assertFalse(actual['is_closed'])
        self.assertGreater(actual['boundary_edges'],0)

    def test_open_orientation_and_nonmanifold_are_separate(self):
        self.assertFalse(topology(BOX,FACES[:-1])['is_closed'])
        reversed_faces=FACES.copy();reversed_faces[0]=reversed_faces[0][::-1]
        actual=topology(BOX,reversed_faces)
        self.assertTrue(actual['is_closed'])
        self.assertTrue(actual['is_manifold'])
        self.assertFalse(actual['is_oriented'])
        self.assertIsNone(actual['volume_m3'])
        actual=topology(BOX,np.vstack([FACES,FACES[0]]))
        self.assertFalse(actual['is_manifold'])
        self.assertGreater(actual['nonmanifold_edges'],0)

    def test_disconnected_boxes_are_not_dropped(self):
        vertices=np.vstack([BOX,BOX+[3000,0,0]])
        actual=topology(vertices,np.vstack([FACES,FACES+8]))
        self.assertTrue(actual['is_solid'])
        self.assertEqual(actual['area_m2'],12)
        self.assertEqual(actual['volume_m3'],2)

    def test_quad_uses_shorter_diagonal_and_rejects_bad_coordinates(self):
        vertices=np.array([[0,0,0],[4,0,0],[4,4,2],[0,1,0]],float)
        triangles=triangulate(vertices,np.array([[0,1,2,3]],dtype=np.int64))
        self.assertEqual(triangles.tolist(),[[0,1,3],[1,2,3]])
        vertices[0,0]=np.nan
        with self.assertRaises(ValueError):topology(vertices,np.array([[0,1,2,3]]))


class SourceReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.native=r.File3dm.Read(str(ROOT/'model'/'vmu_site_future_native.3dm'))
        cls.quality=json.loads((ROOT/'model'/'vmu_site_future_geometry.json').read_text())
        cls.transom=next(o for o in cls.native.Objects if o.Attributes.Name=='VMU01|Middle transom')
        cls.row=next(x for x in cls.quality['components'] if x['component_id']==str(cls.transom.Attributes.Id))

    def subset(self):
        doc=r.File3dm();doc.Objects.AddMesh(self.transom.Geometry,self.transom.Attributes)
        quality={'components':[copy.deepcopy(self.row)],'mesh_components':1,'closed':1,
                 'open':0,'solid':0,'invalid':0,'volume_available':0,'generated_uv_objects':1}
        return doc,quality

    def test_actual_source_all_235_preserves_106_open_surfaces(self):
        with (ROOT/'model'/'vmu_site_future_geometry.csv').open(encoding='utf-8-sig',newline='') as stream:
            records=list(csv.DictReader(stream))
        errors,_,actual,_,_=verify_geometry(self.native,self.quality,records)
        self.assertEqual(errors,[])
        self.assertEqual(sum(not x['is_closed'] for x in actual.values()),106)
        self.assertEqual(sum(x['is_solid'] for x in actual.values()),101)

    def test_transom_report_and_csv_forgery_cannot_supply_volume(self):
        doc,quality=self.subset();row=quality['components'][0]
        self.assertFalse(topology(*arrays(self.transom.Geometry))['is_manifold'])
        for field in ('is_closed','is_manifold','is_oriented','is_solid'):row[field]=True
        row['volume_m3']=.02251787432;row['volume_reason']='solid mesh; geometric volume'
        quality['solid']=quality['volume_available']=1
        errors,*_=verify_geometry(doc,quality,csv_records(quality))
        self.assertTrue(any('actual non-solid' in x for x in errors),errors)
        self.assertTrue(any('is_manifold' in x for x in errors),errors)
        self.assertFalse(any('CSV/JSON disagreement' in x for x in errors),errors)

    def test_csv_missing_duplicate_and_json_duplicate_rejected(self):
        doc,quality=self.subset();records=csv_records(quality)
        self.assertEqual(verify_geometry(doc,quality,records)[0],[])
        for changed in ([],records+records):
            with self.subTest(csv_rows=len(changed)):
                self.assertTrue(verify_geometry(doc,quality,changed)[0])
        quality['components']*=2
        self.assertTrue(any('Duplicate geometry' in x for x in verify_geometry(doc,quality,records)[0]))

    def test_nan_metrics_and_boolean_flags_rejected(self):
        doc,quality=self.subset()
        quality['components'][0]['area_m2']=float('nan')
        quality['components'][0]['is_manifold']=0
        quality['components'][0]['volume_m3']=float('inf')
        errors,*_=verify_geometry(doc,quality,csv_records(quality))
        self.assertTrue(any('Nonfinite' in x for x in errors))
        self.assertTrue(any('is_manifold' in x for x in errors))
        self.assertTrue(any('actual non-solid' in x for x in errors))


if __name__=='__main__':unittest.main()
