# PresaleGate — GenLayer Studio test plan

Deploy `contracts/presale_gate.py` on https://studio.genlayer.com. The constructor has no inputs.

* **Account 1** = team (creator)
* **Account 2** = buyer

Value fields are in GEN. Caps are in wei (1 GEN = 1000000000000000000).

Evidence pages (GitHub Pages, official domain `gurusankar55.github.io`):

* OK page: `https://gurusankar55.github.io/presalegate/launch.html`
* "Coming soon" page: `https://gurusankar55.github.io/presalegate/soon.html`

Demo token address: `0x7e57000000000000000000000000000000c0ffee`

## Scenario A — verified launch, team paid (sale "0")

| # | Account | Call | Expected |
|---|---|---|---|
| A1 | 1 | `create_sale("DemoGate", "DEMOG", "evm", "gurusankar55.github.io", 1000000000000000000, 100000000000000000000, 60, 900)` | `"0"` |
| A2 | 2 | `contribute("0")` with value **2** | `2000000000000000000` |
| A3 | 1 | wait **1 minute**, then `get_status("0")` | `AWAITING_LAUNCH` |
| A4 | 2 | `claim_launch("0", "https://gurusankar55.github.io/presalegate/launch.html", "0x7e57000000000000000000000000000000c0ffee")` | error: only the sale creator |
| A5 | 1 | `claim_launch("0", "https://evil.io/launch.html", "0x7e57000000000000000000000000000000c0ffee")` | error: not on the committed official domain |
| A6 | 1 | `claim_launch("0", "https://gurusankar55.github.io/presalegate/launch.html", "0x7e57000000000000000000000000000000c0ffee")` | `"LAUNCHED"` |
| A7 | 1 | `get_sale("0")` | `current_status: LAUNCHED`, `last_check.passed: true`, both quotes shown |
| A8 | 2 | `refund("0")` | error: refunds only for failed sales |
| A9 | 1 | `withdraw()` | `2000000000000000000` |

## Scenario B — promise only, 3 failed attempts, buyer refunded (sale "1")

| # | Account | Call | Expected |
|---|---|---|---|
| B1 | 1 | `create_sale("DemoGate", "DEMOG", "evm", "gurusankar55.github.io", 1000000000000000000, 100000000000000000000, 60, 1800)` | `"1"` |
| B2 | 2 | `contribute("1")` with value **2** | `2000000000000000000` |
| B3 | 1 | wait **1 minute**, then `claim_launch("1", "https://gurusankar55.github.io/presalegate/soon.html", "0x7e57000000000000000000000000000000c0ffee")` | `"NOT_PROVEN"` |
| B4 | 1 | same call again | `"NOT_PROVEN"` |
| B5 | 1 | same call again | `"FAILED_LAUNCH"` |
| B6 | 1 | `claim_launch("1", ".../launch.html", "0x7e57…c0ffee")` | error: not awaiting launch (no 4th try) |
| B7 | 2 | `refund("1")` | `2000000000000000000` |
| B8 | 2 | `withdraw()` | `2000000000000000000` |

## Scenario C — soft cap not reached (sale "2")

| # | Account | Call | Expected |
|---|---|---|---|
| C1 | 1 | `create_sale("SmallCap", "SMOL", "evm", "gurusankar55.github.io", 50000000000000000000, 100000000000000000000, 60, 60)` | `"2"` |
| C2 | 2 | `contribute("2")` with value **1** | `1000000000000000000` |
| C3 | 2 | wait **1 minute**, then `get_status("2")` | `FAILED_SOFTCAP` |
| C4 | 2 | `refund("2")`, then `withdraw()` | `1000000000000000000`, then `1000000000000000000` |

## Scenario D — isolation and views

| # | Account | Call | Expected |
|---|---|---|---|
| D1 | any | `is_launched("0")` / `is_launched("1")` / `is_launched("2")` | `true` / `false` / `false` |
| D2 | any | `get_sale_count()` | `3` |
| D3 | any | `get_credit(<account 1 address>)` | `0` (sale 0 paid once, nothing from sales 1–2) |

## Offline tests

```
python -m unittest tests/test_presale_gate.py -v
```

These are 30 tests. They cover input validation, the hard cap, timing, soft cap refunds, domain tricks, address and ticker checks, hallucinated quotes, unreachable pages, the 3-attempt limit, the deadline, a lying leader (fake pass and hidden pass), validator page differences, and per-sale isolation.
