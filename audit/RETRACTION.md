# RETRACTION — "Recyclable voting weight" is a FALSE POSITIVE

**Verdict: WITHDRAWN. There is no recyclable-voting-weight vulnerability in Clarity.**
The earlier `VERIFICATION.md` ("CONFIRMED / HIGH") and the `poc/` "3,100 ADA → +$38k" PoC are
**wrong** and are retracted. The error was a **component misidentification**, caught by a peer
re-audit and confirmed here directly against mainnet (Koios + deployed bytecode, epoch 654).

## The single mistake everything hinged on

I labeled script `08921c4b…` a *stake* validator whose datum field `F5[1]` is "one owner's
recyclable voting weight." It is not. `08921c4b…` is the **Agora Proposal validator**, and its
datum is the 8-field `ProposalDatum`; field 5 is the **votes** map, so `F5[1]` is `votes[outcome 1]`
— a *single proposal's accumulated tally across many voters*, not a per-owner weight.

Corrected component map:

| script | I called it | what it actually is |
|---|---|---|
| `251f79b3…` | "custody pool" | **Agora Stake validator** — 4-field `StakeDatum [stakedAmount, owner, delegatedTo, lockedBy]`; each stake **holds CLARITY == stakedAmount**, so weight is always backed |
| `08921c4b…` | "stake, F5[1]=weight" | **Agora Proposal validator** — 8-field `ProposalDatum`; `F5[1] = votes[1]` tally |
| redeemer 0 | "lock" | `PVote` |
| redeemer 2 | "delock" | `PUnlock` |
| `a21eb594…` | governor | governor (correct) |
| `fcc43cd5…` | treasury | a real treasury (correct) |

Proof it's a `ProposalDatum` (decode any UTXO at `08921c4b`): 8 fields =
`[proposalId, effects, status, cosigners, thresholds, votes, timingConfig, startingTime]`.
All 5 live proposals have `status = 3 (Finished)`, `thresholds[0] = 57,500,000,000,000` (the 57.5M
quorum), and per-outcome `effects`. My "stake" reading silently ignored six of the eight fields
(`effects, status, cosigners, thresholds, timingConfig, startingTime`) — none of which a stake has.

## Why each part of the finding re-reads as normal governance

1. **"318M weight vs 65M locked → 253M unbacked"** — category error.
   `318,049,654` = sum of `votes[1]` over **5 Finished proposals** (elections over ~2 years).
   `65,098,023` = a **current snapshot** of stakes still holding a lock. Subtracting a two-year
   cumulative tally from a point-in-time lock set is meaningless. One 25M stake voting in 4
   proposals contributes 100M to the cumulative tally from 25M of backing.

2. **"Every vote is backed" — verified, 61/61 exact.** For every tally-increase tx, the rise in
   `votes[1]` equals the summed `stakedAmount` of the `251f79b3` **stake inputs** in that same tx.
   Zero inflation. (My original flow analysis had empty tx inputs and never summed the stake
   inputs per vote — the "one vote tx carries several stake inputs" trap. The tx I cited as
   "recycling," `208c8071`, is one owner's **5 stakes** summing to exactly the delta.)

3. **"Delock keeps weight" — true but inert.** `PUnlock` leaving the tally unchanged only happens
   on a **Finished** proposal (the election is over). My real-bytecode "proof" (`verify_bytecode.py`
   GATE 1) ran `PUnlock` on proposal 0, whose `status = 3 (Finished)` at that tx — so keeping the
   frozen tally is correct, not a bug. On a **VotingReady** proposal, `PUnlock` (retract) decrements
   the tally (tx `1ca043e4`, status = 1). And you **cannot `PVote` on a Finished proposal** —
   verified: 0 of 61 PVotes occurred at status 3 — so a preserved tally can't drive anything new.

4. **"Governor mints GAT from persisted weight without backing"** — that's normal Agora execution:
   a **passed proposal** (whose tally was accumulated from real backed votes) is consumed to mint
   its effect's GAT. No stake input at execution is expected because voting already happened.

## What is actually true (kept from the original, still correct)

The on-chain *numbers* and addresses were read correctly; only the *interpretation* was wrong.
Still accurate: the contract addresses; the treasury `fcc43cd5` holds 780,384,895 CLARITY; the
treasury validator releases funds on a GAT burn; there is no admin/pause/timelock. But because
governance is **not cheaply capturable** (votes require real locked stake, per §2 above), none of
this yields cheap theft.

## The two "genuinely open" items — now CHECKED (both clean, not cheap-theft)

### (a) `2c036098…` and the other unrevealed treasuries
- It holds **5,131 ADA + ~21 illiquid small-cap tokens** (nominal ~$16k, but realizable value is
  dominated by the ADA, ~$1.1k). Its validator is genuinely **not on-chain** (never spent, no
  reference script) so it cannot be decompiled — and there are **7** such unrevealed treasuries,
  not one.
- But it has empty `Constr0[]` datums and treasury-style holdings, i.e. the **type-A treasury
  family**. Decompiling all **11 revealed** type-A treasuries shows they are **byte-identical
  except for a single embedded GAT policy** — one parameterized validator whose spend condition is
  "burn this DAO's GAT." `2c036098` is almost certainly another instance, spend-gated on its DAO's
  GAT (governance). The preimage can't be *confirmed* until first spend (a genuine limitation), but
  a non-standard/weaker script is very unlikely, and the value at stake is small.
- **Verdict:** governance-gated like the rest; not a cheap-theft path.

### (b) Treasury-withdrawal effect output-binding — the destination IS bound
Examined a real drain (tx `cbaa7f9b…`): treasury `ed927ac0` spent, GAT `50fc1b9c` **burned**, effect
`8c690736` spent, funds paid out. The effect's datum is the Agora `TreasuryWithdrawalDatum`:
`receivers = [(addr, value), …]` **plus** `treasuries = [ScriptCredential(ed927ac0)]`, committed via
DatumHash in the proposal's `effects` map at proposal creation (so voters approve the exact payout).
The two actual outputs matched **both committed receivers exactly** — address *and* amount
(`5.000000` + `1.017160` ADA to the committed `addr1q8jeyy88…` = pkh `e59210e7…`/stake `6c2f7862…`).
The effect validator embeds the GAT policy and enforces the receiver list with `equalsData` (12×),
and the GAT is minted to the effect UTXO carrying that committed datum, so the executor cannot swap
it. **The destination is fixed at proposal creation, not chosen by the executor — no execution
hijack / output redirection.** (I confirmed the treasury validator accepts a faithfully
reconstructed context and got the stake-delock replay to ACCEPT, but did not get this specific
multi-input effect-spend context to ACCEPT in isolation; per the paired-control rule I draw nothing
from that rejection — the binding conclusion rests on the exact on-chain receiver match + the
`TreasuryWithdrawalDatum` structure + the `equalsData` enforcement, which don't depend on the eval.)

**Net:** both items are governance-gated, and governance is not cheaply capturable (the body of this
retraction). Neither is a cheap-theft path. The on-chain logic has no open cheap-theft exit.

## Root cause of the false positive (for my own process)

- I never decoded the full `ProposalDatum` semantics — I pattern-matched field 0 and field 5 to
  "id + weight" and ran with it, ignoring the six fields that identify it as a proposal.
- My transaction-flow reconciliation compared an aggregate tally to a lock snapshot instead of
  reconciling **each vote against the stake inputs that produced it** (the decisive §-3 check).
- The "real-bytecode PoC" I built to be convincing evaluated a **Finished-proposal** `PUnlock`
  context, so it faithfully proved *correct* behavior while I read it as the bug. A paired control
  (a legit action that must ACCEPT, and voting that must be gated by status) would have caught it;
  the isolated PoC had none.

## Reproduce the correction

```bash
python3 poc/verify_onchain.py     # decode 08921c4b datum -> 8-field ProposalDatum, status=3
# vote-backing (61/61 delta == summed stakedAmount of 251f79b3 stake inputs): audit/evidence/
```

Credit: the correcting checks (decode the ProposalDatum; sum all stake inputs per vote tx; pair
each PoC action with a control; note that PUnlock only preserves votes on a Finished proposal) came
from a peer auditor's note. They were right; the original finding was not.
