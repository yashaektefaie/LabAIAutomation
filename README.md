# Opentrons Agent Tools

Small local tools for inspecting and driving Opentrons robots through the same
robot-facing interfaces used by the desktop app.

The default HTTP target is `http://<host>:31950` with `Opentrons-Version: 3`.
Read-only commands do not require confirmation. Commands that mutate robot state
or may move hardware require:

```sh
--allow-action --confirm ACTIONS_CAN_MOVE_HARDWARE
```

## First Checks

```sh
python3 -m opentrons_tools discover-mdns --seconds 5
python3 -m opentrons_tools probe 192.168.1.10 opentrons.local
python3 -m opentrons_tools --host 192.168.1.10 health
python3 -m opentrons_tools --host 192.168.1.10 snapshot
python3 -m opentrons_tools --host 192.168.1.10 get /runs
```

You can also set defaults:

```sh
export OT_HOST=192.168.1.10
export OT_PORT=31950
python3 -m opentrons_tools health
```

## Protocols And Runs

Upload a protocol:

```sh
python3 -m opentrons_tools --host "$OT_HOST" upload-protocol ./protocol.py \
  --allow-action --confirm ACTIONS_CAN_MOVE_HARDWARE
```

Create a run from a protocol ID:

```sh
python3 -m opentrons_tools --host "$OT_HOST" create-run --protocol-id "<protocol-id>" \
  --allow-action --confirm ACTIONS_CAN_MOVE_HARDWARE
```

Send a run action:

```sh
python3 -m opentrons_tools --host "$OT_HOST" run-action "<run-id>" play \
  --allow-action --confirm ACTIONS_CAN_MOVE_HARDWARE
```

Send a command from JSON:

```sh
python3 -m opentrons_tools --host "$OT_HOST" run-command "<run-id>" \
  --command-file ./command.json \
  --allow-action --confirm ACTIONS_CAN_MOVE_HARDWARE
```

Delete a temporary run after testing:

```sh
python3 -m opentrons_tools --host "$OT_HOST" delete-run "<run-id>" \
  --allow-action --confirm ACTIONS_CAN_MOVE_HARDWARE
```

## Safe Motion Commands

The live-tested first motion is homing. It waits for completion by default:

```sh
python3 -m opentrons_tools --host "$OT_HOST" home "<run-id>" \
  --allow-action --confirm ACTIONS_CAN_MOVE_HARDWARE
```

For ad-hoc absolute coordinate movement, prefer `move-mount`. It sends the
Protocol Engine `robot/moveTo` command, which does not require a protocol
pipette ID:

```sh
python3 -m opentrons_tools --host "$OT_HOST" move-mount "<run-id>" left \
  --x 200 --y 150 --z 150 --speed 20 \
  --allow-action --confirm ACTIONS_CAN_MOVE_HARDWARE
```

For a cautious high-Z movement test on an empty OT-2 deck:

```sh
python3 -m opentrons_tools --host "$OT_HOST" health
python3 -m opentrons_tools --host "$OT_HOST" get /runs
python3 -m opentrons_tools --host "$OT_HOST" get /modules
python3 -m opentrons_tools --host "$OT_HOST" get /instruments

python3 -m opentrons_tools --host "$OT_HOST" create-run \
  --allow-action --confirm ACTIONS_CAN_MOVE_HARDWARE

python3 -m opentrons_tools --host "$OT_HOST" home "<run-id>" \
  --allow-action --confirm ACTIONS_CAN_MOVE_HARDWARE

python3 -m opentrons_tools --host "$OT_HOST" move-mount "<run-id>" left \
  --x 200 --y 150 --z 150 --speed 20 \
  --allow-action --confirm ACTIONS_CAN_MOVE_HARDWARE
```

If that succeeds, a small high-Z square that has been tested on the live OT-2 is:

```text
left mount, speed 20, z 150:
(210, 150, 150)
(210, 160, 150)
(200, 160, 150)
(200, 150, 150)
```

Finish by homing and deleting the temporary run. Avoid low-Z moves, plunger
movement, tip pickup/drop, `forceDirect`, and protocol execution until those
paths have been tested deliberately.

## Generic API

Read any endpoint:

```sh
python3 -m opentrons_tools --host "$OT_HOST" get /modules
```

Call any endpoint:

```sh
python3 -m opentrons_tools --host "$OT_HOST" request POST /runs \
  --body-json '{"data":{"protocolId":"<protocol-id>"}}' \
  --allow-action --confirm ACTIONS_CAN_MOVE_HARDWARE
```

## Notifications

MQTT notification listening uses `paho-mqtt` if installed and otherwise falls
back to a small standard-library MQTT v5 client:

```sh
python3 -m opentrons_tools --host "$OT_HOST" mqtt-listen \
  --topic robot-server/runs --seconds 10
```

## Live-Tested Notes

On 2026-06-09, the tools were tested against an OT-2 at `169.254.126.66`
named `OT2CEP20210802R07`, running API `9.0.0`. Verified paths:

- health and status reads
- run creation and deletion
- homing through `/runs/{id}/commands`
- high-Z `robot/moveTo` absolute movement of the left mount
- MQTT connect/subscribe

Not yet verified: protocol upload/execution, tip pickup/drop, plunger movement,
aspirate/dispense, labware offsets, module control, and camera capture.

## Notes

- These tools currently cover the network HTTP/MQTT path.
- USB Flex control needs Opentrons' serial HTTP bridge behavior. The desktop app
  implements that internally; this package intentionally starts with the safer
  network path.
- Do not run mutating commands unless the robot deck is clear and you intend to
  change robot state.
