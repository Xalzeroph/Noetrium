import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from noetrium_platform.foundation.governance.release.runtime.packager import ReleasePackager
from noetrium_platform.foundation.governance.release.runtime.manifest import build_release_manifest
from noetrium_platform.foundation.governance.release.runtime.project_metadata import load_project_metadata


class ReleaseVersionAuthorityV102Tests(unittest.TestCase):
    def test_real_source_tree_manifest_uses_pyproject_version(self):
        root=Path(__file__).resolve().parents[1]
        metadata=load_project_metadata(root,allow_unversioned=False)
        manifest=build_release_manifest(root)
        self.assertRegex(metadata.version, r"^\d+\.\d+\.\d+$")
        self.assertEqual(manifest.platform_code_version,metadata.version)
        self.assertEqual(manifest.python_requires,metadata.python_requires)

    def test_packager_no_longer_injects_stale_default_version(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/"src"; root.mkdir()
            (root/"pyproject.toml").write_text(
                '[project]\nname="x"\nversion="9.8.7"\nrequires-python=">=3.12"\n',encoding="utf-8"
            )
            (root/"a.py").write_text("x=1\n",encoding="utf-8")
            package=ReleasePackager().build(root,Path(td)/"release.zip")
            with zipfile.ZipFile(package.zip_path) as zf:
                manifest=json.loads(zf.read("RELEASE_MANIFEST.json"))
            self.assertEqual(manifest["platform_code_version"],"9.8.7")
            self.assertEqual(manifest["python_requires"],">=3.12")

    def test_synthetic_tree_is_explicitly_unversioned_not_fake_versioned(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); (root/"a.txt").write_text("x")
            self.assertEqual(build_release_manifest(root).platform_code_version,"unversioned")


if __name__ == "__main__":
    unittest.main()
