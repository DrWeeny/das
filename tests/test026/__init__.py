# -*- coding: utf8 -*-
import os
import glob
import unittest
import das # pylint: disable=import-error
from das.schematypes import (Struct, String, Integer, Boolean, Sequence,
                             SchemaType, Optional, Or, Empty)


class TestCase(unittest.TestCase):
   @classmethod
   def setUpClass(cls):
      cls.outdir = os.path.abspath(os.path.dirname(__file__))
      os.environ["DAS_SCHEMA_PATH"] = cls.outdir
      cls._clean_generated()
      das.load_schemas(force=True)

   @classmethod
   def tearDownClass(cls):
      cls._clean_generated()
      del(os.environ["DAS_SCHEMA_PATH"])
      das.load_schemas(force=True)

   @classmethod
   def _clean_generated(cls):
      # every schema this test writes is generated, the directory ships none
      for f in glob.glob(os.path.join(cls.outdir, "*.schema")):
         os.remove(f)

   def _write_and_load(self, filename, **types):
      path = os.path.join(self.outdir, filename)
      das.write_schema(path, **types)
      das.load_schemas(force=True)
      return path

   # Test functions

   def testWriteSchemaAndReload(self):
      typ = Struct(name=String(default="new"),
                   count=Integer(default=3, min=0),
                   enabled=Boolean(default=True))
      self._write_and_load("wr1.schema", Item=typ)
      v = das.make_default("wr1.Item")
      self.assertEqual(v.name, "new")
      self.assertEqual(v.count, 3)
      v.count = 5
      das.validate(v, "wr1.Item")
      with self.assertRaises(das.ValidationError):
         das.get_schema_type("wr1.Item")["count"].validate(-1)

   def testAuthoredFieldOrderPreserved(self):
      typ = Struct(zebra=String(), apple=String(), mango=String())
      self._write_and_load("wr2.schema", Ordered=typ)
      st = das.get_schema_type("wr2.Ordered")
      self.assertEqual(list(st._order), ["zebra", "apple", "mango"])

   def testExplicitOrderStillWins(self):
      typ = Struct(a=String(), b=String(), c=String(), __order__=["c", "a", "b"])
      self._write_and_load("wr3.schema", Ordered=typ)
      st = das.get_schema_type("wr3.Ordered")
      self.assertEqual(list(st._order), ["c", "a", "b"])

   def testUiMetadataRoundTrip(self):
      typ = Struct(title=String(editable=False, description="locked"),
                   secret=String(hidden=True),
                   size=Integer(__properties__={"widget": "slider", "required": True}),
                   note=Optional(String()),
                   link=Or(String(), Empty()))
      self._write_and_load("wr4.schema", Thing=typ)
      st = das.get_schema_type("wr4.Thing")
      self.assertIs(st["title"].editable, False)
      self.assertEqual(st["title"].description, "locked")
      self.assertIs(st["secret"].hidden, True)
      self.assertEqual(st["size"].get_property("widget"), "slider")
      self.assertIs(st["size"].get_property("required"), True)

   def testCrossReferenceRemapped(self):
      dep = Struct(name=String())
      tool = Struct(name=String(),
                    dependencies=Sequence(SchemaType("xr1.Dependency")))
      self._write_and_load("xr1.schema", Dependency=dep, Tool=tool)

      # re-save the loaded types under a new schema name: the internal
      # reference must follow, or validation raises UnknownSchemaError
      types = dict(Dependency=das.get_schema_type("xr1.Dependency"),
                   Tool=das.get_schema_type("xr1.Tool"))
      path = self._write_and_load("xr2.schema", **types)
      with open(path, "r") as f:
         content = f.read()
      self.assertIn("SchemaType('xr2.Dependency'", content)
      self.assertNotIn("xr1.Dependency", content)

      v = das.make_default("xr2.Tool")
      v.dependencies.append(das.make_default("xr2.Dependency"))
      das.validate(v, "xr2.Tool")

   def testSaveGuessesTypename(self):
      typ = Struct(name=String())
      self._write_and_load("sg1.schema", Solo=typ)
      st = das.get_schema_type("sg1.Solo")
      st.save(os.path.join(self.outdir, "sg2.schema"))
      das.load_schemas(force=True)
      das.validate(das.make_default("sg2.Solo"), "sg2.Solo")

   def testSaveUnregisteredRequiresTypename(self):
      typ = Struct(name=String())
      with self.assertRaises(Exception):
         typ.save(os.path.join(self.outdir, "sg3.schema"))

   def testWriteSchemaRequiresTypes(self):
      with self.assertRaises(Exception):
         das.write_schema(os.path.join(self.outdir, "empty.schema"))


if __name__ == "__main__":
   unittest.main()