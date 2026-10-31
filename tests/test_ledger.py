"""INR ledger: no spend before a budget, reserve/settle, cap refusals, raises, failure accounting, locking."""
import threading
import unittest

from helpers import MockCase, hidrogen

from bizzbell import ledger
from bizzbell.errors import BudgetExceeded, UsageError


class LedgerTests(MockCase):
    def setUp(self):
        MockCase.setUp(self)
        self.root = self.make_project(budget=0, doctor=False)
        self.L = ledger.Ledger(self.root)

    def test_refuses_without_budget(self):
        with self.assertRaises(BudgetExceeded) as cm:
            self.L.reserve("image", 4)
        self.assertIn("no budget approved", str(cm.exception))
        self.assertEqual(self.L.entries(), [])

    def test_reserve_settle_and_cap(self):
        ledger.set_cap(self.root, 10, "user said 10")
        a = self.L.reserve("image", 6, model="image-pro", purpose="sheet")
        self.assertEqual(self.L.summary()["reserved_inr"], 6)
        with self.assertRaises(BudgetExceeded):
            self.L.reserve("image", 6)
        self.L.settle(a, 4.0)
        s = self.L.summary()
        self.assertEqual((s["spent_inr"], s["reserved_inr"], s["remaining_inr"]), (4.0, 0, 6.0))
        b = self.L.reserve("image", 6)
        self.L.release(b, "blocked")
        self.assertEqual(self.L.summary()["spent_inr"], 4.0)
        self.assertIsNotNone(self.L.check(7))
        self.assertIsNone(self.L.check(6))

    def test_raise_cap_and_mirror(self):
        ledger.set_cap(self.root, 10)
        s = ledger.raise_cap(self.root, 15, "user approved 15 more")
        self.assertEqual(s["cap_inr"], 25)
        from bizzbell import project
        self.assertEqual(project.load_state(self.root)["spend"]["cap_inr"], 25)
        with self.assertRaises(UsageError):
            ledger.raise_cap(self.root, -1)
        with self.assertRaises(UsageError):
            ledger.set_cap(self.root, -5)

    def test_call_settles_actual_from_reply(self):
        ledger.set_cap(self.root, 50)
        out = self.L.call("image", lambda: hidrogen.image("x"), model="image-pro", quote_params={})
        self.assertTrue(out[0].startswith(b"\x89PNG"))
        e = self.L.entries()[-1]
        self.assertEqual((e["reserved_inr"], e["actual_inr"], e["status"]), (4.0, 4.0, "settled"))

    def test_estimate_falls_back_to_rates(self):
        self.mock.set_behaviours(["media404"])
        inr, src = self.L.estimate("video", "video", units=3, quote_params={"seconds": 3})
        self.assertEqual((inr, src), (24.0, "rate"))

    def test_call_releases_on_402_and_block(self):
        ledger.set_cap(self.root, 50)
        self.mock.set_behaviours(["pay402"])
        with self.assertRaises(hidrogen.PaymentRequired):
            self.L.call("image", lambda: hidrogen.image("x"))
        self.mock.set_behaviours(["block"])
        with self.assertRaises(hidrogen.Blocked):
            self.L.call("voice", lambda: hidrogen.tts("x"))
        self.assertEqual([e["status"] for e in self.L.entries()], ["released", "released"])
        self.assertEqual(self.L.summary()["spent_inr"], 0)

    def test_call_counts_uncertain_failures(self):
        ledger.set_cap(self.root, 50)

        def boom():
            raise hidrogen.HidrogenError("could not reach the gateway")
        with self.assertRaises(hidrogen.HidrogenError):
            self.L.call("chat", boom, estimate_inr=2)
        e = self.L.entries()[-1]
        self.assertEqual((e["status"], e["actual_inr"]), ("uncertain", 2))

    def test_parallel_reservations_never_pass_cap(self):
        ledger.set_cap(self.root, 20)
        ok, refused = [], []

        def worker():
            try:
                ok.append(self.L.reserve("image", 3))
            except BudgetExceeded:
                refused.append(1)
        ts = [threading.Thread(target=worker) for _ in range(15)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(len(ok), 6)
        self.assertEqual(len(refused), 9)
        self.assertLessEqual(self.L.summary()["reserved_inr"], 20)

    def test_cost_of(self):
        self.assertEqual(ledger.cost_of({"charged_inr": 1.5}), 1.5)
        self.assertEqual(ledger.cost_of((b"x", {"billing": {"charged_paise": 250}})), 2.5)
        self.assertIsNone(ledger.cost_of((b"x", {})))


if __name__ == "__main__":
    unittest.main()
