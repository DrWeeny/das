# -*- coding: utf8 -*-
import os
import sys
import json
import unittest
import das               # pylint: disable=import-error
from das import ui       # the framework-neutral UI layer (no Qt)


class TestCase(unittest.TestCase):
   @classmethod
   def setUpClass(cls):
      os.environ["DAS_SCHEMA_PATH"] = os.path.abspath(os.path.dirname(__file__))
      das.load_schemas(force=True)

   @classmethod
   def tearDownClass(cls):
      del(os.environ["DAS_SCHEMA_PATH"])

   # -- the overlay must never drag in a Qt binding -------------------------
   def testUiLayerIsQtFree(self):
      ui.ui_for("uidemo.Doc")
      ui.render("uidemo.Doc", framework="web")
      for mod in ("PySide2", "PySide6", "Qt"):
         self.assertNotIn(mod, sys.modules,
                          "das.ui pulled in %s" % mod)

   # -- ui_for walks the schema, keyed by das type name ---------------------
   def testUiForWalksNamedTypes(self):
      u = ui.ui_for("uidemo.Doc")
      self.assertEqual(u.root, "uidemo.Doc")
      self.assertIn("uidemo.Doc", u.types())
      self.assertIn("uidemo.Item", u.types())          # reached via Sequence
      self.assertEqual(set(u["uidemo.Doc"].order()),
                       {"title", "body", "count", "enabled", "tags", "items"})

   # -- convention defaults (no annotation) ---------------------------------
   def testDefaultWidgetConvention(self):
      doc = das.get_schema_type("uidemo.Doc")
      self.assertEqual(ui.default_widget(doc["enabled"]), "checkbox")
      self.assertEqual(ui.default_widget(doc["count"]), "spinbox")
      self.assertEqual(ui.default_widget(doc["tags"]), "list")
      self.assertEqual(ui.default_widget(doc["title"]), "lineedit")
      self.assertEqual(ui.default_widget(doc["items"]), "list")

   # -- set_widget + options + label + order --------------------------------
   def testCustomiseOverlay(self):
      u = ui.ui_for("uidemo.Doc")
      u.body.set_widget("multiline", rows=6)
      u.title.set_label("Title").set_required(True)
      u.order(["title", "body", "count"])
      self.assertEqual(u.body.widget, "multiline")
      self.assertEqual(u.body.options["rows"], 6)
      self.assertEqual(u.title.label, "Title")
      self.assertTrue(u.title.required)
      self.assertEqual(u["uidemo.Doc"].order()[:3], ["title", "body", "count"])

   # -- to_dict / from_dict round-trip (named widgets survive) --------------
   def testSerialiseRoundTrip(self):
      u = ui.ui_for("uidemo.Doc")
      u.body.set_widget("multiline", rows=4)
      u.title.set_label("Title")
      u.order(["title", "body"])
      d = json.loads(json.dumps(u.to_dict()))     # must be JSON-clean
      u2 = ui.UiSchema.from_dict(d)
      doc2 = u2["uidemo.Doc"]
      self.assertEqual(doc2.field("body").widget, "multiline")
      self.assertEqual(doc2.field("body").options.get("rows"), 4)
      self.assertEqual(doc2.field("title").label, "Title")
      self.assertEqual(doc2.order()[:2], ["title", "body"])

   # -- web renderer resolves "auto" via convention -------------------------
   def testWebRenderResolvesAuto(self):
      u = ui.ui_for("uidemo.Doc")
      u.body.set_widget("multiline", rows=5)
      web = ui.render("uidemo.Doc", u, framework="web")
      fields = web["uiSchema"]["uidemo.Doc"]["fields"]
      self.assertEqual(fields["enabled"]["widget"], "checkbox")   # auto -> convention
      self.assertEqual(fields["count"]["widget"], "spinbox")
      self.assertEqual(fields["tags"]["widget"], "list")
      self.assertEqual(fields["body"]["widget"], "multiline")     # explicit
      self.assertEqual(fields["body"]["options"]["rows"], 5)

   # -- a raw callable widget is Qt-only: web falls back to the type default -
   def testCustomWidgetFallsBackForWeb(self):
      u = ui.ui_for("uidemo.Doc")
      u.title.set_widget(lambda t: None)        # raw callable -> "custom"
      self.assertEqual(u.title.widget, "custom")
      web = ui.render("uidemo.Doc", u, framework="web")
      # title is a String -> falls back to lineedit (not "custom") for the web
      self.assertEqual(web["uiSchema"]["uidemo.Doc"]["fields"]["title"]["widget"],
                       "lineedit")

   # -- unknown framework is a clear error ----------------------------------
   def testUnknownFramework(self):
      with self.assertRaises(ValueError):
         ui.render("uidemo.Doc", framework="nope")