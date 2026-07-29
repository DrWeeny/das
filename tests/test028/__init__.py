# -*- coding: utf8 -*-
import os
import unittest
import das # pylint: disable=import-error
from das import ui # pylint: disable=import-error

# NOTE: Qt is imported lazily, inside setUpClass -- never at module import.
# tests/run.py imports every test package *before* running anything, and
# test025.testUiLayerIsQtFree asserts no Qt binding is in sys.modules.


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
      QtWidgets = qtform.QtWidgets
      cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
      cls.stype = das.get_schema_type("ui028.Doc")

   @classmethod
   def tearDownClass(cls):
      del(os.environ["DAS_SCHEMA_PATH"])
      if cls._platform is None:
         os.environ.pop("QT_QPA_PLATFORM", None)
      else:
         os.environ["QT_QPA_PLATFORM"] = cls._platform

   def _form(self, ui_schema=None):
      return self.qtform.StructForm(self.stype, ui_schema=ui_schema)

   # -- the editor returned is the one backing that field -------------------
   def testFieldReturnsEditor(self):
      form = self._form()
      editor = form.field("version")
      self.assertIsNotNone(editor)
      editor.set_value("3.2")
      self.assertEqual(form.get_data()["version"], "3.2")

   def testFieldUnknownKey(self):
      self.assertIsNone(self._form().field("nope"))

   # -- a field hidden by the overlay has no widget at all ------------------
   def testFieldHiddenByOverlay(self):
      u = ui.ui_for("ui028.Doc")
      u.secret.hide()
      form = self._form(ui_schema=u)
      self.assertIsNone(form.field("secret"))
      self.assertNotIn("secret", form.get_data())
      self.assertIsNotNone(form.field("version"))

   # -- the point of the accessor: a signal for one field only --------------
   def testFieldSignalIsPerField(self):
      form = self._form()
      version = form.field("version")
      seen = []
      version.value_changed.connect(lambda: seen.append(version.get_value()))

      form.field("comment").set_value("unrelated edit")
      self.assertEqual(seen, [])

      version.set_value("3.2")
      self.assertEqual(seen[-1], "3.2")