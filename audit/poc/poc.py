#!/usr/bin/env python3
# =============================================================================
# ⚠️  RETRACTED — DEMONSTRATES A NON-BUG.  See ../RETRACTION.md
# The premise (08921c4b F5[1] = recyclable per-owner weight) is a component
# misidentification: 08921c4b is the Agora PROPOSAL validator and F5[1] is a
# proposal's VOTE TALLY. Every vote is backed by real staked CLARITY (verified
# 61/61), and you cannot PVote on a Finished proposal, so the "recycle" below
# is impossible on mainnet. This file is kept only as a record of the mistake.
# =============================================================================
# Clarity (Cardano) — Governance-capture PoC   [RETRACTED]
# "Recyclable voting weight" -> quorum -> GAT -> treasury drain -> DEX dump
#
# Wallet starts with 3,100 ADA and ends ~+$37k, using only recoverable capital.
#
# This is a local eUTXO emulator seeded with REAL, pinned mainnet state
# (block 13,914,607 / epoch 654, Conway). It does NOT submit anything to
# mainnet (an unprivileged submit would be a call against real funds). Every
# custody gate is grounded in the deployed system:
#   * the delock-keeps-weight bug is what the DEPLOYED stake validator
#     08921c4b already accepted in 37 real mainnet txs (see REAL_DELOCKS);
#   * the treasury validator fcc43cd5 releases funds on a GAT (33230e1d) burn,
#     read from its own bytecode (see verify_bytecode.py);
#   * quorum-from-a-single-stake and no-backing-at-mint are what the 4 real
#     GAT-mint txs already did.
# The emulator enforces strict value conservation on every transaction, so the
# ONLY place value is created from nothing is the weight counter — the bug.
#
# Run:  python3 poc.py          (pure-python, no network needed)
#       python3 poc.py --live   (re-reads the pinned figures from Koios first)
#
# What is simulated vs. what an attacker does on mainnet: see MAINNET_VS_FORK.md.
# The two custody gates below (delock-keeps-weight, GAT-burn-drains-treasury) are
# run on the REAL deployed bytecode by verify_bytecode.py; here they are the
# value-conserving ledger that chains them into a wallet run.
# =============================================================================
import sys, json, urllib.request

# ---------------------------------------------------------------------------
# 1) PINNED REAL STATE  (every number independently verified against Koios;
#    see ../VERIFICATION.md and ../reproduce.sh)
# ---------------------------------------------------------------------------
DECIMALS      = 6
UNIT          = 10**DECIMALS
ADA_USD       = 0.2217                 # CoinGecko, pinned read
CLAR_POLICY   = "1e76aaec4869308ef5b61e81ebf229f2e70f75a50223defa087f807b"

STAKE_SCRIPT  = "08921c4b5027814381c9c680d84e9852452c8850376a2938c760e706"
POOL_SCRIPT   = "251f79b3e18875ad4bf8b18ffc057b45068668b74b17fc7300bba002"
GOV_SCRIPT    = "a21eb594a679bc511908cde7286188a1968d4e221dfd7a35a6bf9c44"
GAT_POLICY    = "33230e1de259f957d1d857ea37ca810950b4c47d7ed8db9086e9d28d"
TREASURY      = "fcc43cd5b28c5a37e1f6c7fca4af2fd16552c8ecaf6534c2359eb073"

QUORUM        = 57_500_000 * UNIT      # stake datum field 4[0]
TREASURY_CLAR = 780_384_895_000_524    # raw CLARITY held by treasury fcc43cd5
TREASURY_ADA  = 2_277                  # ADA held by treasury (approx, lovelace/1e6)

# Minswap V2 CLARITY/ADA pool reserves (on-chain read; ~0 volume so ~static).
POOL_ADA      = 195_476.0
POOL_CLAR     = 116_024_067.0

# Governance lock window (stake datum field 6, last entry) = 1,800,000 ms.
LOCK_WINDOW_MIN = 30

# The 37 real mainnet delock txs where the DEPLOYED stake validator accepted a
# delock that FREED the locked collateral while leaving stake weight unchanged.
# (full list in ../evidence/delock_analysis.json; a few shown here as citation)
REAL_DELOCKS = [
    ("6a2a55a2b324", 5_000_000, 0),   # freed 5,000,000 CLARITY, weight delta 0
    ("0e7c47a0afc6", 25_000_000, 0),  # freed 25,000,000 CLARITY, weight delta 0
    ("9b39362979c5", 7_500_000, 0),   # freed 7,500,000 CLARITY, weight delta 0
    ("124adead4250", 25_000_000, 0),  # freed 25,000,000 CLARITY, weight delta 0
    # ... 37 total; only 1 of 38 delocks ever decremented weight.
]

def usd(ada):  return ada * ADA_USD
def c(raw):    return raw / UNIT

# ---------------------------------------------------------------------------
# 2) A tiny value-conserving eUTXO ledger
#    Every tx must conserve (ADA_in == ADA_out + fee) and
#    (CLARITY_in == CLARITY_out), EXCEPT the stake weight counter, which is
#    NOT a real asset — it is the datum field the bug lets us inflate.
# ---------------------------------------------------------------------------
class Ledger:
    def __init__(self):
        self.wallet_ada  = 0.0      # attacker wallet ADA
        self.wallet_clar = 0        # attacker wallet CLARITY (raw)
        self.pool_ada    = POOL_ADA # DEX reserves
        self.pool_clar   = POOL_CLAR
        self.fees        = 0.0
        # attacker's own stake (created permissionlessly): weight counter F5[1]
        self.stake_weight = 0
        # attacker's live pool position (locked CLARITY backing), raw
        self.locked      = 0
        self.log = []

    def _assert(self, cond, msg):
        if not cond:
            raise AssertionError("VALUE CONSERVATION VIOLATED: " + msg)

    def note(self, s): self.log.append(s)

    # ---- DEX: Minswap constant-product, 0.3% fee ----
    def dex_buy_clar(self, ada_in):
        """spend ADA, receive CLARITY (raw)"""
        self._assert(ada_in <= self.wallet_ada, "buy: not enough ADA")
        x = ada_in * 0.997
        out = self.pool_clar * x / (self.pool_ada + x)      # CLARITY units
        self.pool_ada  += ada_in
        self.pool_clar -= out
        self.wallet_ada  -= ada_in
        got = int(out * UNIT)
        self.wallet_clar += got
        self.note(f"  DEX buy : -{ada_in:,.0f} ADA  -> +{c(got):,.0f} CLARITY")
        return got

    def dex_sell_clar(self, clar_raw):
        """dump CLARITY, receive ADA"""
        self._assert(clar_raw <= self.wallet_clar, "sell: not enough CLARITY")
        cin = (clar_raw / UNIT) * 0.997
        out = self.pool_ada * cin / (self.pool_clar + cin)  # ADA
        self.pool_clar += clar_raw / UNIT
        self.pool_ada  -= out
        self.wallet_clar -= clar_raw
        self.wallet_ada  += out
        self.note(f"  DEX dump: -{c(clar_raw):,.0f} CLARITY -> +{out:,.0f} ADA")
        return out

    def fee(self, ada=0.3):
        self.wallet_ada -= ada; self.fees += ada

    # ---- custody gates (grounded in the deployed validators / real txs) ----
    def lock(self, clar_raw):
        """
        LOCK a fresh pool position of `clar_raw` CLARITY to the attacker stake.
        Deployed stake validator (redeemer 0) credits weight += locked amount.
        Value conserved: CLARITY moves wallet -> pool position (still ours).
        """
        self._assert(clar_raw <= self.wallet_clar, "lock: not enough CLARITY")
        self.wallet_clar -= clar_raw
        self.locked      += clar_raw
        self.stake_weight += clar_raw          # F5[1] += locked  (redeemer 0)
        self.fee()

    def delock_keep_weight(self, clar_raw):
        """
        DELOCK (deployed stake validator redeemer 2). Removes the lock so the
        position is withdrawable again while the stake KEEPS its full weight.
        verify_bytecode.py GATE 1 runs the real 08921c4b validator on a real
        delock context and shows it ACCEPTS keeping the weight (and, in that
        context, REJECTS reducing it -> weight is a forced ratchet). 37 real
        mainnet delock txs (REAL_DELOCKS) already did exactly this.
        Value conserved: CLARITY stays in the pool position (still ours);
        the weight counter is left untouched (the bug).
        """
        self._assert(clar_raw <= self.locked, "delock: nothing that large locked")
        self.locked -= clar_raw
        # self.stake_weight unchanged  <-- THE BUG (37/38 real delocks did this)
        self.fee()

    def withdraw(self, clar_raw):
        """Withdraw an unlocked pool position back to the wallet (inverse of deposit)."""
        self.wallet_clar += clar_raw
        self.fee()

    def drain_treasury(self):
        """
        A passed proposal mints a GAT (policy 33230e1d); burning it from the
        treasury input authorizes releasing ALL treasury funds to any address.
        The treasury validator fcc43cd5 checks only the GAT burn (read from its
        bytecode). Requires stake_weight >= QUORUM.
        """
        self._assert(self.stake_weight >= QUORUM,
                     f"weight {c(self.stake_weight):,.0f} < quorum {c(QUORUM):,.0f}")
        self.wallet_clar += TREASURY_CLAR
        self.wallet_ada  += TREASURY_ADA
        self.note(f"  DRAIN   : +{c(TREASURY_CLAR):,.0f} CLARITY  +{TREASURY_ADA:,} ADA "
                  f"(GAT burn accepted by treasury fcc43cd5)")

# ---------------------------------------------------------------------------
# 3) THE ATTACK
# ---------------------------------------------------------------------------
def run(start_ada=3100.0, buy_ada=2800.0):
    L = Ledger()
    L.wallet_ada = start_ada
    print("="*74)
    print(f" START: attacker wallet = {start_ada:,.0f} ADA  (~${usd(start_ada):,.0f})")
    print("="*74)

    # -- Step 1: buy a small CLARITY chunk to recycle -------------------------
    print("\n[1] Buy a small CLARITY chunk on Minswap (this is the ONLY capital,"
          "\n    and it is fully recovered at the end):")
    chunk = L.dex_buy_clar(buy_ada)
    print(f"    chunk to recycle = {c(chunk):,.0f} CLARITY   (wallet ADA left = {L.wallet_ada:,.0f})")

    # -- Step 2: recycle chunk -> build weight >= quorum ----------------------
    # deposit+lock -> wait 30 min -> delock (KEEP weight) -> withdraw -> repeat
    print(f"\n[2] Recycle the SAME chunk: lock -> wait {LOCK_WINDOW_MIN}m -> delock(keep weight)"
          f" -> withdraw -> re-lock.\n    Each cycle adds {c(chunk):,.0f} weight for ~free"
          " (collateral recovered every time):")
    cycles = 0
    while L.stake_weight < QUORUM:
        L.lock(chunk)                 # weight += chunk   (deployed redeemer 0)
        L.delock_keep_weight(chunk)   # lock removed, weight KEPT (the bug)
        L.withdraw(chunk)             # collateral back in wallet
        cycles += 1
        if cycles > 200: break
    print(f"    cycles       = {cycles}  (~{cycles*LOCK_WINDOW_MIN/60:.1f} h of waiting; time is free)")
    print(f"    stake weight = {c(L.stake_weight):,.0f}  >=  quorum {c(QUORUM):,.0f}   ✓")
    print(f"    real backing locked right now = {c(L.locked):,.0f} CLARITY (≈0 — weight is unbacked)")
    print(f"    wallet still holds the chunk = {c(L.wallet_clar):,.0f} CLARITY (recovered)")

    # -- Step 3: pass a malicious proposal & drain the treasury ---------------
    print("\n[3] Single stake now exceeds quorum -> pass a proposal -> mint GAT"
          " -> burn it against\n    the treasury (fcc43cd5) -> release everything:")
    L.drain_treasury()
    print(f"    wallet now = {L.wallet_ada:,.0f} ADA + {c(L.wallet_clar):,.0f} CLARITY")

    # -- Step 4: convert looted CLARITY to ADA on the DEX ---------------------
    print("\n[4] Dump looted CLARITY into Minswap (realized value is capped by pool"
          " liquidity,\n    NOT by the 780M nominal — this is the honest number):")
    L.dex_sell_clar(L.wallet_clar)

    # -- settle fees ----------------------------------------------------------
    end_ada = L.wallet_ada
    profit  = end_ada - start_ada
    print("\n" + "="*74)
    print(f" END  : attacker wallet = {end_ada:,.0f} ADA  (~${usd(end_ada):,.0f})")
    print(f" FEES : {L.fees:,.1f} ADA over {cycles} cycles + trades")
    print(f" NET PROFIT = {profit:,.0f} ADA  (~${usd(profit):,.0f})")
    print("="*74)
    print("\n Cost breakdown for the team:")
    print(f"   • capital required   : {start_ada:,.0f} ADA (~${usd(start_ada):,.0f}) — FULLY recoverable")
    print(f"   • unrecoverable cost : ~{L.fees:,.0f} ADA fees + DEX slippage (a few hundred $)")
    print(f"   • collateral at risk : 0 (funds stay in attacker UTXOs; no admin/pause exists)")
    print(f"   • time               : ~{cycles*LOCK_WINDOW_MIN/60:.0f} h recycle + multi-day vote (both free)")
    print(f"   • realized profit    : ~${usd(profit):,.0f}  (liquidity-capped)")
    print(f"   • value-at-risk      : total governance control of the DAO; treasury nominal"
          f" ~{c(TREASURY_CLAR):,.0f} CLARITY")
    return profit

def maybe_refresh_live():
    """--live: re-read the load-bearing figures from Koios before running."""
    def post(ep, body):
        req = urllib.request.Request("https://api.koios.rest/api/v1/"+ep,
              data=json.dumps(body).encode(), headers={"content-type":"application/json"})
        return json.load(urllib.request.urlopen(req, timeout=60))
    global TREASURY_CLAR
    ta = "addr1w87vg0x4k2x95dlp7mrlef909lgk25kgajhk2dxzxk0tquclfp0at"
    a = post("address_assets", {"_addresses":[ta]})
    for row in a:
        if row.get("policy_id")==CLAR_POLICY:
            TREASURY_CLAR = int(row["quantity"]); print(f"[live] treasury CLARITY = {c(TREASURY_CLAR):,.0f}")
    sa = "addr1wyyfy8zt2qnczsupe8rgpkzwnpfy2tyg2qmk52fccaswwps7xs2u5"
    u = post("address_utxos", {"_addresses":[sa],"_extended":True})
    tot = sum(next(kv["v"]["int"] for kv in x["inline_datum"]["value"]["list"][5]["map"]
                    if kv["k"]["int"]==1) for x in u)
    print(f"[live] 5 live stakes total weight = {c(tot):,.0f} (unbacked; pool holds far less locked)")

if __name__ == "__main__":
    if "--live" in sys.argv:
        try: maybe_refresh_live()
        except Exception as e: print("[live] skipped:", e)
    run()
