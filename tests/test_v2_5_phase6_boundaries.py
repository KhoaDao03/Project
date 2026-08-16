"""Static boundaries for the V2.5 generic routing cleanup."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APPLICATION = ROOT / "src/elly/application"


class Phase6RoutingBoundaryTests(unittest.TestCase):
    def test_generic_interpreter_and_router_have_no_optional_capability_literals(self) -> None:
        sources = {
            name: (APPLICATION / name).read_text(encoding="utf-8")
            for name in ("routing.py", "catalog_routing.py")
        }
        for name, source in sources.items():
            with self.subTest(module=name):
                for literal in ('"web_research"', "'web_research'", '"coding"', "'coding'", '"research"', "'research'", '"stock_analysis"', "'stock_analysis'"):
                    self.assertNotIn(literal, source)
                self.assertNotIn("_ROUTE_CAPABILITIES", source)
                self.assertNotIn("_LEGACY_OPERATIONS", source)

    def test_legacy_routing_modules_and_maps_are_removed(self) -> None:
        compatibility_source = (APPLICATION / "route_compatibility.py").read_text(
            encoding="utf-8"
        )
        self.assertFalse((APPLICATION / "legacy_routing.py").exists())
        self.assertFalse((APPLICATION / "intent.py").exists())
        self.assertNotIn("_LEGACY_ROUTE_BY_CAPABILITY", compatibility_source)

    def test_catalog_module_has_no_executable_or_storage_imports(self) -> None:
        tree = ast.parse(
            (APPLICATION / "catalog_routing.py").read_text(encoding="utf-8")
        )
        imported = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
        forbidden = ("provider", "repository", "composition", "sqlite", "handler")
        self.assertFalse(
            [module for module in imported if any(word in module.casefold() for word in forbidden)]
        )


if __name__ == "__main__":
    unittest.main()
