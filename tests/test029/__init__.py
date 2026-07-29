# -*- coding: utf8 -*-
import os
import unittest
import das # pylint: disable=import-error
from das import ui # pylint: disable=import-error

# Qt is imported lazily, inside setUpClass -- see the note in tests/test028.


class TestCase(unittest.TestCase):
   @classmethod
   def setUpClass(cls):
      os.environ["DAS_SCHEMA_PATH"] = os.path.abspath(os.path.dirname(__file__))
      das.load_schemas(force=True)
      cls._platform = os.environ.get("QT_QPA_PLATFORM")
      os.environ["QT_QPA_PLATFORM"] = "offscreen"
      try:
         from das import qtform # pylint: disable=import-error
      except ImportError as e:
         raise unittest.SkipTest(f"no Qt binding ({e})")
      cls.qtform = qtform
      cls.app = (qtform.QtWidgets.QApplication.instance()
                 or qtform.QtWidgets.QApplication([]))
      cls.stype = das.get_schema_type("ui029.Doc")

   @classmethod
   def tearDownClass(cls):
      del(os.environ["DAS_SCHEMA_PATH"])
      if cls._platform is None:
         os.environ.pop("QT_QPA_PLATFORM", None)
      else:
         os.environ["QT_QPA_PLATFORM"] = cls._platform

   def setUp(self):
      # Qt parents own their children: a StructForm nobody holds is collected,
      # and every widget taken out of it dies with it. Real code keeps the form
      # (it is in a layout); a test has to say so explicitly.
      self._alive = []

   def _form(self, *table_fields, ui_schema=None):
      u = ui_schema
      if u is None:
         u = ui.ui_for("ui029.Doc")
         for name in table_fields:
            u[u.root].field(name).set_widget("table")
      form = self.qtform.StructForm(self.stype, ui_schema=u)
      self._alive.append(form)
      return form

   # -- "table" is in the neutral vocabulary, but never a default ------------
   def testTableIsOptIn(self):
      self.assertIn("table", ui.WIDGETS)
      doc = das.get_schema_type("ui029.Doc")
      for field in ("named_layers", "layer_list"):
         self.assertNotEqual(ui.default_widget(doc[field]), "table")
      form = self._form()   # no hint at all
      self.assertIsInstance(form.field("named_layers"), self.qtform.DictField)
      self.assertIsInstance(form.field("layer_list"), self.qtform.StructListField)

   # -- Dict(String, Struct): a key column, then one column per field --------
   def testDictTableRoundTrip(self):
      table = self._form("named_layers").field("named_layers")
      self.assertIsInstance(table, self.qtform.StructTableField)
      self.assertTrue(table.keyed)
      self.assertEqual([c[0] for c in table._columns],
                       ["name", "renderer", "start", "enabled"])

      data = {"char": {"name": "char", "renderer": "vray",
                       "start": 1001, "enabled": True},
              "fx": {"name": "fx", "renderer": "arnold",
                     "start": 1050, "enabled": False}}
      table.set_value(data)
      self.assertEqual(table.get_value(), data)

   # -- Sequence(Struct): same, positional (no key column) ------------------
   def testSequenceTableRoundTrip(self):
      table = self._form("layer_list").field("layer_list")
      self.assertIsInstance(table, self.qtform.StructTableField)
      self.assertFalse(table.keyed)

      data = [{"name": "char", "renderer": "vray", "start": 1001, "enabled": True},
              {"name": "fx", "renderer": "arnold", "start": 1050, "enabled": False}]
      table.set_value(data)
      self.assertEqual(table.get_value(), data)

   # -- add / remove, and removing the RIGHT row ----------------------------
   def testAddAndRemoveRows(self):
      table = self._form("layer_list").field("layer_list")
      table.set_value([{"name": "a"}, {"name": "b"}, {"name": "c"}])
      self.assertEqual([r["name"] for r in table.get_value()], ["a", "b", "c"])

      table._add_row()
      self.assertEqual(len(table.get_value()), 4)

      # remove the middle row: indices below it shift, so the button must be
      # located at click time, not captured when the row was built
      last_col = table._table.columnCount() - 1
      table._remove(table._table.cellWidget(1, last_col))
      self.assertEqual([r["name"] for r in table.get_value()], ["a", "c", ""])

   # -- a column keeps the widget its das type implies -----------------------
   def testColumnWidgetsComeFromTheType(self):
      table = self._form("layer_list").field("layer_list")
      table.set_value([{"name": "char"}])
      cell = table._table.cellWidget(0, 1)          # "renderer": String(choices)
      self.assertIsInstance(cell._inner, self.qtform.QComboBox)
      cell = table._table.cellWidget(0, 3)          # "enabled": Boolean
      self.assertIsInstance(cell._inner, self.qtform.QCheckBox)

   # -- a hint on a non-flat element type is ignored, not honoured badly -----
   def testNestedElementFallsBack(self):
      form = self._form("nested")
      self.assertIsInstance(form.field("nested"), self.qtform.DictField)

   # -- the overlay still drives columns: hidden fields, order, labels -------
   def testOverlayShapesColumns(self):
      u = ui.ui_for("ui029.Doc")
      u.layer_list.set_widget("table")
      layer = u["ui029.Layer"]
      layer.field("start").hide()
      layer.field("renderer").set_label("engine")
      layer.order(["renderer", "name", "enabled"])
      table = self._form(ui_schema=u).field("layer_list")

      self.assertEqual([c[0] for c in table._columns],
                       ["renderer", "name", "enabled"])
      self.assertEqual(table._table.horizontalHeaderItem(0).text(), "engine")
      table.set_value([{"name": "char", "renderer": "vray"}])
      self.assertNotIn("start", table.get_value()[0])

   # -- what the table produces is what the schema accepts -------------------
   def testTableDataValidates(self):
      form = self._form("named_layers", "layer_list")
      form.field("layer_list").set_value(
          [{"name": "char", "renderer": "vray", "start": 1001, "enabled": True}])
      form.field("named_layers").set_value(
          {"char": {"name": "char", "renderer": "vray",
                    "start": 1001, "enabled": True}})
      self.assertIsNotNone(self.stype.validate(das.copy(form.get_data())))