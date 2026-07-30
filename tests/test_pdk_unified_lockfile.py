import unittest
import tempfile
import os
from pathlib import Path
from lumen.core.pdk_unified import PDKInfo, PDKLock, PDKCorner, PDKDevice, DeviceCategory, PDKModelFile


class TestPDKLockfile(unittest.TestCase):
    def test_create_and_load_lockfile(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pdk_info = PDKInfo(
                name="ihp-sg13g2",
                version="1.0.0",
                foundry="IHP",
                corners=[PDKCorner(name="typ")],
                devices=[PDKDevice(name="sg13_lv_nmos", category=DeviceCategory.MOSFET, prefix="M", model="sg13_lv_nmos")],
                model_files=[PDKModelFile(path="models/cornerMOS.lib")],
            )

            lock = PDKLock.create_lockfile(pdk_info, tmpdir)
            self.assertEqual(lock.pdk_name, "ihp-sg13g2")
            self.assertEqual(lock.pdk_version, "1.0.0")

            lock_file = Path(tmpdir) / "lumen.lock"
            self.assertTrue(lock_file.exists())

            loaded_lock = PDKLock.load(str(lock_file))
            self.assertEqual(loaded_lock.pdk_manifest_hash, lock.pdk_manifest_hash)


if __name__ == "__main__":
    unittest.main()
