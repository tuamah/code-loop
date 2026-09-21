"""F1-I5 closure tests: transactional authoritative state (T1A §10.1, AM-24/25/26/29).

The crash and concurrency cases are the point. A store that commits correctly when nothing goes
wrong has not been tested at all — the whole reason §10.1 exists is the half-transition.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import f1_state as st                                                        # noqa: E402

C1, C2 = "sha256:" + "11" * 32, "sha256:" + "22" * 32


class Fixture(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.store = st.AuthoritativeStore(Path(self.dir.name) / "state.json")

    def reopen(self):
        """A fresh process's view: nothing in memory, only what reached disk."""
        return st.AuthoritativeStore(Path(self.dir.name) / "state.json")


class AtomicityTests(Fixture):
    def test_a_committed_transition_is_durable(self):
        with self.store.transaction() as tx:
            tx.assert_head("registry", "")
            tx.set_head("registry", C1, tx.allocate_epoch("registry"))
        self.assertEqual(self.reopen().head("registry"), (C1, 1))

    def test_an_aborted_transaction_leaves_nothing(self):
        tx = self.store.transaction()
        tx.set_head("registry", C1, 1)
        tx.consume_authorization("auth-1")
        tx.abort()
        self.assertIsNone(self.reopen().head("registry"))
        self.assertFalse(self.reopen().is_consumed("auth-1"))

    def test_an_exception_inside_the_block_aborts_everything(self):
        with self.assertRaises(ValueError):
            with self.store.transaction() as tx:
                tx.set_head("registry", C1, 1)
                tx.consume_authorization("auth-1")
                raise ValueError("the last step failed")
        self.assertIsNone(self.reopen().head("registry"))
        self.assertFalse(self.reopen().is_consumed("auth-1"))

    def test_the_composite_transition_is_all_or_nothing(self):
        """validate heads + consume authorization + allocate epoch + install = ONE commit."""
        with self.store.transaction() as tx:
            tx.assert_head("policy", "")
            tx.set_head("policy", C1, tx.allocate_epoch("policy"))
        with self.assertRaises(st.StateError):
            with self.store.transaction() as tx:
                tx.assert_head("registry", "")
                tx.assert_head("policy", C1)
                tx.consume_authorization("auth-9")
                tx.set_head("registry", C2, tx.allocate_epoch("registry"))
                tx.set_head("policy", C2, 99)           # the LAST step fails
        after = self.reopen()
        self.assertIsNone(after.head("registry"), "an earlier write survived a later failure")
        self.assertFalse(after.is_consumed("auth-9"),
                         "the authorization was consumed by a transition that never committed")
        self.assertEqual(after.head("policy"), (C1, 1), "the policy head moved")


class CrashTests(Fixture):
    """A crash is simulated where a real one hurts: around the publishing rename."""

    def test_crash_before_commit_leaves_the_old_state(self):
        with self.store.transaction() as tx:
            tx.set_head("registry", C1, 1)
        tx = self.store.transaction()
        tx.consume_authorization("auth-1")
        tx.set_head("registry", C2, 2)
        del tx                                            # the process dies here
        self.assertEqual(self.reopen().head("registry"), (C1, 1))
        self.assertFalse(self.reopen().is_consumed("auth-1"))

    def test_crash_during_commit_publishes_nothing(self):
        with self.store.transaction() as tx:
            tx.set_head("registry", C1, 1)
        real_replace = os.replace

        def die(*args, **kwargs):
            raise OSError("power lost mid-rename")

        os.replace = die
        try:
            with self.assertRaises(OSError):
                with self.store.transaction() as tx:
                    tx.consume_authorization("auth-1")
                    tx.set_head("registry", C2, 2)
                    tx.commit()
        finally:
            os.replace = real_replace
        after = self.reopen()
        self.assertEqual(after.head("registry"), (C1, 1), "a half-written commit was published")
        self.assertFalse(after.is_consumed("auth-1"))

    def test_the_state_file_is_never_left_half_written(self):
        with self.store.transaction() as tx:
            tx.set_head("registry", C1, 1)
        raw = (Path(self.dir.name) / "state.json").read_text(encoding="utf-8")
        json.loads(raw)                                   # parses, or this raises

    def test_retry_after_a_crash_succeeds_against_the_surviving_head(self):
        with self.store.transaction() as tx:
            tx.set_head("registry", C1, 1)
        real_replace = os.replace
        os.replace = lambda *a, **k: (_ for _ in ()).throw(OSError("crash"))
        try:
            with self.assertRaises(OSError):
                with self.store.transaction() as tx:
                    tx.set_head("registry", C2, 2)
                    tx.commit()
        finally:
            os.replace = real_replace
        retried = self.reopen()
        with retried.transaction() as tx:
            tx.assert_head("registry", C1)                # the surviving head, not the lost one
            tx.set_head("registry", C2, tx.allocate_epoch("registry"))
        self.assertEqual(self.reopen().head("registry"), (C2, 2))

    def test_a_sequence_allocated_before_a_crash_is_never_reissued(self):
        first = self.store.allocate_sequence("key-1")
        self.assertEqual(first, 0)
        # The process dies; a new one opens the same store.
        self.assertEqual(self.reopen().allocate_sequence("key-1"), 1,
                         "a sequence was reused after a restart")


class ConcurrencyTests(Fixture):
    def test_two_transactions_from_the_same_head_cannot_both_commit(self):
        with self.store.transaction() as tx:
            tx.set_head("registry", C1, 1)
        a, b = self.store.transaction(), self.store.transaction()
        a.assert_head("registry", C1)
        b.assert_head("registry", C1)
        a.set_head("registry", C2, 2)
        b.set_head("registry", "sha256:" + "33" * 32, 2)
        a.commit()
        with self.assertRaises(st.ConflictError):
            b.commit()
        self.assertEqual(self.reopen().head("registry"), (C2, 2))

    def test_two_consumers_of_one_authorization_cannot_both_commit(self):
        a, b = self.store.transaction(), self.store.transaction()
        a.consume_authorization("auth-1")
        b.consume_authorization("auth-1")                 # neither has committed yet
        a.commit()
        with self.assertRaises(st.ConflictError):
            b.commit()
        self.assertTrue(self.reopen().is_consumed("auth-1"))

    def test_the_same_authorization_is_refused_on_the_second_attempt(self):
        with self.store.transaction() as tx:
            tx.consume_authorization("auth-1")
        with self.assertRaises(st.StateError):
            with self.store.transaction() as tx:
                tx.consume_authorization("auth-1")

    def test_parallel_processes_never_share_a_sequence_for_one_identity(self):
        """The case I3 declared out of scope, closed here: real processes, one key_id."""
        path = str(Path(self.dir.name) / "state.json")
        script = (
            "import sys; sys.path.insert(0, %r)\n"
            "import f1_state as st\n"
            "store = st.AuthoritativeStore(%r)\n"
            "print(','.join(str(store.allocate_sequence('key-1')) for _ in range(25)))\n"
            % (str(Path(__file__).resolve().parents[1] / "scripts"), path)
        )
        procs = [subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE,
                                  text=True) for _ in range(4)]
        allocated = []
        for proc in procs:
            out, _ = proc.communicate(timeout=60)
            self.assertEqual(proc.returncode, 0, out)
            allocated.extend(int(value) for value in out.strip().split(","))
        self.assertEqual(len(allocated), 100)
        self.assertEqual(len(set(allocated)), 100, "two processes were handed the same sequence")
        self.assertEqual(sorted(allocated), list(range(100)), "the allocation was not contiguous")


class HeadSemanticsTests(Fixture):
    def test_a_stale_expected_head_is_refused(self):
        with self.store.transaction() as tx:
            tx.set_head("registry", C1, 1)
        with self.assertRaises(st.ConflictError):
            with self.store.transaction() as tx:
                tx.assert_head("registry", "")            # the genesis head, long gone

    def test_epochs_must_chain(self):
        with self.store.transaction() as tx:
            tx.set_head("registry", C1, 1)
        with self.assertRaises(st.StateError):
            with self.store.transaction() as tx:
                tx.set_head("registry", C2, 5)

    def test_genesis_epoch_is_one(self):
        with self.assertRaises(st.StateError):
            with self.store.transaction() as tx:
                tx.set_head("registry", C1, 0)

    def test_heads_are_independent_scopes_in_one_domain(self):
        with self.store.transaction() as tx:
            tx.set_head("registry", C1, 1)
            tx.set_head("policy", C2, 1)
        after = self.reopen()
        self.assertEqual((after.head("registry"), after.head("policy")), ((C1, 1), (C2, 1)))


class ScopeBoundaryTests(unittest.TestCase):
    def test_no_stage_2_and_no_message_semantics(self):
        """The store holds facts; it knows nothing about messages.

        Checks the CODE, not the prose. Scanning raw source matched the docstring that explains
        why sequence allocation commits separately — which mentions signatures precisely because
        the reasoning is about them. A scope test that cannot tell an explanation from an
        implementation is the crude-probe mistake, and this is its third appearance.
        """
        import ast
        source = (Path(__file__).resolve().parents[1] / "scripts" / "f1_state.py").read_text()
        tree = ast.parse(source)
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                names.add(node.id)
            elif isinstance(node, ast.Attribute):
                names.add(node.attr)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                if not isinstance(getattr(node, "parent", None), ast.Expr):
                    names.add(node.value)
        docstrings = {ast.get_docstring(n) for n in ast.walk(tree)
                      if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef))}
        names -= {d for d in docstrings if d}
        for absent in ("message_type", "signature", "obligation", "verdict", "admissible"):
            self.assertNotIn(absent, names, f"{absent!r} is not I5's; the store holds facts")

    def test_a_completed_transaction_cannot_commit_twice(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = st.AuthoritativeStore(Path(tmp) / "s.json")
            tx = store.transaction()
            tx.set_head("registry", C1, 1)
            tx.commit()
            with self.assertRaises(st.StateError) as caught:
                tx.commit()
            # Asserting the reason: mutation testing showed the CAS re-check ALSO refuses a second
            # commit, so the flag's own guard was never what the test exercised. Two independent
            # refusals is defense in depth, but only if each is actually pinned.
            self.assertIn("already completed", str(caught.exception))

    def test_a_double_commit_is_also_refused_with_the_flag_gone(self):
        """The second, independent guard: the CAS re-check under the lock."""
        with tempfile.TemporaryDirectory() as tmp:
            store = st.AuthoritativeStore(Path(tmp) / "s.json")
            tx = store.transaction()
            tx.set_head("registry", C1, 1)
            tx.commit()
            tx._done = False                       # as if the flag had never been set
            with self.assertRaises(st.ConflictError):
                tx.commit()

    def test_the_commit_path_fsyncs_before_and_after_publishing(self):
        """A structural check, and honest about why.

        No in-process test can observe a missing fsync: it only matters across a real power loss,
        where the data or the rename may not have reached the disk. Mutation testing surfaced this
        as an unkillable mutant, so the property is pinned where it can be — the commit path must
        call fsync on the data before the rename and on the directory after it. Asserting the
        implementation is the weaker kind of test; here it is the only kind available, and saying
        so is better than leaving a durability property with no check at all.
        """
        import ast
        source = (Path(__file__).resolve().parents[1] / "scripts" / "f1_state.py").read_text()
        write = next(n for n in ast.walk(ast.parse(source))
                     if isinstance(n, ast.FunctionDef) and n.name == "_write")
        # ast.walk does not preserve source order, and the ordering IS the property here.
        calls = [n.func.attr for n in sorted(
            (n for n in ast.walk(write)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)),
            key=lambda n: (n.lineno, n.col_offset))]
        self.assertEqual(calls.count("fsync"), 2,
                         "the commit path must fsync the data before the rename and the "
                         "directory after it")
        self.assertIn("replace", calls, "the commit must publish with an atomic rename")
        data_fsync = calls.index("fsync")
        rename = calls.index("replace")
        dir_fsync = calls.index("fsync", data_fsync + 1)
        self.assertLess(data_fsync, rename,
                        "the data must reach the disk before the rename publishes it")
        self.assertLess(rename, dir_fsync,
                        "the directory fsync must follow the rename: it is what makes the rename "
                        "itself survive a crash, so doing it first records nothing")


if __name__ == "__main__":
    unittest.main()
