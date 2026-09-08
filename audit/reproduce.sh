#!/usr/bin/env bash
# Reproduce the key checks for the Clarity governance-capture finding.
# Uses only the free Koios Cardano API (no key required). Pinned near block 13,914,607.
set -euo pipefail
K="https://api.koios.rest/api/v1"
STAKE_ADDR="addr1wyyfy8zt2qnczsupe8rgpkzwnpfy2tyg2qmk52fccaswwps7xs2u5"   # stake validator 08921c4b
POOL_ADDR="addr1wyj377dnuxy8tt2tlzccllq90dzsdpngka930lrnqza6qqszkhsc7"    # custody pool  251f79b3
TREAS_ADDR="addr1w87vg0x4k2x95dlp7mrlef909lgk25kgajhk2dxzxk0tquclfp0at"   # treasury      fcc43cd5
CLAR="1e76aaec4869308ef5b61e81ebf229f2e70f75a50223defa087f807b"           # CLARITY token
GAT="33230e1de259f957d1d857ea37ca810950b4c47d7ed8db9086e9d28d"            # GAT policy

echo "# 1) Five live stakes; total voting weight F5[1] (expect 318.05M):"
curl -s -X POST "$K/address_utxos" -H 'content-type: application/json' \
  -d "{\"_addresses\":[\"$STAKE_ADDR\"],\"_extended\":true}" \
| jq '[.[].inline_datum.value.list[5].map[]|select(.k.int==1)|.v.int]|add'

echo "# 2) Pool CLARITY held (expect 268.18M) and currently-locked backing (expect 65.10M):"
curl -s -X POST "$K/address_assets" -H 'content-type: application/json' \
  -d "{\"_addresses\":[\"$POOL_ADDR\"]}" | jq -r ".[]|select(.policy_id==\"$CLAR\")|.quantity"

echo "# 3) Treasury fcc43cd5 CLARITY (expect 780,384,895) + ADA:"
curl -s -X POST "$K/address_assets" -H 'content-type: application/json' \
  -d "{\"_addresses\":[\"$TREAS_ADDR\"]}" | jq -r ".[]|select(.policy_id==\"$CLAR\")|.quantity"

echo "# 4) Treasury validator embeds GAT policy 33230e1d (grep the bytecode):"
curl -s -X POST "$K/script_info" -H 'content-type: application/json' \
  -d '{"_script_hashes":["fcc43cd5b28c5a37e1f6c7fca4af2fd16552c8ecaf6534c2359eb073"]}' \
| jq -r '.[0].bytes' | grep -o "$GAT" && echo "  -> present"

echo "# 5) The delock that KEEPS weight while freeing 5M collateral (tx 6a2a55a2, redeemer stake=2):"
echo "   compare stake weight in==out and the spent pool position's locks -> []"
curl -s -X POST "$K/tx_info" -H 'content-type: application/json' \
  -d '{"_tx_hashes":["6a2a55a2b32400e422f50e179b1077f2bb74ca4d586cfed0f59af75079c2799d"],"_inputs":true,"_scripts":true}' \
| jq -c '.[0].plutus_contracts[]|{script:.script_hash[0:8], redeemer_constr:.input.redeemer.datum.value.constructor}'
