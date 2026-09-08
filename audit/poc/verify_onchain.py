#!/usr/bin/env python3
# =============================================================================
# On-chain proof of the recyclable-weight bug (the primitive poc.py relies on).
#
# Re-reads live Cardano state via Koios (no API key) and shows, on the DEPLOYED
# stake validator 08921c4b, that:
#   (1) the 5 live stakes claim 318M voting weight while only ~65M CLARITY is
#       actually locked -> ~253M of weight is unbacked RIGHT NOW; and
#   (2) a real delock tx (6a2a55a2) removed a locked position's lock, freeing
#       5,000,000 CLARITY, while the stake's weight stayed exactly the same.
#
# These transactions were already validated by the whole Cardano network, so
# this IS the deployed validator accepting delock-without-decrement — the bug.
# =============================================================================
import json, urllib.request
K="https://api.koios.rest/api/v1/"
CLAR="1e76aaec4869308ef5b61e81ebf229f2e70f75a50223defa087f807b"
STAKE_ADDR="addr1wyyfy8zt2qnczsupe8rgpkzwnpfy2tyg2qmk52fccaswwps7xs2u5"
POOL_ADDR="addr1wyj377dnuxy8tt2tlzccllq90dzsdpngka930lrnqza6qqszkhsc7"

def post(ep, body):
    req=urllib.request.Request(K+ep, data=json.dumps(body).encode(),
        headers={"content-type":"application/json"})
    return json.load(urllib.request.urlopen(req, timeout=60))
def datum(dh):
    return post("datum_info", {"_datum_hashes":[dh]})[0]["value"]
def weight(stake_datum_value):
    for kv in stake_datum_value["list"][5]["map"]:
        if kv["k"]["int"]==1: return kv["v"]["int"]

print("[1] Five live stakes at 08921c4b — weight vs locked backing")
stakes=post("address_utxos", {"_addresses":[STAKE_ADDR], "_extended":True})
total_w=sum(weight(s["inline_datum"]["value"]) for s in stakes)
pool=post("address_utxos", {"_addresses":[POOL_ADDR], "_extended":True})
locked=sum(p["inline_datum"]["value"]["list"][0]["int"]
           for p in pool if p["inline_datum"]["value"]["list"][3]["list"])
print(f"    stakes                : {len(stakes)}")
print(f"    total voting weight    : {total_w/1e6:,.0f} CLARITY")
print(f"    currently locked       : {locked/1e6:,.0f} CLARITY")
print(f"    UNBACKED weight        : {(total_w-locked)/1e6:,.0f} CLARITY  <-- the ratchet\n")

print("[2] Replaying a real delock tx (6a2a55a2): weight kept while 5M freed")
tx=post("tx_info", {"_tx_hashes":["6a2a55a2b32400e422f50e179b1077f2bb74ca4d586cfed0f59af75079c2799d"],
                    "_inputs":True,"_scripts":True})[0]
# stake weight before (from spent input datum) and after (output datum)
sc=[p for p in tx["plutus_contracts"] if p["script_hash"].startswith("08921c4b")][0]
w_before=weight(sc["input"]["datum"]["value"])
redeemer=sc["input"]["redeemer"]["datum"]["value"]["constructor"]
w_after=None
for o in tx["outputs"]:
    if o["payment_addr"]["bech32"]==STAKE_ADDR:
        w_after=weight(datum(o["datum_hash"]))
# pool position: locks before/after
pc=[p for p in tx["plutus_contracts"] if p["script_hash"].startswith("251f79b3")][0]
pos_in=pc["input"]["datum"]["value"]["list"]
freed=pos_in[0]["int"]; locks_in=len(pos_in[3]["list"])
print(f"    stake redeemer         : {redeemer}  (2 = delock)")
print(f"    position freed         : {freed/1e6:,.0f} CLARITY  (locks before={locks_in} -> after=0)")
print(f"    stake weight before    : {w_before/1e6:,.0f} CLARITY")
print(f"    stake weight after     : {w_after/1e6:,.0f} CLARITY")
print(f"    weight change          : {(w_after-w_before)/1e6:+,.0f} CLARITY")
assert w_after==w_before, "expected weight unchanged"
print("\n    => deployed validator ACCEPTED freeing 5,000,000 CLARITY of backing")
print("       while the stake kept its full weight. Recycle this => unbounded weight.")
