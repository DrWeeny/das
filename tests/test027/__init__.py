# -*- coding: utf8 -*-
import os
import glob
import unittest
import das # pylint: disable=import-error
from das.schematypes import (Struct, String, Integer, Sequence, Tuple,
                             SchemaType)


class TestCase(unittest.TestCase):
   @classmethod
   def setUpClass(cls):
      cls.outdir = os.path.abspath(os.path.dirname(__file__))
      os.environ["DAS_SCHEMA_PATH"] = cls.outdir
      cls._clean_generated()
      das.load_schemas(force=True)

      job = Struct(renderer=String(default="preview",
                                   choices=["preview", "arnold", "vray"],
                                   strict=False),
                   frame_range=Tuple(Integer(default=1001), Integer(default=1100)),
                   layers=Sequence(SchemaType("render.Layer")))
      layer = Struct(name=String())
      das.write_schema(os.path.join(cls.outdir, "render.schema"),
                       master_types="Job", Job=job, Layer=layer)
      das.write_schema(os.path.join(cls.outdir, "solo.schema"), Only=Struct(x=Integer()))
      das.write_schema(os.path.join(cls.outdir, "multi.schema"),
                       A=Struct(x=Integer()), B=Struct(y=Integer()))

   @classmethod
   def tearDownClass(cls):
      cls._clean_generated()
      del(os.environ["DAS_SCHEMA_PATH"])
      das.load_schemas(force=True)

   @classmethod
   def _clean_generated(cls):
      for f in glob.glob(os.path.join(cls.outdir, "*.schema")):
         os.remove(f)

   # Test functions

   def testLoadSchemaReturnsSchema(self):
      schema = das.load_schema(os.path.join(self.outdir, "render.schema"))
      self.assertEqual(schema.name, "render")
      self.assertEqual(schema.list_types(), ["render.Job", "render.Layer"])

   def testMakeDefaultUsesMasterType(self):
      schema = das.load_schema(os.path.join(self.outdir, "render.schema"))
      job = schema.make_default()
      self.assertEqual(job.renderer, "preview")
      self.assertEqual(tuple(job.frame_range), (1001, 1100))

   def testAssignmentsValidate(self):
      schema = das.load_schema(os.path.join(self.outdir, "render.schema"))
      job = schema.make_default()
      job.renderer = "arnold"
      job.frame_range = [1001, 1035]
      self.assertEqual(tuple(job.frame_range), (1001, 1035))
      with self.assertRaises(das.ValidationError):
         job.frame_range = [1001, "end"]
      with self.assertRaises(das.ValidationError):
         job.renderer = 42

   def testMakeWithKeywords(self):
      schema = das.load_schema(os.path.join(self.outdir, "render.schema"))
      job = schema.make(renderer="vray")
      self.assertEqual(job.renderer, "vray")
      das.validate(job, "render.Job")

   def testExplicitTypeNameWithAndWithoutPrefix(self):
      schema = das.load_schema(os.path.join(self.outdir, "render.schema"))
      self.assertEqual(schema.make_default("Layer").name, "")
      self.assertEqual(schema.make_default("render.Layer").name, "")
      with self.assertRaises(das.UnknownSchemaError):
         schema.make_default("Nope")

   def testSingleTypeNeedsNoMaster(self):
      schema = das.load_schema(os.path.join(self.outdir, "solo.schema"))
      self.assertEqual(schema.make_default().x, 0)

   def testAmbiguousSchemaRaises(self):
      schema = das.load_schema(os.path.join(self.outdir, "multi.schema"))
      self.assertIsNone(schema.default_type())
      with self.assertRaises(Exception):
         schema.make_default()

   def testMissingFileRaises(self):
      with self.assertRaises(Exception):
         das.load_schema(os.path.join(self.outdir, "absent.schema"))

   def testWriteSchemaRejectsUnknownMaster(self):
      with self.assertRaises(Exception):
         das.write_schema(os.path.join(self.outdir, "bad.schema"),
                          master_types="Nope", Only=Struct(x=Integer()))


if __name__ == "__main__":
   unittest.main()