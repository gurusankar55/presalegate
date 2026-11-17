# PresaleGate — GenLayer Intelligent Contract

**Refund-by-default presale escrow. The team gets the money only after GenLayer validators verify a public launch notice on the team's own pre-committed domain.**

## Problem

Presale rugs are one of the most common losses in crypto. A team collects money for a token, then never launches, or launches and never gives presale buyers their tokens. Today the money goes straight to the team's wallet, and buyers have no way back.

## What PresaleGate does

PresaleGate holds presale money in the contract and answers one question:

> Did the team publish, on the official domain it committed to **before** the sale, and **before the deadline**, a launch notice for **this exact token address** that says presale buyers' tokens were **already delivered** (or are claimable now)?

* **Yes** → the raised money is credited to the team (once).
* **No / unclear** → nothing moves. After 3 failed attempts, or when the launch deadline passes, every buyer can take their money back.
* **Soft cap not reached** → every buyer can take their money back.

Other contracts can use one view as a trust primitive:

```
is_launched(sale_id) -> bool
```

## Sale lifecycle

```
create_sale ──► OPEN (now < sale_end)                 contribute() allowed
                  │
        sale_end reached
                  ├── raised < soft_cap ────────────► FAILED_SOFTCAP   refund() allowed
                  │
                  └── raised >= soft_cap ───────────► AWAITING_LAUNCH  claim_launch() (creator only)
                                                         │
                       ├── launch verified ────────────► LAUNCHED        creator paid once
                       ├── 3rd failed attempt ─────────► FAILED_LAUNCH   refund() allowed
                       └── now >= launch_deadline ─────► FAILED_DEADLINE refund() allowed
```

Status is computed from the transaction clock, so a deadline takes effect by itself. Nobody has to call anything.

Times are relative to the `create_sale` transaction:

* `sale_end = now + sale_duration_seconds`
* `launch_deadline = sale_end + launch_window_seconds`

Both windows must be between 60 seconds and 90 days.

## How consensus is used

`claim_launch` uses a **custom leader / validator pair** (`gl.vm.run_nondet_unsafe`), not a free-text comparison.

**1. Deterministic pre-checks (no web, no LLM).** Invalid input is rejected before any validator work, and it does not use up an attempt.

* `evidence_url` must be `https://` and its host must be the committed `official_domain` or one of its subdomains.
* Tricks are rejected: `user@host`, ports, `official.com.evil.io`, look-alike hosts.
* `token_address` must match the sale's chain format (EVM `0x` + 40 hex, or Solana base58).

**2. Literal checks on the fetched page (no LLM).**

* The token address must appear on the page.
* The ticker must appear as a whole word. For example, `DEMO` does not match `DEMOG`.

**3. A narrow LLM judgement with proof.** The LLM answers two yes/no questions:

* `launched`: is the token already live (not "coming soon")?
* `delivered`: have presale buyers' tokens already been delivered, or are they claimable now?

For each "yes", the LLM must copy one sentence from the page. If that quote is not literally on the page, the check fails. A hallucinated "yes" therefore cannot release money.

**4. Independent validators.** Each validator:

1. re-fetches the page itself;
2. re-runs the literal checks, which must match the leader exactly;
3. confirms the leader's quotes exist on its **own** copy of the page;
4. makes its **own** pass/fail judgement.

Any mismatch is a disagreement, and the transaction does not finalize. A lying leader is caught in both directions: a fake pass, or hiding a real pass.

**5. Safe default.** If the page is unreachable, unclear or only a promise, the result is `NOT_PROVEN`. No money moves.

## Funds safety

* **Per-sale accounting.** Each sale tracks its own `raised` and per-buyer contributions. One sale can never pay out another sale's money (tested).
* **No double payment.** `LAUNCHED` and the `FAILED_*` states are mutually exclusive, so the creator payout and buyer refunds can never both happen for one sale.
* **Bounded tries.** The team has at most 3 claims. A 4th claim is rejected, even with a good page.
* **Contribution rules.** The creator cannot contribute to their own sale. `hard_cap` is enforced.
* **Pull payments.** Payouts are credited first, then taken out with `withdraw()`.

## Methods

**Write**

| Method | Description |
|---|---|
| `create_sale(name, ticker, chain, official_domain, soft_cap, hard_cap, sale_duration_seconds, launch_window_seconds)` | Open a presale and commit the official domain. Returns `sale_id`. |
| `contribute(sale_id)` payable | Buy in while the sale is `OPEN`. |
| `claim_launch(sale_id, evidence_url, token_address)` | Creator asks validators to verify the launch notice. Returns `LAUNCHED`, `NOT_PROVEN` or `FAILED_LAUNCH`. |
| `refund(sale_id)` | Buyer takes their contribution back from a failed sale. |
| `withdraw()` | Withdraw credited funds. |

**View**

| Method | Description |
|---|---|
| `is_launched(sale_id)` | True only for a verified launch. |
| `get_status(sale_id)` | `OPEN`, `AWAITING_LAUNCH`, `LAUNCHED`, `FAILED_SOFTCAP`, `FAILED_LAUNCH`, `FAILED_DEADLINE` or `NO_SALE`. |
| `get_sale(sale_id)` | Full sale JSON, plus `current_status`, `can_contribute`, `can_claim_launch`, `can_refund`, `attempts_left` and the last check (with quotes). |
| `get_contribution(sale_id, address)` | A buyer's amount still held. |
| `get_credit(address)` | Withdrawable balance. |
| `get_sale_count()` / `get_rules()` | Totals and fixed rules. |

## Using it from another contract

```python
gate = gl.get_contract_at(Address(PRESALEGATE_ADDRESS))
if gate.view().is_launched(sale_id):
    # launchpad badge, listing bot, airdrop checker, etc.
    ...
```

## Limitations

* PresaleGate verifies a **public, attributable statement** on a domain the team committed to before buyers paid. It does not read token balances on another chain. If a team publishes a false delivery statement, the statement is now on-chain evidence against them, together with the exact page, the address and the quotes. Integrators can cross-check `token_address` on-chain.
* Pages that load all their text through heavy JavaScript may come back unreachable. Teams should use a simple announcement page.
* Only the first 15,000 characters of a page are read.

## Files

```
contracts/presale_gate.py        # the Intelligent Contract (deployed source)
tests/test_presale_gate.py       # 30 offline unit tests: python -m unittest tests/test_presale_gate.py -v
tests/STUDIO_TEST_PLAN.md        # 4 Studio scenarios, step by step
docs/launch.html, docs/soon.html # evidence pages used in the Studio test (GitHub Pages)
evidence/                        # Studio screenshots
```

The offline tests use a small stub of the `genlayer` module. The stub runs the leader and then the validator, exactly like `run_nondet_unsafe`. This covers validator behaviour too: a lying leader in both directions, different page copies, and whitespace- and case-tolerant quotes.

## Deployment

GenLayer Studio: [`0x08106B60b0b2C12c63F2E3054E7D0B1400cC7965`](https://explorer-studio.genlayer.com/address/0x08106B60b0b2C12c63F2E3054E7D0B1400cC7965) (no constructor arguments)

The deployed contract is exactly `contracts/presale_gate.py` in this repo.

## Studio test evidence (Nov 17, 2026)

* Account 1 = team `0xA40774…dfbb`
* Account 2 = buyer `0xaeD00d…4813`

Screenshots are in `evidence/`.

**Scenario A: verified launch, team paid (sale 0)**

| Step | Call | Result |
|---|---|---|
| A1 | `create_sale("DemoGate","DEMOG","evm","gurusankar55.github.io",1 GEN,100 GEN,180,900)` | `"0"` |
| A2 | `contribute("0")` + 2 GEN (buyer) | `2000000000000000000` |
| A3 | `get_status("0")` after sale end | `AWAITING_LAUNCH` |
| A4 | `claim_launch` by the buyer | error: only the sale creator can claim the launch |
| A5 | `claim_launch` with `https://evil.io/launch.html` | error: evidence_url is not on the committed official domain |
| A6a | `claim_launch` with a mistyped URL (`launch.htmll`, a 404 page) | `"NOT_PROVEN"`: `reachable:false`, no money moved, 1 attempt used |
| A6 | `claim_launch` with `/presalegate/launch.html` | `"LAUNCHED"`: address and ticker found, both quotes found on the page, all validators agree |
| A9 | `withdraw()` (team) | `2000000000000000000` |

**Scenario B: promise only, 3 failures, buyer refunded (sale 1)**

| Step | Call | Result |
|---|---|---|
| B1–B2 | `create_sale(…,180,1800)` → `"1"`; buyer `contribute("1")` + 2 GEN | `2000000000000000000` |
| B3–B4 | `claim_launch` with `/presalegate/soon.html` | `"NOT_PROVEN"` twice (`address_in_page:true`, `launched:false`, `delivered:false`) |
| B5 | same, 3rd attempt | `"FAILED_LAUNCH"` |
| B6 | 4th claim, this time with the GOOD page | error: sale is not awaiting launch (status FAILED_LAUNCH) |
| B7–B8 | buyer `refund("1")`, then `withdraw()` | `2000000000000000000`, then paid out |

**Scenario C: soft cap not reached (sale 2)**

| Step | Call | Result |
|---|---|---|
| C1–C2 | `create_sale("SmallCap","SMOL",…,soft 50 GEN,…,180,60)` → `"2"`; buyer `contribute("2")` + 1 GEN | raised 1 GEN |
| C3 | `get_sale("2")` after sale end | `current_status: FAILED_SOFTCAP`, `can_refund: true` |
| C4 | buyer `refund("2")`, then `withdraw()` | both finalized; buyer balance back to the starting amount |

**Scenario D: accounting**

| Check | Result |
|---|---|
| `get_sale_count()` | `3` |
| `get_credit(team)` after everything | `0`: team paid once, for sale 0 only |
| `get_credit(buyer)` after withdrawals | `0` |

License: MIT
