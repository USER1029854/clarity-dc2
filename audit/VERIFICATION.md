> # ⚠️ RETRACTED — THIS VERDICT IS WRONG. See `RETRACTION.md`.
> This "CONFIRMED" conclusion is a **false positive from a component misidentification**:
> `08921c4b` is the Agora **Proposal** validator (its `F5[1]` is a proposal's *vote tally*),
> not a stake with recyclable weight. Every vote is backed by real staked CLARITY (61/61
> verified), and a preserved tally exists only on Finished proposals, which can't accept new
> votes. **There is no recyclable-voting-weight vulnerability.** The text below is kept only as
> a record of the mistake; do not act on it.

---

# Verification — "Governance capture via recyclable voting weight" (Clarity, Cardano)

**Verdict: CONFIRMED (real, live, exploitable).** — ❌ RETRACTED, see banner above and `RETRACTION.md`. Independently reproduced against the live
Cardano mainnet deployment (Koios + on-chain bytecode), pinned at **block 13,914,607 / epoch 654
(Conway), slot 197,311,244**. The finding's root cause, contract set, live numbers and value-at-risk
all check out. One mechanistic detail in the finding is imprecise (see §4) — but the correction makes
the bug *more* clearly real, not less.

The audit workspace this was filed from was empty here (no `audit/sim/*.py` present), so nothing was
taken on trust: every load-bearing claim below was re-derived from the deployment.

---

## 1. What the finding claims

A Clarity stake's voting weight (`F5[1]`) is credited when CLARITY is **locked** to the stake, but is
**not reduced when the CLARITY is unlocked (delocked)**. Because an unlocked position is identical to a
fresh deposit, the same coins can be locked → delocked → withdrawn → redeposited → re-locked, adding
weight *again* each cycle. A small, fully-recoverable amount of CLARITY therefore buys unbounded standing
voting weight → pass any proposal → mint a GAT → drain the DAO treasury. Defeats the core economic
defense ("to control governance you must lock quorum-worth of the token").

## 2. Confirmed on-chain facts (all independently re-derived)

| Claim in finding | Verified value (live) | Match |
|---|---|---|
| CLARITY token | policy `1e76aaec…`, "Clarity DAO Token", supply 2e15 | ✓ |
| Stake validator `08921c4b…` | `addr1wyyfy8zt2qn…` (5 live stakes) | ✓ |
| Custody pool `251f79b3…` | `addr1wyj377dnuxy…` (100 positions, 268.18M CLARITY) | ✓ |
| Governor `a21eb594…` | confirmed in GAT-mint tx + as script | ✓ |
| GAT policy `33230e1d…` | `33230e1de259f957d1d857ea37ca810950b4c47d7ed8db9086e9d28d` | ✓ |
| Type-A treasury `fcc43cd5…` | `addr1w87vg0x4k…` | ✓ |
| 5 live stakes, **318.05M** total weight | Σ F5[1] = **318,049,654,029,048** raw = 318.05M | ✓ exact |
| Only **65.10M** currently locked | Σ locked positions = **65,098,022,599,584** = 65.10M | ✓ exact |
| Quorum **57.5M** | stake datum field 4[0] = 57,500,000,000,000 | ✓ |
| 30-min lock window | stake datum field 6 last = 1,800,000 ms | ✓ |
| Treasury holds **780,384,895 CLARITY + 2,276 ADA** | `fcc43cd5` holds 780,384,895 CLARITY + 2,277 ADA | ✓ exact |
| 4 GAT mints from single stakes 63–90M > quorum | blocks 10374642 / 10526088 / 10555842 / 10622956 | ✓ |
| No admin key / pause / guardian / timelock | no pubkeyhash constant in any validator; all constants are protocol hashes | ✓ |

## 3. The root cause is real — proven from transaction history (§evidence/delock_analysis.json)

Stake weight lives in datum **field 5, key 1** (`F5[1]`). Positions live in the pool with datum
`[amount, owner, _, locks]`; a lock entry is `[stake_id, Constr1[type, deadline_ms]]`.

I traced **every** `delock` transaction (stake redeemer constructor **2**) across the 5 stakes' full
118-tx history and compared, per tx, the stake's weight decrease against the amount of collateral
unlocked:

- **38** delock transactions total.
- **37** removed a locked position's lock (`locks: [[id,…]] → []`, collateral freed) while the stake's
  weight stayed **exactly unchanged**.
- **1** decremented weight by exactly the unlocked amount (the correct behavior).
- Cumulative backing unlocked while weight was kept: **~305.66M CLARITY**.

Worked example — tx `6a2a55a2…` (block 10437364): a **5,000,000-CLARITY** position (locked to stake 0)
is delocked (`locks → []`); stake 0's weight stays **63,497,959,270,744** before and after. The freed
collateral is now withdrawable, the weight persists.

Aggregate corroboration: stake 0's weight was *built* to 63.50M by lock operations (Σ positive
weight-deltas = 63.50M), yet only **0.048M** remains locked to it today — the rest was delocked with
weight retained. Same shape for stakes 1–3 (gaps of ~64M / ~60M / ~65M). Stake 4 (the newest) is the
only one still fully backed (weight 24.76M == locked 24.76M) because its locks were never removed.

So the deployed delock validator **does not enforce** `weight' = weight − unlocked`. It accepts keeping
the full weight. That is the bug, and it has already run 37 times in production.

## 4. Mechanism, pinned down on the real bytecode (finding's description holds)

I ran the deployed 7,946-byte stake validator `08921c4b` in the UPLC CEK machine against the
reconstructed `ScriptContext` of a real delock tx (`6a2a55a2`, freeing 5,000,000 CLARITY) and did a
differential on the output weight (`audit/poc/verify_bytecode.py`, GATE 1):

- output weight **KEPT** (unchanged) → **ACCEPT**
- output weight **reduced** by the unlocked amount → **REJECT**
- output weight increased / zeroed → **REJECT**

So in the ordinary (expired-lock) delock, the validator **forces the weight to stay** — you free the
collateral and *cannot* reduce the weight. That matches the finding's claim ("leaves F5[1] unchanged;
changing it up or down is rejected"). A single atypical tx (`1ca043e4`) did decrement on redeemer 2, and
running *its* context shows that context accepts both keep and decrement — so "decrement is always
forbidden" is slightly too strong. The invariant that actually holds on the real code, and is all the
exploit needs: **keeping the weight while freeing the collateral is ALWAYS accepted** (proven on real
bytecode in both contexts; 37 real mainnet delocks did it). The proposed fix — make delock decrement
`F5[1]` by the unlocked amount — is correct.

(This supersedes an earlier draft note that called the decrement merely "optional"; the real-bytecode
differential shows keeping is not just allowed but, in the common case, mandatory.)

## 5. The weight is actually usable, and it reaches the money

- **Governor trusts the persisted weight without re-checking backing.** The GAT-mint tx `f42d76033c…`
  consumes the stake (carrying its stale `F5[1]` = 63.5M) and the governor, but **no pool positions at
  all** (`POOL inputs = 0`). Quorum is judged from the persisted counter, not from live locked
  collateral. So unbacked weight votes.
- **A single stake ≥ quorum passes a proposal.** All 4 historical GAT mints came from a single stake at
  63–90M weight (> 57.5M quorum).
- **GAT → treasury.** The treasury `fcc43cd5` validator bytecode **embeds GAT policy `33230e1d…`**
  (CBOR `…4c011e581c33230e1de259…`, `581c` = 28-byte string) and does *not* reference any other policy.
  The 780M-CLARITY treasury is drainable by exactly the governance whose stakes are recyclable — the
  finding did **not** conflate two DAOs (I checked: an unrelated `977cd5f1` GAT seen near the treasury
  belongs to a different DAO's tx that merely co-located).
- **No brakes.** No validator contains an admin pubkeyhash, pause flag, or timelock constant — governance
  is weight-only and the scripts are immutable. The only possible response to an in-flight attack is
  social (off-chain), during the multi-day voting window.

## 6. Attacker profit · collateral · conditions

- **Collateral needed:** a small, **fully-recoverable** amount of CLARITY to recycle (finding's figure
  ~9,805 ADA ≈ $2,136, recovered at the end). The only unrecoverable cost is gas + DEX round-trip
  slippage (a few hundred $). No large capital is ever at risk of freezing — funds stay in the attacker's
  own UTXOs (no admin/pause exists), self-locked ~30 min per cycle.
- **Realized profit:** **liquidity-capped**, not the nominal treasury value. Nominal treasury ≈ 780.38M
  CLARITY (~$291k at CLARITY≈$0.000374, ADA=$0.2217) + ~$505 ADA, but CLARITY trades on a thin,
  ~zero-volume DEX, so an attacker can only realize on the order of the finding's **~$37.5k** (dump into
  the pool + drain its ADA side) plus an illiquid token basket. The finding's honest de-rating to **HIGH
  (design-Critical)** on these grounds is fair.
- **Value at risk:** total governance control of the DAO — its treasury (~$291k nominal here), and, since
  the stake/pool/governor scripts are parameterized copies, **every** Clarity DAO on the same code
  (system-wide treasuries ≈ 1.05B CLARITY nominal). The ceiling rises the moment any Clarity DAO holds a
  liquid token or a larger external treasury.
- **Conditions:** outsider deposits + locks CLARITY and drives a stake to ≥ 57.5M weight by recycling
  (no admin/whitelist gate found in any validator); creates + passes a proposal; mints a GAT; drains the
  treasury. Non-atomic — spans the recycle time (hours) + the multi-day voting window. No privileged
  access required.

## 7. Severity

**HIGH**, design-Critical. The broken invariant is the entire economic security model of the governance
system ("quorum costs quorum-worth of locked token"). It is permissionless, live, and cheap
(recoverable capital + gas). Realized single-shot theft is bounded today only by CLARITY's illiquidity
and the non-atomic multi-day window with a possible (soft, off-chain-only) social reaction — not by any
on-chain guard. Fix: make delock mandatorily decrement `F5[1]` by the unlocked amount (or derive voting
weight from currently-locked positions at read time), restoring `Σ weight ≤ Σ locked`.

## 8. Residual / not fully closed

- I did **not** stand up a Cardano fork to run the full recycle loop end-to-end. Instead every primitive
  was confirmed independently in mainnet history: lock adds weight (redeemer 0, 61×), delock keeps weight
  while freeing collateral (redeemer 2, 37×), governor spends stake weight without pool backing (GAT
  mint), GAT authorizes the treasury (bytecode). The composition is therefore established from live
  behavior rather than a synthetic PoC.
- Permissionless *stake/proposal creation* is strongly supported (a plain user wallet created a stake;
  **no admin pubkeyhash exists in any validator**) but I did not isolate the exact governor redeemer that
  gates creation. If creation were somehow gated, the attacker profile narrows toward "insider," but the
  weight-inflation defect itself is unchanged.

---

*Method: DefiLlama intake → Koios live reads (address/utxo/tx/datum/script) → address bech32 decode →
full 118-tx stake-history trace → per-delock weight-vs-unlocked analysis → validator bytecode constant
extraction + UPLC decompile (uplc 1.3.3). Evidence in `audit/evidence/`.*
