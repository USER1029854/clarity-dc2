# PoC — Clarity governance capture (recyclable voting weight → treasury drain)

One attacker wallet goes from **3,100 ADA (~$687)** to **~175,000 ADA (~$38k realized)**
using only recoverable capital. The exploit chain and each gate's grounding:

```
buy small CLARITY chunk ──► recycle (lock→delock→withdraw→re-lock) ──► weight ≥ quorum
     (DEX, recoverable)         BUG: delock keeps weight                (57.5M)
                                                                            │
        drain treasury  ◄── burn GAT 33230e1d ◄── pass proposal (single stake ≥ quorum)
     (780M CLARITY + ADA)      REAL treasury validator                 no backing checked
                                                                            │
              dump looted CLARITY on Minswap ──► ~170k ADA (liquidity-capped)
```

## Files

| file | what it does | needs |
|---|---|---|
| `poc.py` | end-to-end eUTXO emulator, strict value conservation; prints the wallet ledger 3,100 ADA → +$38k | none (offline); `--live` re-reads figures from Koios |
| `verify_bytecode.py` | runs **both real deployed validators** in the UPLC CEK machine — GATE 1: stake `08921c4b` on a real delock context (ACCEPTS keeping weight, REJECTS reducing it); GATE 2: treasury `fcc43cd5` (GAT burn → releases all funds, negative controls) | `pip install uplc==1.3.3 cbor2==5.6.5` |
| `verify_onchain.py` | re-proves the bug from **live chain**: 318M weight vs 65M locked, and a real delock tx that kept weight while freeing 5M CLARITY | network (Koios) |
| `MAINNET_VS_FORK.md` | part-by-part: what's a fork/emulator artifact and what each piece becomes on mainnet (the `vm.prank`/`deal`/`warp` analogs, per-line mapping) | — |
| `data/` | real deployed bytecode (`stake_08921c4b.cbor`, `treasury_fcc43cd5.cbor`) + real delock tx data used to reconstruct the contexts | — |

## Run

```bash
pip install uplc==1.3.3 cbor2==5.6.5
python3 poc.py               # the wallet PoC: 3,100 ADA -> ~+$38k
python3 verify_bytecode.py   # REAL stake + treasury bytecode: delock keeps weight; GAT burn drains
python3 verify_onchain.py    # live chain: 253M of unbacked weight; real delock keeps weight
```

Fork-vs-mainnet mapping (what an attacker actually does): see `MAINNET_VS_FORK.md`.

## Expected output (poc.py)

```
 START: attacker wallet = 3,100 ADA  (~$687)
 [1] buy 1,633,614 CLARITY chunk           (300 ADA left)
 [2] recycle 36× -> stake weight 58,810,115 ≥ quorum 57,500,000   (backing locked ≈ 0)
 [3] pass proposal -> mint GAT -> drain treasury: +780,384,895 CLARITY + 2,277 ADA
 [4] dump looted CLARITY on Minswap
 END  : attacker wallet ≈ 175,452 ADA  (~$38,898)
 NET PROFIT ≈ 172,352 ADA  (~$38,210)   capital 3,100 ADA fully recovered
```

## Why each step is real (not modeled)

- **Recyclable weight (the bug):** `verify_bytecode.py` GATE 1 runs the **real deployed stake
  validator `08921c4b`** on a real delock context and shows it ACCEPTS keeping the full weight
  while freeing the collateral (and REJECTS reducing it). On chain, the deployed validator
  accepted this in **37 of 38** real delock txs (`../evidence/delock_analysis.json`);
  `verify_onchain.py` replays one and shows 253M of live unbacked weight.
- **Weight is usable without backing:** the 4 real GAT-mint txs consumed only the stake (its
  persisted `F5[1]`), never a pool position — quorum is judged from the stale counter.
- **GAT → treasury:** `verify_bytecode.py` runs the real treasury validator and shows a single
  GAT burn releases **all** funds to an arbitrary address; it embeds GAT policy `33230e1d`.
- **Realized profit** is capped by Minswap liquidity (thin, ~0 volume), which is why ~$38k, not
  the ~$291k nominal — the honest, team-facing number.

## Note on fidelity

This does not submit to mainnet (an unprivileged submit is a call against real funds). It is a
fork-style emulator seeded with pinned real state (block 13,914,607 / epoch 654). **Both custody
gates — delock-keeps-weight and GAT-burn-drains-treasury — are executed on the real deployed
bytecode** (`verify_bytecode.py`); the deposit/withdraw/swap steps are standard, and the two
key facts are also confirmed by real mainnet txs (37 weight-keeping delocks, 4 single-stake GAT
mints). Assembling them into one wallet run is what the emulator does. `MAINNET_VS_FORK.md` maps
every simulated piece to its mainnet equivalent; `../VERIFICATION.md` has the full audit trail.
