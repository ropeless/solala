# Tapo P110M Matter experiment

The P110M firmware 1.4.1 advertises TPAP encryption, which python-kasa 0.12.0
does not recognise. This separate experiment uses Matter instead.

## Prerequisite

Run a Matter controller/server accessible through a WebSocket endpoint (typically
`ws://HOST:5580/ws`). The Python demo is a *client*, not a Matter controller.
A standalone Matter Server is generally easiest to run on a Linux machine or
container with working IPv6/mDNS access to the P110M. A reserved IPv4 address
alone is insufficient for Matter commissioning and discovery.

The plug must be commissioned onto the Matter server's fabric. In the Tapo app,
open Matter pairing / multi-admin commissioning and obtain a *fresh* setup code.
Do not commit or share that code. A code printed on the plug may not be valid
for adding another controller after the Tapo app has already commissioned it.

## Run

From the project root, after `poetry lock` and `poetry install`:

```powershell
$env:MATTER_SERVER_URL = "ws://YOUR_MATTER_SERVER:5580/ws"
poetry run python src/solala_demo/demo_tapo_matter.py
```

If no nodes are listed, open a Matter pairing window in the Tapo app:

```powershell
$env:MATTER_PAIRING_CODE = "YOUR_TEMPORARY_PAIRING_CODE"
poetry run python src/solala_demo/demo_tapo_matter.py --action commission
```

Then inspect the resulting node ID and endpoint. Only after confirming them,
test the relay:

```powershell
poetry run python src/solala_demo/demo_tapo_matter.py --action on --node 1
poetry run python src/solala_demo/demo_tapo_matter.py --action off --node 1
```

Replace node 1 with the ID returned by your Matter server. The default
OnOff endpoint is 1; change `--endpoint` if the discovered device uses another.

## Scope and limitations

This is an exploratory WebSocket client, not a production integration.
It does not install or launch a Matter Server, and it has not been tested against
the physical P110M. Commissioning may require network/mDNS/IPv6 configuration
on the server host. The node dump may include device identifiers: review it
before sharing. No credentials or pairing codes should be committed.
