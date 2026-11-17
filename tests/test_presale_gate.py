"""
Offline unit tests for PresaleGate.

They run with plain Python (no Docker, no GenLayer node). A small stub of the
`genlayer` module is installed first, so the real contract file is imported
unchanged. Web pages and LLM replies are mocked. The stub runs the leader and
then the validator exactly like gl.vm.run_nondet_unsafe, so validator logic
(re-fetch, literal checks, quote checks, own verdict) is tested too.

Run from the repo root:
    python -m unittest tests/test_presale_gate.py -v
"""

import os
import sys
import json
import types
import unittest
import datetime
import importlib.util


# ---------------- genlayer stub ----------------

class _Addr:
    def __init__(self, hex_):
        self.as_hex = hex_


class _Write:
    def __call__(self, fn):
        return fn

    def payable(self, fn):
        return fn


class _Return:
    def __init__(self, calldata):
        self.calldata = calldata


class ConsensusFailed(Exception):
    pass


class _Env:
    """Mutable test environment shared with the stub."""
    phase = "leader"          # "leader" or "validator"
    pages = {}                # url -> text seen by the leader
    validator_pages = {}      # url -> text seen by validators (if different)
    llm = None                # function(prompt, phase) -> dict
    tamper = None             # function(leader_dict) -> dict (lying leader)
    transfers = []
    now = 1800000000
    sender = "0xAAA0000000000000000000000000000000000001"
    value = 0


def _render(url, mode="text"):
    if _Env.phase == "validator" and url in _Env.validator_pages:
        page = _Env.validator_pages[url]
    else:
        page = _Env.pages.get(url)
    if page is None:
        raise Exception("fetch failed")
    return page


def _exec_prompt(prompt, response_format=None):
    return json.dumps(_Env.llm(prompt, _Env.phase))


def _run_nondet_unsafe(leader_fn, validator_fn):
    _Env.phase = "leader"
    res = leader_fn()
    if _Env.tamper is not None:
        res = _Env.tamper(dict(res))
    _Env.phase = "validator"
    try:
        ok = validator_fn(_Return(res))
    finally:
        _Env.phase = "leader"
    if not ok:
        raise ConsensusFailed("validators disagreed")
    return res


class _Handle:
    def __init__(self, addr):
        self.addr = addr

    def emit_transfer(self, value):
        _Env.transfers.append((self.addr.as_hex, int(value)))


class _Message:
    @property
    def sender_address(self):
        return _Addr(_Env.sender)

    @property
    def value(self):
        return _Env.value


class _MessageRaw(dict):
    def __contains__(self, k):
        return k == "datetime"

    def __getitem__(self, k):
        return datetime.datetime.fromtimestamp(_Env.now, datetime.timezone.utc).isoformat()


gl = types.SimpleNamespace(
    Contract=object,
    public=types.SimpleNamespace(write=_Write(), view=lambda fn: fn),
    nondet=types.SimpleNamespace(
        web=types.SimpleNamespace(render=_render),
        exec_prompt=_exec_prompt,
    ),
    vm=types.SimpleNamespace(Return=_Return, run_nondet_unsafe=_run_nondet_unsafe),
    get_contract_at=lambda addr: _Handle(addr),
)
gl.message = _Message()
gl.message_raw = _MessageRaw()


class _TreeMap(dict):
    def __class_getitem__(cls, item):
        return cls


genlayer_stub = types.ModuleType("genlayer")
genlayer_stub.gl = gl
genlayer_stub.u256 = int
genlayer_stub.TreeMap = _TreeMap
genlayer_stub.Address = _Addr
genlayer_stub.__all__ = ["gl", "u256", "TreeMap", "Address"]
sys.modules["genlayer"] = genlayer_stub

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "contracts", "presale_gate.py")
spec = importlib.util.spec_from_file_location("presale_gate", SRC)
pg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pg)


# ---------------- fixtures ----------------

CREATOR = "0xC000000000000000000000000000000000000001"
BUYER1 = "0xB000000000000000000000000000000000000001"
BUYER2 = "0xB000000000000000000000000000000000000002"
OTHER = "0xD000000000000000000000000000000000000009"
TOKEN = "0x1234567890abcdef1234567890abcdef12345678"
DOMAIN = "gurusankar55.github.io"
URL_OK = "https://gurusankar55.github.io/presalegate/launch.html"
URL_SOON = "https://gurusankar55.github.io/presalegate/soon.html"
URL_DOWN = "https://gurusankar55.github.io/presalegate/missing.html"

FILLER = " This page is the official announcement channel of the project team." * 4
S_LAUNCH = "The DEMOG token is now live on mainnet at the address shown below."
S_DELIVER = "All presale buyers have received their DEMOG tokens by airdrop today."

PAGE_OK = (
    "DemoGate launch notice. " + S_LAUNCH + " Token address: " + TOKEN + ". "
    + S_DELIVER + FILLER
)
PAGE_SOON = (
    "DemoGate update. The DEMOG token launch is coming soon. Token address: " + TOKEN
    + ". Presale tokens will be distributed next month." + FILLER
)

GEN = 10 ** 18


def honest_llm(prompt, phase):
    page = " ".join(prompt.split("<<<", 1)[1].lower().split())
    if " ".join(S_LAUNCH.lower().split()) in page and " ".join(S_DELIVER.lower().split()) in page:
        return {"launched": True, "delivered": True,
                "quote_launch": S_LAUNCH, "quote_delivery": S_DELIVER}
    return {"launched": False, "delivered": False, "quote_launch": "", "quote_delivery": ""}


def as_(addr, value=0):
    _Env.sender = addr
    _Env.value = value


class Base(unittest.TestCase):
    def setUp(self):
        _Env.phase = "leader"
        _Env.pages = {URL_OK: PAGE_OK, URL_SOON: PAGE_SOON}
        _Env.validator_pages = {}
        _Env.llm = honest_llm
        _Env.tamper = None
        _Env.transfers = []
        _Env.now = 1800000000
        self.c = pg.PresaleGate()
        self.c.sales = _TreeMap()
        self.c.contributions = _TreeMap()
        self.c.credits = _TreeMap()
        self.c.__init__()

    def new_sale(self, soft=2 * GEN, hard=10 * GEN, dur=600, window=600, ticker="DEMOG"):
        as_(CREATOR)
        return self.c.create_sale("DemoGate", ticker, "evm", DOMAIN, soft, hard, dur, window)

    def funded_awaiting(self):
        sid = self.new_sale()
        as_(BUYER1, 2 * GEN)
        self.c.contribute(sid)
        as_(BUYER2, 1 * GEN)
        self.c.contribute(sid)
        _Env.now += 601
        return sid

    def status(self, sid):
        return self.c.get_status(sid)

    def contract_liabilities(self):
        """Money the contract still owes (credits + contributions not refunded,
        for sales that were not paid out)."""
        owed = sum(int(v) for v in self.c.credits.values())
        for sid in self.c.sales:
            s = json.loads(self.c.sales[sid])
            if s["status"] != pg.STATUS_LAUNCHED:
                owed += sum(int(v) for k, v in self.c.contributions.items()
                            if k.startswith(sid + ":"))
        return owed


# ---------------- create_sale ----------------

class TestCreate(Base):
    def test_create_valid(self):
        sid = self.new_sale()
        self.assertEqual(sid, "0")
        s = json.loads(self.c.get_sale(sid))
        self.assertEqual(s["current_status"], "OPEN")
        self.assertEqual(s["official_domain"], DOMAIN)
        self.assertEqual(s["sale_end"], 1800000000 + 600)
        self.assertEqual(s["launch_deadline"], 1800000000 + 1200)
        self.assertEqual(s["creator"], CREATOR.lower())

    def test_domain_is_normalized(self):
        as_(CREATOR)
        sid = self.c.create_sale("X", "ABC", "evm", "https://WWW.Example.com/", 1, 1, 60, 60)
        self.assertEqual(json.loads(self.c.get_sale(sid))["official_domain"], "example.com")

    def test_bad_inputs_rejected(self):
        as_(CREATOR)
        bad = [
            ("", "ABC", "evm", DOMAIN, 1, 1, 60, 60),            # empty name
            ("X", "abc", "evm", DOMAIN, 1, 1, 60, 60),           # lowercase ticker
            ("X", "1AB", "evm", DOMAIN, 1, 1, 60, 60),           # ticker starts with digit
            ("X", "A", "evm", DOMAIN, 1, 1, 60, 60),             # ticker too short
            ("X", "ABC", "btc", DOMAIN, 1, 1, 60, 60),           # unknown chain
            ("X", "ABC", "evm", "localhost", 1, 1, 60, 60),      # not a domain
            ("X", "ABC", "evm", "evil.com/path", 1, 1, 60, 60),  # path in domain
            ("X", "ABC", "evm", DOMAIN, 0, 1, 60, 60),           # soft cap 0
            ("X", "ABC", "evm", DOMAIN, 5, 4, 60, 60),           # hard < soft
            ("X", "ABC", "evm", DOMAIN, 1, 1, 59, 60),           # sale too short
            ("X", "ABC", "evm", DOMAIN, 1, 1, 60, 7776001),      # window too long
        ]
        for args in bad:
            with self.assertRaises(Exception, msg=str(args)):
                self.c.create_sale(*args)
        self.assertEqual(self.c.get_sale_count(), 0)


# ---------------- contribute ----------------

class TestContribute(Base):
    def test_contribute_and_totals(self):
        sid = self.new_sale()
        as_(BUYER1, 3 * GEN)
        self.assertEqual(self.c.contribute(sid), 3 * GEN)
        as_(BUYER1, 1 * GEN)
        self.assertEqual(self.c.contribute(sid), 4 * GEN)
        s = json.loads(self.c.get_sale(sid))
        self.assertEqual(s["raised"], 4 * GEN)
        self.assertEqual(s["buyers"], 1)
        self.assertEqual(self.c.get_contribution(sid, BUYER1), 4 * GEN)

    def test_hard_cap_enforced(self):
        sid = self.new_sale(hard=5 * GEN)
        as_(BUYER1, 5 * GEN)
        self.c.contribute(sid)
        as_(BUYER2, 1)
        with self.assertRaises(Exception):
            self.c.contribute(sid)

    def test_zero_value_rejected(self):
        sid = self.new_sale()
        as_(BUYER1, 0)
        with self.assertRaises(Exception):
            self.c.contribute(sid)

    def test_creator_cannot_contribute(self):
        sid = self.new_sale()
        as_(CREATOR, GEN)
        with self.assertRaises(Exception):
            self.c.contribute(sid)

    def test_closed_after_sale_end(self):
        sid = self.new_sale()
        _Env.now += 600
        as_(BUYER1, GEN)
        with self.assertRaises(Exception):
            self.c.contribute(sid)


# ---------------- soft cap failure ----------------

class TestSoftCap(Base):
    def test_under_soft_cap_refunds(self):
        sid = self.new_sale(soft=5 * GEN)
        as_(BUYER1, 2 * GEN)
        self.c.contribute(sid)
        _Env.now += 601
        self.assertEqual(self.status(sid), "FAILED_SOFTCAP")
        as_(CREATOR)
        with self.assertRaises(Exception):
            self.c.claim_launch(sid, URL_OK, TOKEN)
        as_(BUYER1)
        self.assertEqual(self.c.refund(sid), 2 * GEN)
        with self.assertRaises(Exception):
            self.c.refund(sid)                       # no double refund
        self.assertEqual(self.c.withdraw(), 2 * GEN)
        self.assertEqual(_Env.transfers, [(BUYER1, 2 * GEN)])
        with self.assertRaises(Exception):
            self.c.withdraw()                        # nothing left

    def test_no_refund_while_open_or_awaiting(self):
        sid = self.new_sale()
        as_(BUYER1, 2 * GEN)
        self.c.contribute(sid)
        with self.assertRaises(Exception):
            self.c.refund(sid)                       # OPEN
        _Env.now += 601
        self.assertEqual(self.status(sid), "AWAITING_LAUNCH")
        with self.assertRaises(Exception):
            self.c.refund(sid)                       # AWAITING_LAUNCH


# ---------------- claim_launch: pre-checks ----------------

class TestClaimPrechecks(Base):
    def test_claim_before_sale_end_rejected(self):
        sid = self.new_sale()
        as_(BUYER1, 2 * GEN)
        self.c.contribute(sid)
        as_(CREATOR)
        with self.assertRaises(Exception):
            self.c.claim_launch(sid, URL_OK, TOKEN)

    def test_only_creator(self):
        sid = self.funded_awaiting()
        as_(OTHER)
        with self.assertRaises(Exception):
            self.c.claim_launch(sid, URL_OK, TOKEN)

    def test_off_domain_urls_rejected_without_using_attempt(self):
        sid = self.funded_awaiting()
        as_(CREATOR)
        for url in [
            "http://gurusankar55.github.io/presalegate/launch.html",       # not https
            "https://evil.io/gurusankar55.github.io/launch.html",          # other host
            "https://gurusankar55.github.io@evil.io/launch.html",          # userinfo trick
            "https://gurusankar55.github.io.evil.io/launch.html",          # suffix trick
            "https://gurusankar55.github.io:8443/launch.html",             # port
            "https://notgurusankar55.github.io/launch.html",               # look-alike
        ]:
            with self.assertRaises(Exception, msg=url):
                self.c.claim_launch(sid, url, TOKEN)
        self.assertEqual(json.loads(self.c.get_sale(sid))["attempts"], 0)

    def test_subdomain_allowed(self):
        self.assertTrue(pg._on_domain("https://docs.example.com/a", "example.com"))
        self.assertFalse(pg._on_domain("https://badexample.com/a", "example.com"))

    def test_bad_token_address_rejected(self):
        sid = self.funded_awaiting()
        as_(CREATOR)
        with self.assertRaises(Exception):
            self.c.claim_launch(sid, URL_OK, "0x1234")
        self.assertEqual(json.loads(self.c.get_sale(sid))["attempts"], 0)


# ---------------- claim_launch: verification ----------------

class TestVerification(Base):
    def test_verified_launch_pays_creator_once(self):
        sid = self.funded_awaiting()
        as_(CREATOR)
        self.assertEqual(self.c.claim_launch(sid, URL_OK, TOKEN), "LAUNCHED")
        self.assertTrue(self.c.is_launched(sid))
        self.assertEqual(self.status(sid), "LAUNCHED")
        self.assertEqual(self.c.get_credit(CREATOR), 3 * GEN)
        s = json.loads(self.c.get_sale(sid))
        self.assertTrue(s["last_check"]["passed"])
        self.assertEqual(s["token_address"], TOKEN)
        # no second claim, no refunds, status stays after deadline
        with self.assertRaises(Exception):
            self.c.claim_launch(sid, URL_OK, TOKEN)
        _Env.now += 10 ** 6
        self.assertEqual(self.status(sid), "LAUNCHED")
        as_(BUYER1)
        with self.assertRaises(Exception):
            self.c.refund(sid)
        as_(CREATOR)
        self.assertEqual(self.c.withdraw(), 3 * GEN)

    def test_address_missing_not_proven(self):
        sid = self.funded_awaiting()
        as_(CREATOR)
        other_token = "0x" + "9" * 40
        self.assertEqual(self.c.claim_launch(sid, URL_OK, other_token), "NOT_PROVEN")
        s = json.loads(self.c.get_sale(sid))
        self.assertEqual(s["attempts"], 1)
        self.assertFalse(s["last_check"]["address_in_page"])
        self.assertEqual(self.c.get_credit(CREATOR), 0)
        self.assertEqual(self.status(sid), "AWAITING_LAUNCH")

    def test_ticker_must_be_whole_word(self):
        # sale ticker DEMO, page only says DEMOG -> must not match
        sid = self.new_sale(ticker="DEMO")
        as_(BUYER1, 2 * GEN)
        self.c.contribute(sid)
        _Env.now += 601
        as_(CREATOR)
        self.assertEqual(self.c.claim_launch(sid, URL_OK, TOKEN), "NOT_PROVEN")
        self.assertFalse(json.loads(self.c.get_sale(sid))["last_check"]["ticker_in_page"])
        self.assertTrue(pg._ticker_in("buy $DEMO now", "DEMO"))
        self.assertFalse(pg._ticker_in("XDEMO and DEMO2", "DEMO"))

    def test_coming_soon_not_proven(self):
        sid = self.funded_awaiting()
        as_(CREATOR)
        self.assertEqual(self.c.claim_launch(sid, URL_SOON, TOKEN), "NOT_PROVEN")
        s = json.loads(self.c.get_sale(sid))
        self.assertFalse(s["last_check"]["delivered"])

    def test_hallucinated_quote_not_proven(self):
        def lying_llm(prompt, phase):
            return {"launched": True, "delivered": True,
                    "quote_launch": S_LAUNCH,
                    "quote_delivery": "Every presale buyer already holds the tokens in full."}
        _Env.llm = lying_llm
        sid = self.funded_awaiting()
        as_(CREATOR)
        self.assertEqual(self.c.claim_launch(sid, URL_OK, TOKEN), "NOT_PROVEN")
        self.assertFalse(json.loads(self.c.get_sale(sid))["last_check"]["quotes_ok"])
        self.assertEqual(self.c.get_credit(CREATOR), 0)

    def test_unreachable_not_proven(self):
        sid = self.funded_awaiting()
        as_(CREATOR)
        self.assertEqual(self.c.claim_launch(sid, URL_DOWN, TOKEN), "NOT_PROVEN")
        self.assertFalse(json.loads(self.c.get_sale(sid))["last_check"]["reachable"])

    def test_three_failures_open_refunds(self):
        sid = self.funded_awaiting()
        as_(CREATOR)
        self.assertEqual(self.c.claim_launch(sid, URL_SOON, TOKEN), "NOT_PROVEN")
        self.assertEqual(self.c.claim_launch(sid, URL_SOON, TOKEN), "NOT_PROVEN")
        self.assertEqual(self.c.claim_launch(sid, URL_SOON, TOKEN), "FAILED_LAUNCH")
        self.assertEqual(self.status(sid), "FAILED_LAUNCH")
        with self.assertRaises(Exception):
            self.c.claim_launch(sid, URL_OK, TOKEN)      # no 4th try, even a good one
        as_(BUYER1)
        self.assertEqual(self.c.refund(sid), 2 * GEN)
        as_(BUYER2)
        self.assertEqual(self.c.refund(sid), 1 * GEN)
        self.assertEqual(self.c.get_credit(CREATOR), 0)

    def test_deadline_passes(self):
        sid = self.funded_awaiting()
        _Env.now += 600                                   # reaches launch_deadline
        self.assertEqual(self.status(sid), "FAILED_DEADLINE")
        as_(CREATOR)
        with self.assertRaises(Exception):
            self.c.claim_launch(sid, URL_OK, TOKEN)
        as_(BUYER2)
        self.assertEqual(self.c.refund(sid), 1 * GEN)


# ---------------- validator behaviour ----------------

class TestValidator(Base):
    def test_validator_rejects_lying_leader_pass(self):
        # Leader claims PASS for the "coming soon" page -> validators must reject.
        def tamper(r):
            r.update({"launched": True, "delivered": True, "quotes_ok": True,
                      "quote_launch": "the demog token launch is coming soon.",
                      "quote_delivery": "presale tokens will be distributed next month."})
            return r
        _Env.tamper = tamper
        sid = self.funded_awaiting()
        as_(CREATOR)
        with self.assertRaises(ConsensusFailed):
            self.c.claim_launch(sid, URL_SOON, TOKEN)
        self.assertEqual(json.loads(self.c.get_sale(sid))["attempts"], 0)  # tx reverted
        self.assertEqual(self.c.get_credit(CREATOR), 0)

    def test_validator_rejects_lying_literal_fact(self):
        def tamper(r):
            r["address_in_page"] = not r["address_in_page"]
            return r
        _Env.tamper = tamper
        sid = self.funded_awaiting()
        as_(CREATOR)
        with self.assertRaises(ConsensusFailed):
            self.c.claim_launch(sid, URL_OK, TOKEN)

    def test_validator_rejects_leader_hiding_a_pass(self):
        # Leader reports FAIL for a page that really passes -> disagreement.
        def tamper(r):
            r["delivered"] = False
            r["quotes_ok"] = False
            return r
        _Env.tamper = tamper
        sid = self.funded_awaiting()
        as_(CREATOR)
        with self.assertRaises(ConsensusFailed):
            self.c.claim_launch(sid, URL_OK, TOKEN)

    def test_validator_page_differs(self):
        # Validator's copy of the page lost the delivery sentence -> no PASS.
        _Env.validator_pages = {URL_OK: PAGE_OK.replace(S_DELIVER, "")}
        sid = self.funded_awaiting()
        as_(CREATOR)
        with self.assertRaises(ConsensusFailed):
            self.c.claim_launch(sid, URL_OK, TOKEN)

    def test_whitespace_and_case_tolerant_quotes(self):
        _Env.validator_pages = {URL_OK: PAGE_OK.replace(S_LAUNCH, S_LAUNCH.upper().replace(" ", "\n  "))}
        sid = self.funded_awaiting()
        as_(CREATOR)
        self.assertEqual(self.c.claim_launch(sid, URL_OK, TOKEN), "LAUNCHED")


# ---------------- isolation & accounting ----------------

class TestIsolation(Base):
    def test_sales_are_isolated(self):
        a = self.new_sale()
        as_(OTHER)
        b = self.c.create_sale("Other", "OTHR", "evm", "other-project.xyz", GEN, 10 * GEN, 600, 600)
        as_(BUYER1, 3 * GEN)
        self.c.contribute(a)
        as_(BUYER1, 4 * GEN)
        self.c.contribute(b)
        as_(BUYER2, 2 * GEN)
        self.c.contribute(b)
        _Env.now += 601
        as_(CREATOR)
        self.assertEqual(self.c.claim_launch(a, URL_OK, TOKEN), "LAUNCHED")
        self.assertEqual(self.c.get_credit(CREATOR), 3 * GEN)       # only sale A money
        _Env.now += 600
        self.assertEqual(self.status(b), "FAILED_DEADLINE")
        as_(BUYER1)
        self.assertEqual(self.c.refund(b), 4 * GEN)                 # only sale B money
        with self.assertRaises(Exception):
            self.c.refund(a)
        total_in = 3 * GEN + 4 * GEN + 2 * GEN
        self.assertEqual(self.contract_liabilities(), total_in)

    def test_unknown_sale(self):
        self.assertEqual(self.c.get_status("7"), "NO_SALE")
        self.assertFalse(self.c.is_launched("7"))
        self.assertEqual(self.c.get_sale("7"), "")
        as_(BUYER1, GEN)
        with self.assertRaises(Exception):
            self.c.contribute("7")


if __name__ == "__main__":
    unittest.main()
