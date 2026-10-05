import json
import shutil
import subprocess
import unittest
from pathlib import Path

FORMAT = Path(__file__).resolve().parents[1] / "web" / "format.js"


def run_node(expression):
    script = f"const f = require({json.dumps(str(FORMAT))}); process.stdout.write(JSON.stringify({expression}));"
    return json.loads(subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True).stdout)


@unittest.skipUnless(shutil.which("node"), "node est nécessaire pour tester web/format.js")
class FormatTests(unittest.TestCase):
    def test_escape_neutralises_markup(self):
        escaped = run_node("f.escapeHtml('<img src=x onerror=\"alert(1)\">&\\'')")
        self.assertNotIn("<", escaped)
        self.assertNotIn('"', escaped)
        self.assertEqual(escaped, "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;&amp;&#39;")

    def test_plural_agrees_with_the_count(self):
        self.assertEqual(run_node("[f.plural(0, 'rejet'), f.plural(1, 'rejet'), f.plural(2, 'rejet')]"), ["0 rejet", "1 rejet", "2 rejets"])

    def test_result_text_follows_the_api_response(self):
        message = {"event_id": "flux-203", "route_id": "B7"}
        cases = {
            "accepted_alert": {"status": "accepted", "decision": {"severity": "critical"}},
            "accepted_quiet": {"status": "accepted", "decision": {"severity": "none"}},
            "duplicate": {"status": "duplicate"},
            "rejected": {"status": "rejected", "error": "delay_seconds must be a finite positive number or zero"},
        }
        texts = run_node(f"Object.fromEntries(Object.entries({json.dumps(cases)}).map(([k, v]) => [k, f.describeResult({json.dumps(message)}, v)]))")
        self.assertEqual(texts["accepted_alert"], "flux-203, ligne B7 : accepté, alerte critique ouverte.")
        self.assertEqual(texts["accepted_quiet"], "flux-203, ligne B7 : accepté, rien à signaler.")
        self.assertEqual(texts["duplicate"], "flux-203, ligne B7 : relecture absorbée, aucun doublon écrit.")
        self.assertIn("rejeté, delay_seconds", texts["rejected"])

    def test_run_summary_counts_real_statuses(self):
        summary = run_node("f.summarizeRun(['accepted', 'accepted', 'duplicate', 'rejected'])")
        self.assertEqual(summary, "Flux terminé : 4 messages, 2 acceptés, 1 doublon, 1 rejet.")


if __name__ == "__main__":
    unittest.main()
