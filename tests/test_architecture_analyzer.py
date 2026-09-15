from dataclasses import asdict, replace
from pathlib import Path
import tempfile
import unittest

from noetrium_platform.foundation.governance.architecture import (
    ImportRule,
    analyze_hotspots,
    audit_import_rules,
    package_cycles,
    scan_imports,
)
from noetrium_platform.foundation.governance.architecture.budget import (
    audit_architecture_complexity_budget,
    current_architecture_complexity,
)
from noetrium_platform.foundation.governance.architecture.import_graph import (
    ImportEdge,
    ImportViolation,
    LayerViolation,
)
from noetrium_platform.foundation.governance.architecture.report import (
    ImportViolationRecord,
    LayerViolationRecord,
)
from tests_support import repository_architecture_report


class ArchitectureAnalyzerTests(unittest.TestCase):
    def test_current_tree_has_no_forbidden_imports_or_cycles(self):
        report=repository_architecture_report()
        self.assertEqual(report.import_violations,())
        self.assertEqual(report.package_cycles,())
        self.assertEqual(report.declared_authority_violations,())
        self.assertEqual(report.architecture_budget_violations,())
        self.assertEqual(len(report.report_sha256),64)


    def test_working_tree_budget_compares_against_explicit_head_reference(self):
        root = Path(__file__).resolve().parents[1]
        reference = current_architecture_complexity(import_edges=0)
        current, evaluated, violations = audit_architecture_complexity_budget(
            root, import_edges=0, working_tree_reference=reference
        )
        self.assertEqual(current, reference)
        self.assertEqual(violations, ())
        self.assertIsNotNone(evaluated)
        assert evaluated is not None
        self.assertEqual(evaluated.limits, reference)
        self.assertNotEqual(evaluated.baseline.complexity, reference)

        tighter = replace(reference, authorities=reference.authorities - 1)
        _current, _evaluated, violations = audit_architecture_complexity_budget(
            root, import_edges=0, working_tree_reference=tighter
        )
        self.assertEqual(tuple(row.dimension for row in violations), ("authorities",))

    def test_report_violation_records_preserve_flat_json_shape(self):
        edge=ImportEdge("noetrium_platform.a","projects.b","noetrium_platform/a.py",7)
        import_row=ImportViolationRecord.from_violation(ImportViolation(edge,"no"))
        layer_row=LayerViolationRecord.from_violation(
            LayerViolation(edge,"api","runtime","layer violation")
        )
        self.assertEqual(asdict(import_row),{
            "source":"noetrium_platform.a","target":"projects.b",
            "path":"noetrium_platform/a.py","line":7,"reason":"no",
        })
        self.assertEqual(asdict(layer_row),{
            "source":"noetrium_platform.a","target":"projects.b",
            "path":"noetrium_platform/a.py","line":7,
            "source_layer":"api","target_layer":"runtime","reason":"layer violation",
        })

    def test_rule_reports_exact_source_line(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); (root/"noetrium_platform"/"x").mkdir(parents=True); (root/"projects"/"m").mkdir(parents=True)
            (root/"noetrium_platform"/"__init__.py").write_text(""); (root/"projects"/"__init__.py").write_text("")
            p=root/"noetrium_platform"/"x"/"a.py"; p.write_text("from projects.m import y\n")
            edges=scan_imports(root); v=audit_import_rules(edges,(ImportRule("noetrium_platform","projects","no"),))
            self.assertEqual(v[0].edge.line,1); self.assertIn("a.py",v[0].edge.path)

    def test_cycle_detection_is_physical(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); (root/"noetrium_platform"/"a").mkdir(parents=True); (root/"noetrium_platform"/"b").mkdir(parents=True)
            for p in (root/"noetrium_platform"/"__init__.py",root/"noetrium_platform"/"a"/"__init__.py",root/"noetrium_platform"/"b"/"__init__.py"): p.write_text("")
            (root/"noetrium_platform"/"a"/"x.py").write_text("from noetrium_platform.b import y\n")
            (root/"noetrium_platform"/"b"/"y.py").write_text("from noetrium_platform.a import x\n")
            self.assertTrue(package_cycles(scan_imports(root),depth=2))

    def test_hotspot_analysis_surfaces_large_branchy_module(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); (root/"projects").mkdir(); (root/"projects"/"__init__.py").write_text(""); (root/"projects"/"x.py").write_text("def f(x):\n"+"    if x: x+=1\n"*30+"    return x\n")
            rows=analyze_hotspots(root)
            self.assertGreater(rows[0].branches,20)
            self.assertGreater(rows[0].score,rows[0].physical_lines)


if __name__=='__main__': unittest.main()
