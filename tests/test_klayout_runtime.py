import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lumen.core.klayout_runtime import KLayoutInstallResult, KLayoutRuntimeManager


class KLayoutRuntimeManagerTest(unittest.TestCase):
    def test_set_and_reload_active_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake_exe = Path(tmp) / "klayout_app.exe"
            fake_exe.write_text("", encoding="utf-8")
            with patch("lumen.core.klayout_runtime.shutil.which") as mock_which, patch(
                "lumen.core.klayout_runtime.subprocess.run"
            ) as mock_run:
                mock_which.side_effect = lambda name: (
                    str(fake_exe) if name in ("klayout", "klayout_app", str(fake_exe)) else None
                )
                mock_run.return_value = subprocess.CompletedProcess(
                    args=["klayout", "-v"], returncode=0, stdout="KLayout 0.30.4", stderr=""
                )

                mgr = KLayoutRuntimeManager(tmp)
                self.assertTrue(mgr.set_active_executable("klayout"))
                self.assertIn("klayout_app.exe", mgr.get_active_executable().lower())

                # Reload manager from disk and ensure config persisted.
                mgr2 = KLayoutRuntimeManager(tmp)
                self.assertIn("klayout_app.exe", mgr2.get_active_executable().lower())

    def test_discover_installations_includes_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake_exe = Path(tmp) / "klayout.exe"
            fake_exe.write_text("", encoding="utf-8")
            with patch("lumen.core.klayout_runtime.shutil.which") as mock_which, patch(
                "lumen.core.klayout_runtime.subprocess.run"
            ) as mock_run:
                mock_which.side_effect = lambda name: (
                    str(fake_exe) if name in ("klayout", "klayout.exe", str(fake_exe)) else None
                )
                mock_run.return_value = subprocess.CompletedProcess(
                    args=["klayout", "-v"], returncode=0, stdout="KLayout 0.30.8", stderr=""
                )

                mgr = KLayoutRuntimeManager(tmp)
                found = mgr.discover_installations()
                self.assertTrue(found)
                self.assertTrue(any(item.version.startswith("0.30") for item in found))

                summary = mgr.runtime_summary()
                self.assertIn("discovered", summary)
                self.assertTrue(summary["config_path"].endswith(".lumen_klayout.json"))
                self.assertIn("runtime_available", summary)

    def test_ensure_runtime_without_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = KLayoutRuntimeManager(tmp)
            with patch.object(mgr, "get_active_executable", return_value=""):
                ok, msg = mgr.ensure_runtime(auto_install=False)
                self.assertFalse(ok)
                self.assertIn("not installed", msg.lower())

    def test_ensure_runtime_with_auto_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = KLayoutRuntimeManager(tmp)
            with patch.object(mgr, "get_active_executable", return_value=""), patch.object(
                mgr,
                "install_if_missing",
                return_value=KLayoutInstallResult(
                    success=True,
                    message="Installed",
                    executable=r"C:\Tools\klayout_app.exe",
                    method="portable",
                    logs=[],
                ),
            ):
                ok, msg = mgr.ensure_runtime(auto_install=True)
                self.assertTrue(ok)
                self.assertEqual(msg, "Installed")

    def test_resolve_portable_urls_from_choco_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = KLayoutRuntimeManager(tmp)
            script = """
            $packageArgs = @{
              url64 = 'https://www.klayout.org/downloads/Windows/klayout-0.30.8-win64-install.exe'
              url = 'https://www.klayout.org/downloads/Windows/klayout-0.30.8-win32-install.exe'
            }
            """
            with patch.object(mgr, "_fetch_choco_install_script", return_value=script):
                urls = mgr._resolve_windows_portable_urls()
                self.assertIn(
                    "https://www.klayout.org/downloads/Windows/klayout-0.30.8-win64.zip",
                    urls,
                )
                self.assertIn(
                    "https://www.klayout.org/downloads/Windows/klayout-0.30.8-win32.zip",
                    urls,
                )

    def test_find_local_windows_installer(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = KLayoutRuntimeManager(tmp)
            tools_dir = Path(tmp) / "tools"
            tools_dir.mkdir(parents=True, exist_ok=True)
            installer = tools_dir / "klayout-0.30.8-win64-install.exe"
            installer.write_text("", encoding="utf-8")
            with patch("lumen.core.klayout_runtime.Path.cwd", return_value=Path(tmp)):
                found = mgr._find_local_windows_installer()
                self.assertTrue(found.lower().endswith("klayout-0.30.8-win64-install.exe"))


if __name__ == "__main__":
    unittest.main()
