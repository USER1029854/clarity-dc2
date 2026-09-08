# Fork/emulator vs. mainnet — what's simulated and what an attacker actually does

This explains, part by part, which pieces of the PoC are **fork/emulator artifacts**
and what each one **becomes on mainnet** — so you can read it the way you'd read a
Foundry PoC's cheatcodes.

## 0. The big picture

A PoC never runs the attack on mainnet (an unprivileged submit is a real theft). Instead
it runs against a **fork**: a copy of the ledger seeded from real state at a pinned point,
where you can drive transactions and let the *real* validators judge them. On EVM that's
`vm.createSelectFork(RPC, block)` in Foundry. On Cardano (eUTXO) there's no single standard
"anvil"; the equivalent is either a local devnet replaying the real scripts, or — what we do
here — an emulator that holds the real UTXOs and calls the **real deployed validator bytecode**
(`verify_bytecode.py` runs the actual 08921c4b and fcc43cd5 scripts in the same CEK machine a
node uses in phase-2). The economics (`poc.py`) are a strict value-conserving ledger on top.

The key mental model difference from EVM:

| | EVM | Cardano (this target) |
|---|---|---|
| who is "the caller" | `msg.sender` | there is none; a validator checks the tx's **signatories** list + the UTXOs it spends |
| impersonation | `vm.prank(addr)` fakes `msg.sender` | **not needed** — the attacker uses their *own* keys; you never impersonate a victim |
| giving yourself funds | `deal(token, you, amt)` | buy on a DEX, or seed a UTXO in the emulator; on mainnet you actually acquire it |
| moving time | `vm.warp` / `vm.roll` | set the tx **validity interval**; on mainnet time simply passes |
| "the exploit contract" | a Solidity attacker contract | a sequence of **transactions** you build, sign, and submit |

## 1. The `vm.prank` question specifically

There is **no prank here, and none is needed.** On EVM you `prank` to speak as an address whose
key you don't hold (e.g. impersonate a whale or an admin). This exploit is *permissionless*: the
attacker acts only as **themselves**, from a wallet they fund. The one place a "who signed" fact
appears is inside the reconstructed `ScriptContext`:

```python
# verify_bytecode.py, stake_context()
sigs = Lst([Bs(signer_pkh(wallet['payment_addr']['bech32']))])   # tx signatories
```

On mainnet that list is populated by a **real Ed25519 witness** from the attacker's own signing
key — you literally sign the transaction. We assert it in the context because we're not carrying
real keys; that is the *only* "assumed" signature, and it's the attacker's own, not a victim's.
We never fake the DAO team, an admin, or any existing stake owner.

(In the delock replay we reuse the *real historical* signer `32d04e9c…` because we're replaying a
real tx to prove the validator's behavior. In a fresh attack that pkh becomes the attacker's own.)

## 2. Part-by-part: `poc.py`

| PoC line / symbol | fork/emulator artifact | on mainnet it is… |
|---|---|---|
| `L.wallet_ada = 3100` | we set a starting balance | a real wallet you fund with 3,100 ADA (buy on an exchange, withdraw). Own money, no cheat. |
| `ADA_USD`, `POOL_ADA/POOL_CLAR`, `QUORUM`, `TREASURY_CLAR` | constants pinned at block 13,914,607 | live values read at submit time — they **drift**; `--live` re-reads them from Koios. Re-price before quoting profit. |
| `class Ledger` + `_assert` conservation | our stand-in for the ledger rules | the Cardano node: it enforces value conservation *and* runs every validator. Our `_assert` mimics only the value half; `verify_bytecode.py` supplies the validator half on the real code. |
| `dex_buy_clar` / `dex_sell_clar` | constant-product math (x·y=k, 0.3% fee) | a real Minswap swap you submit; a batcher fills it. Price impact/slippage are real (that's what caps the payout), and ordering/MEV can move the fill. |
| `lock(chunk)` | `stake_weight += chunk` (int) | a real tx: spend your pool position + your stake UTXO with **stake redeemer 0**, output the stake datum with `F5[1]` raised. The node runs 08921c4b, which accepts it (61 such txs exist on chain). |
| `delock_keep_weight(chunk)` | frees `locked`, leaves `stake_weight` (the bug) | a real tx with **stake redeemer 2** whose output stake datum keeps `F5[1]`. **This is exactly what `verify_bytecode.py` GATE 1 runs on the real validator** — it ACCEPTS keeping the weight (and in that context *forbids* reducing it). |
| `withdraw(chunk)` | `wallet_clar += chunk` | a real tx spending the now-unlocked pool position back to your wallet (the inverse of a deposit). |
| the `while weight < QUORUM` loop, `cycles`, `LOCK_WINDOW_MIN` | a Python counter | real elapsed time: each cycle waits out the 30-min lock deadline. See §4 on why skipping it is legitimate. |
| `drain_treasury()` | `wallet += TREASURY_CLAR` if weight≥quorum | the governance execution: create+pass a proposal on your ≥quorum stake, mint a GAT (33230e1d), burn it against the treasury input. **`verify_bytecode.py` GATE 2 runs the real treasury validator** — one GAT burn releases everything to your address. |

## 3. Part-by-part: `verify_bytecode.py` (this is the *most* mainnet-faithful piece)

This runs the **real deployed bytecode**. What's still reconstructed vs. what a node does:

- `uplc.eval(prog, datum, redeemer, ctx)` — the CEK machine here is the same evaluation a node
  performs in phase-2. `prog` is the *actual* on-chain script (`data/*.cbor`, fetched from chain).
  **This is not a model of the validator; it is the validator.**
- The `ScriptContext` (`stake_context`, `treasury_context`) — on mainnet the **node builds this
  for you** from the transaction you submit. Here we build it by hand. For GATE 1 we build it from
  a *real* delock tx (all inputs/outputs/datums/validity/signer are the on-chain values), so it is
  faithful by construction — that's why the real validator accepts it. For GATE 2 we construct a
  spend that burns a GAT; the destination output is an **arbitrary attacker address** (`bb..`),
  which is the point: the validator doesn't constrain where the money goes.
- Slot→POSIX (`slot_to_posix_ms`) — the node does this conversion from its era parameters; we
  hardcode the mainnet Shelley anchor. It only matters for the validity interval / lock deadline.

The two facts GATE 1/2 establish on the real code:
- delock **accepts keeping the full weight** while the collateral is freed (and won't let you
  reduce it in that context) → weight is a forced ratchet;
- a single **GAT burn drains the whole treasury** to any address.
Everything else in the chain is either standard (deposit/withdraw/swap) or already on chain
(37 real delocks kept weight; 4 real GAT mints came from a single stake with no backing input).

## 4. Time — what you may "warp" and what you may not

- The **30-minute lock deadline** per recycle cycle is *mechanical* time: nothing on mainnet stops
  the clock, no defender acts, so waiting it out (or "warping" it in a fork by setting the tx
  validity interval past the deadline) is legitimate. A 36-cycle attack is ~18h of waiting — free.
- The **multi-day proposal/voting window** is partly a *reaction* window. There is **no on-chain
  brake** (no admin key, pause, guardian, or timelock exists in any validator — we checked the
  bytecode), so the only possible response is *social/off-chain* (the team noticing and warning
  exchanges, coordinating a fork, etc.). The emulator cannot model a human defender, so `poc.py`
  treats the vote as passing. On mainnet this window is the single realistic mitigant, and it's why
  the finding is rated **HIGH / design-Critical** rather than a clean atomic Critical.

## 5. What is deliberately NOT made real (and must not be)

- **No mainnet submission.** Every "tx" is applied to the local ledger / run through the local CEK
  machine. Submitting these for real would move other people's money.
- **No real keys over real funds.** A live run uses throwaway attacker keys on a private fork; here
  we don't sign at all — we assert the attacker's own signature in the context (§1).
- **The 780M CLARITY is nominal.** `poc.py` converts the looted CLARITY to ADA through the *real*
  thin Minswap pool, so the realized number is ~$38k, not ~$291k — that liquidity cap is real and
  is the honest figure to hand a team.

## 6. If you wanted to take it all the way to a live-fork submission

The remaining gap to a "submit on a private fork" PoC is plumbing, not logic:
1. spin up a local devnet / privnet (or `cardano-node` in an isolated network) seeded with the
   pinned UTXOs (`data/*` already has the real datums/values);
2. generate throwaway attacker keys; build the lock/delock/withdraw/propose/drain txs with a
   builder (e.g. `pycardano`) instead of the int-level ledger in `poc.py`;
3. submit them to the privnet and read the resulting balances.
Steps (1)–(3) don't change any conclusion — the validators are the same bytecode `verify_bytecode.py`
already runs, and the economics are the same `poc.py` already computes. They only remove the last
hand-built pieces (the ledger bookkeeping and the ScriptContext assembly the node would do for you).
