# -*- coding: utf8 -*-
import os
import unittest
import das # pylint: disable=import-error

class TestCase(unittest.TestCase):
   TestDir = None
   OutputFile = None

   @classmethod
   def setUpClass(cls):
      cls.TestDir = os.path.abspath(os.path.dirname(__file__))
      cls.OutputFile = cls.TestDir + "/out.alias"
      os.environ["DAS_SCHEMA_PATH"] = cls.TestDir

   def setUp(self):
      self.addCleanup(self.cleanUp)

   def tearDown(self):
      pass

   def cleanUp(self):
      pass

   @classmethod
   def tearDownClass(cls):
      del(os.environ["DAS_SCHEMA_PATH"])
      if os.path.isfile(cls.OutputFile):
         os.remove(cls.OutputFile)

   # Test functions

   def test1(self):
      r = das.make_default("testalias.MyStruct")
      r.margin = "both"
      das.write(r, self.OutputFile)

   def test2(self):
      r0 = das.make("testalias.MyStruct", defaultMargin="both")
      r1 = das.read(self.OutputFile)
      self.assertEqual(r0, r1)
      self.assertEqual(r0.margin, r0.defaultMargin)
      self.assertEqual(r1.margin, r1.defaultMargin)
      with self.assertRaises(das.ValidationError):
         r0.defaultMargin = "any"
      r0.defaultMargin = "none"
      self.assertEqual(r0.margin, "none")

   def test3(self):
      # bulk update through an alias key: _update used to translate the key
      # before reading the source dict with it, raising KeyError('margin')
      r = das.make_default("testalias.MyStruct")
      r.update({"defaultMargin": "vertical"})
      self.assertEqual(r.margin, "vertical")
      # ... and through the aliased name itself
      r.update({"margin": "horizontal"})
      self.assertEqual(r.defaultMargin, "horizontal")
      # key/value pair sequences take the same path
      r.update([("defaultMargin", "both")])
      self.assertEqual(r.margin, "both")

   def test4(self):
      # conform(fill=True) used to default the alias key as well as the field
      # it points at, and then reject its own output with
      # 'Conflicting alias values'
      st = das.get_schema_type("testalias.MyStruct")
      self.assertEqual(st.conform({"margin": "both"}, fill=True).margin, "both")
      self.assertEqual(st.conform({"defaultMargin": "both"}, fill=True).margin, "both")
      self.assertEqual(st.conform({}, fill=True).margin, "none")
      # a real conflict is still caught
      with self.assertRaises(das.ValidationError):
         st.conform({"margin": "both", "defaultMargin": "none"}, fill=True)

