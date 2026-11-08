"""Architecture regression: production source must not expose raw financial entrypoints.

Raw WalletLedger/RoundService construction remains intentionally available to
low-level unit tests and local-only load tools. This test limits its inventory
to shipped Python source plus the development server entrypoint.
"""
import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
PROTECTED = {
    "ganesha/game/engine.py",
    "ganesha/game/events.py",
    "ganesha/rgs/service.py",
    "ganesha/rgs/http_api.py",
    "ganesha/wallet/ledger.py",
}


def _called_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _production_modules():
    modules = [(path, path.relative_to(SRC).as_posix())
               for path in SRC.rglob("*.py")]
    modules.append((ROOT / "dev_server.py", "dev_server.py"))
    return [(path, rel) for path, rel in modules
            if rel not in PROTECTED]


class RawFinancialEntrypointsWorker3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.trees = {
            rel: ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for path, rel in _production_modules()
        }

    def _calls(self, name):
        return [(rel, node) for rel, tree in self.trees.items()
                for node in ast.walk(tree)
                if isinstance(node, ast.Call) and _called_name(node.func) == name]

    def test_round_service_is_constructed_only_with_guarded_wallet(self):
        calls = self._calls("RoundService")
        self.assertEqual([rel for rel, _ in calls], ["ganesha/rgs/standard_startup_v1.py"])
        self.assertIsInstance(calls[0][1].args[0], ast.Name)
        self.assertEqual(calls[0][1].args[0].id, "guarded_wallet")

    def test_production_source_does_not_instantiate_raw_wallet_ledger(self):
        self.assertEqual(self._calls("WalletLedger"), [])

    def test_only_development_preview_uses_raw_http_factory_and_disables_round_api(self):
        calls = self._calls("create_server")
        self.assertEqual([rel for rel, _ in calls], ["dev_server.py"])
        kwargs = {item.arg: item.value for item in calls[0][1].keywords}
        self.assertIn("enable_round_api", kwargs)
        self.assertIsInstance(kwargs["enable_round_api"], ast.Constant)
        self.assertIs(kwargs["enable_round_api"].value, False)

    def test_guarded_http_factory_is_called_only_from_standard_startup(self):
        calls = self._calls("create_guarded_server")
        self.assertEqual([rel for rel, _ in calls], ["ganesha/rgs/standard_startup_v1.py"])
        kwargs = {item.arg: item.value for item in calls[0][1].keywords}
        self.assertIsInstance(kwargs.get("game_engine"), ast.Name)
        self.assertEqual(kwargs["game_engine"].id, "guarded_engine")


if __name__ == "__main__":
    unittest.main()
