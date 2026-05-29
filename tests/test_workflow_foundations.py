import tempfile
import unittest

from lumen.core.config_view import ConfigView, ConfigViewManager, ViewBinding
from lumen.core.database import LibraryDatabase
from lumen.core.run_plan import RunPlan, RunPlanExecutor
from lumen.core.ade_engine import ADESession


class WorkflowFoundationsTest(unittest.TestCase):
    def test_config_view_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = ConfigViewManager(tmp)
            cfg = ConfigView(
                name="top_cfg",
                top_library="work",
                top_cell="top",
                bindings=[ViewBinding("work", "amp", "extracted")],
            )
            mgr.upsert(cfg)
            loaded = mgr.get("top_cfg")
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.resolve("work", "amp"), "extracted")
            self.assertEqual(loaded.resolve("work", "other"), "schematic")

    def test_run_plan_apply(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = LibraryDatabase(tmp)
            db.create_library("work")
            db.create_cell("work", "top")
            db.save_view("work", "top", "schematic", {
                "type": "schematic",
                "name": "top",
                "library": "work",
                "instances": [],
                "wires": [],
                "labels": [],
                "pins": [],
            })
            session = ADESession(db, "work", "top")
            plan = RunPlan(
                name="p1",
                analyses=[{"type": "OP", "params": {}}],
                corners=[{"name": "tt", "temperature": 25.0, "voltage": 1.8, "process": "tt"}],
                variables={"VDD": "1.8"},
                simulator="GSPICE",
                timeout=30,
                threads=1,
            )
            ex = RunPlanExecutor(session)
            ex.apply(plan)
            self.assertEqual(session.state.simulator, "GSPICE")
            self.assertEqual(session.state.design_variables.get("VDD"), "1.8")
            self.assertEqual(len(session.state.analyses), 1)
            self.assertEqual(len(session.state.corners), 1)


if __name__ == "__main__":
    unittest.main()

