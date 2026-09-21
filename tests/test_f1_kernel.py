"""F1-I1 closure tests: the cryptographic message kernel (T1A §6).

Every test here maps to a clause of the frozen contract. The adversarial ones matter more than the
happy paths: a kernel that signs and verifies correctly but accepts an unknown field, or lets a
VERIFY signature be read as a DECISION, has implemented the shape of §6 and none of its point.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import f1_kernel as k                                      # noqa: E402
from f1_canonical import CanonicalizationError, canonicalize  # noqa: E402

VERIFY_BODY = {
    "run_commitment": "run-1", "gate_commitment": "gate-1", "candidate_fingerprint": "cand-1",
    "obligation_id": "obl-1", "verification_method": "pytest", "verdict": "pass",
    "observation_digest": "sha256:aa",
}
DECISION_BODY = {
    "run_commitment": "run-1", "candidate_fingerprint": "cand-1", "decision": "accept",
    "decision_snapshot_digest": "sha256:bb", "superseded_adverse_verdicts": [],
    "policy_head": "pol-1",
}


def msg(message_type="VERIFY", action="attest", body=None, **over):
    fields = dict(key_id="key-1", producer_identity="verifier-1", sequence=0,
                  signed_at="2026-09-21T00:00:00Z", deployment_mode="B")
    fields.update(over)
    return k.message(message_type, action, body=dict(body or VERIFY_BODY), **fields)


class CanonicalizationTests(unittest.TestCase):
    """RFC 8785, over the integers-only profile §6's bodies actually use."""

    def test_jcs_vectors(self):
        for value, expected in [
            ({"b": 1, "a": 2}, b'{"a":2,"b":1}'),
            ({}, b"{}"),
            ([], b"[]"),
            ({"a": [1, {"c": 3, "b": 2}]}, b'{"a":[1,{"b":2,"c":3}]}'),
            ({"a": True, "b": False}, b'{"a":true,"b":false}'),
            ({"a": -0}, b'{"a":0}'),
            ({"ä": 1, "a": 2}, b'{"a":2,"\xc3\xa4":1}'),
            # RFC 8785 §3.2.3: escapes, and control characters as lowercase \u00xx.
            ({"a": 'q"\\\b\f\n\r\t'}, b'{"a":"q\\"\\\\\\b\\f\\n\\r\\t"}'),
            ({"a": "\u0001"}, b'{"a":"\\u0001"}'),
            # Literal above 0x1f, never escaped.
            ({"a": "é"}, b'{"a":"\xc3\xa9"}'),
        ]:
            with self.subTest(value=value):
                self.assertEqual(canonicalize(value), expected)

    def test_keys_sort_by_utf16_code_units_not_code_points(self):
        # U+10000 is a surrogate pair in UTF-16, so it sorts BELOW U+FFFD even though its code
        # point is higher. Sorting by code point would put it after.
        out = canonicalize({"\U00010000": 1, "�": 2})
        self.assertLess(out.index(b"\xf0\x90\x80\x80"), out.index(b"\xef\xbf\xbd"))

    def test_float_is_refused_not_approximated(self):
        with self.assertRaises(CanonicalizationError):
            canonicalize({"a": 1.5})

    def test_null_is_refused(self):
        with self.assertRaises(CanonicalizationError):
            canonicalize({"a": None})

    def test_unserializable_type_is_refused(self):
        with self.assertRaises(CanonicalizationError):
            canonicalize({"a": {1, 2}})

    def test_canonical_form_is_stable_under_key_order(self):
        a = dict(VERIFY_BODY)
        b = {key: VERIFY_BODY[key] for key in reversed(list(VERIFY_BODY))}
        self.assertEqual(canonicalize(a), canonicalize(b))


class ClosedVocabularyTests(unittest.TestCase):
    """§6's lists are closed: eleven domains, and a per-type action enum."""

    def test_eleven_domains_each_with_an_action_enum_and_a_body_schema(self):
        self.assertEqual(len(k.DOMAINS), 11)
        self.assertEqual(set(k.DOMAINS), set(k.ACTIONS))
        self.assertEqual(set(k.DOMAINS), set(k.BODIES))

    def test_domains_match_the_frozen_contract(self):
        contract = (Path(__file__).resolve().parents[1]
                    / "docs" / "f1-t1a-trust-core.md").read_text(encoding="utf-8")
        import re
        declared = set(re.findall(r"NOGAP::([A-Z]+)::v1\s*\|\|", contract))
        self.assertEqual(declared, set(k.DOMAINS), "kernel and contract disagree on the domains")

    def test_actions_match_the_frozen_contract(self):
        contract = (Path(__file__).resolve().parents[1]
                    / "docs" / "f1-t1a-trust-core.md").read_text(encoding="utf-8")
        import re
        block = re.search(r"```\n(PROJECT\s+genesis.*?)\n```", contract, re.S).group(1)
        declared = {}
        for line in block.splitlines():
            name, rest = line.split(None, 1)
            declared[name] = frozenset(a.strip() for a in rest.split("|") if a.strip())
        self.assertEqual(declared, dict(k.ACTIONS), "kernel and contract disagree on the actions")

    def test_unknown_message_type_is_rejected(self):
        with self.assertRaises(k.MessageError):
            msg(message_type="OVERRIDE", action="attest")

    def test_action_outside_its_types_enum_is_rejected(self):
        with self.assertRaises(k.MessageError):
            msg(message_type="VERIFY", action="accept")       # DECISION's verb, not VERIFY's
        with self.assertRaises(k.MessageError):
            msg(message_type="DECISION", action="attest", body=DECISION_BODY)

    def test_every_type_can_be_built_and_signed(self):
        bodies = {t: {f: ([] if f.endswith("s") else "x") for f in k.BODIES[t][0]}
                  for t in k.DOMAINS}
        bodies["PROJECT"]["provisioning_sequence"] = 1
        for t in ("POLICY", "APPLICABILITY", "REGISTRY", "MIGRATION"):
            bodies[t]["epoch"] = 1
        sk = k.generate_key()
        for t in sorted(k.DOMAINS):
            with self.subTest(message_type=t):
                m = msg(message_type=t, action=sorted(k.ACTIONS[t])[0], body=bodies[t])
                self.assertEqual(k.verify(k.sign(m, sk), sk.public_key())["message_type"], t)


class EnvelopeTests(unittest.TestCase):
    def test_unknown_envelope_field_is_rejected(self):
        m = msg()
        m["authority"] = "verification"          # F1's original defect, as an envelope field
        with self.assertRaises(k.MessageError):
            k.validate(m)

    def test_missing_envelope_field_is_rejected(self):
        for field in k.ENVELOPE:
            m = msg()
            del m[field]
            with self.subTest(field=field), self.assertRaises(k.MessageError):
                k.validate(m)

    def test_unknown_schema_version_is_rejected(self):
        m = msg()
        m["schema_version"] = "f1-t1a-rev23"
        with self.assertRaises(k.MessageError):
            k.validate(m)

    def test_deployment_mode_must_be_declared(self):
        with self.assertRaises(k.MessageError):
            msg(deployment_mode="D")

    def test_sequence_must_be_a_non_negative_integer(self):
        for bad in (-1, "1", True, 1.0):
            with self.subTest(sequence=bad), self.assertRaises(k.MessageError):
                msg(sequence=bad)


class BodySchemaTests(unittest.TestCase):
    def test_unknown_body_field_is_rejected_not_ignored(self):
        body = dict(VERIFY_BODY, authority="verification")
        with self.assertRaises(k.MessageError):
            msg(body=body)

    def test_missing_required_body_field_is_rejected(self):
        for field in VERIFY_BODY:
            body = {f: v for f, v in VERIFY_BODY.items() if f != field}
            with self.subTest(field=field), self.assertRaises(k.MessageError):
                msg(body=body)

    def test_null_body_field_is_rejected(self):
        with self.assertRaises(k.MessageError):
            msg(body=dict(VERIFY_BODY, supersedes=None))

    def test_optional_field_may_be_absent_or_present(self):
        self.assertNotIn("supersedes", msg()["body"])
        self.assertIn("supersedes", msg(body=dict(VERIFY_BODY, supersedes="verify-9"))["body"])

    def test_a_body_is_validated_against_its_own_schema_and_no_other(self):
        # AM-19: one payload shape for every type was the defect. A DECISION body under VERIFY
        # must not pass merely because both are well-formed objects.
        with self.assertRaises(k.MessageError):
            msg(message_type="VERIFY", action="attest", body=DECISION_BODY)


class SignatureTests(unittest.TestCase):
    def setUp(self):
        self.sk = k.generate_key()
        self.pk = self.sk.public_key()

    def test_round_trip(self):
        self.assertEqual(k.verify(k.sign(msg(), self.sk), self.pk)["body"], VERIFY_BODY)

    def test_wrong_key_does_not_verify(self):
        with self.assertRaises(k.MessageError):
            k.verify(k.sign(msg(), self.sk), k.generate_key().public_key())

    def test_tampered_body_does_not_verify(self):
        signed = k.sign(msg(), self.sk)
        signed["message"]["body"]["verdict"] = "fail"
        with self.assertRaises(k.MessageError):
            k.verify(signed, self.pk)

    def test_tampered_envelope_does_not_verify(self):
        signed = k.sign(msg(), self.sk)
        signed["message"]["producer_identity"] = "someone-else"
        with self.assertRaises(k.MessageError):
            k.verify(signed, self.pk)

    def test_cross_domain_reinterpretation_is_impossible(self):
        """§6: a VERIFY signature can never be read as a DECISION, even if the bodies coincide."""
        shared = {"run_commitment": "r", "candidate_fingerprint": "c"}
        a = msg(message_type="VERIFY", action="attest", body=dict(VERIFY_BODY, **shared))
        signed = k.sign(a, self.sk)
        # Re-label the signed message as the other domain and keep the signature.
        forged = {"message": dict(signed["message"]), "signature": signed["signature"]}
        forged["message"]["message_type"] = "DECISION"
        forged["message"]["action"] = "accept"
        forged["message"]["body"] = dict(DECISION_BODY, **shared)
        with self.assertRaises(k.MessageError):
            k.verify(forged, self.pk)

    def test_domain_prefix_is_in_the_signing_input(self):
        m = msg()
        self.assertTrue(k.signing_input(m).startswith(b"NOGAP::VERIFY::v1||"))

    def test_signature_over_the_same_body_differs_across_domains(self):
        body = {f: "x" for f in k.BODIES["TASK"][0]}
        a = k.signing_input(msg(message_type="TASK", action="create", body=body))
        b = k.signing_input(msg(message_type="TASK", action="relate", body=body))
        self.assertNotEqual(a, b)          # action is inside the signed payload (AM-23)

    def test_recanonicalization_must_be_byte_identical(self):
        m = msg()
        signed = k.sign(m, self.sk)
        reordered = {key: m[key] for key in reversed(list(m))}
        self.assertEqual(k.verify({"message": reordered, "signature": signed["signature"]},
                                  self.pk)["message_type"], "VERIFY")

    def test_malformed_signed_wrapper_is_rejected(self):
        for bad in ({"message": msg()}, {"signature": "aa"}, {"message": msg(), "signature": "zz",},
                    {"message": msg(), "signature": "aa", "extra": 1}, "not-a-dict"):
            with self.subTest(bad=bad), self.assertRaises(k.MessageError):
                k.verify(bad, self.pk)


class NoSigningOracleTests(unittest.TestCase):
    """§2: a signer that endorses caller-supplied assertions is the first failure mode."""

    def test_no_exported_function_signs_caller_supplied_bytes(self):
        sk = k.generate_key()
        for name in dir(k):
            if name.startswith("_"):
                continue
            fn = getattr(k, name)
            if not callable(fn) or name in {"generate_key", "canonicalize"}:
                continue
            with self.subTest(fn=name):
                try:
                    out = fn(b"NOGAP::DECISION::v1||{}", sk)
                except Exception:
                    continue
                self.assertNotIsInstance(out, (bytes, dict),
                                         f"{name}() signed raw caller bytes")

    def test_sign_refuses_an_unvalidated_message(self):
        sk = k.generate_key()
        with self.assertRaises(k.MessageError):
            k.sign({"message_type": "DECISION", "action": "accept"}, sk)

    def test_caller_cannot_choose_the_domain(self):
        import inspect
        for fn in (k.sign, k.signing_input):
            params = set(inspect.signature(fn).parameters)
            self.assertFalse(params & {"domain", "prefix", "context"},
                             f"{fn.__name__} lets the caller choose a signing domain")


if __name__ == "__main__":
    unittest.main()
