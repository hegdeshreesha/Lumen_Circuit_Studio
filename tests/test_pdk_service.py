import tempfile
import unittest

from lumen.core.pdk_service import clear_registry_cache, get_registry, resolve_workspace


class PDKServiceTest(unittest.TestCase):
    def test_registry_cache_scoped_by_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = resolve_workspace(tmp)
            clear_registry_cache(ws)
            reg_a = get_registry(ws)
            reg_b = get_registry(ws)
            self.assertIs(reg_a, reg_b)
            clear_registry_cache(ws)
            reg_c = get_registry(ws)
            self.assertIsNot(reg_a, reg_c)


if __name__ == "__main__":
    unittest.main()

