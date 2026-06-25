# Lab AI Automation — Robot Agent Tools

Small local tools for inspecting and driving lab liquid handlers through the same
robot-facing interfaces used by their desktop apps. Two instrument families are
supported today:

- **Opentrons** OT-2 / Flex — `opentrons_tools` (HTTP API on port 31950) — see below.
- **Hamilton Microlab Prep** — `hamilton_tools` (REST API with JWT auth) — see
  [Hamilton Microlab Prep](#hamilton-microlab-prep). Full capability reference:
  [`hamilton_tools/CAPABILITIES.md`](hamilton_tools/CAPABILITIES.md).

---

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

---

# Hamilton Microlab Prep

`hamilton_tools` drives a Hamilton Microlab Prep through its native REST API
(`http://<prep-ip>/api/v1/...`). Architecture mirrors `opentrons_tools`: a stdlib
HTTP client, an argparse CLI, the same `--allow-action --confirm
ACTIONS_CAN_MOVE_HARDWARE` safety gate for anything that mutates state or moves
hardware, and JSON output on stdout.

**What the machine can do is catalogued in
[`hamilton_tools/CAPABILITIES.md`](hamilton_tools/CAPABILITIES.md)** — pipetting
tools (the two roaming independent channels + the 8-channel head), step types,
integrated devices (Heater-Shaker/Cooler, HEPA/UV, lighting), gripper/transport,
camera/vision, calibration, diagnostics, and the full run lifecycle. Read that
file first when planning a protocol.

The Prep API differs from Opentrons in one important way: it uses **JWT
authentication**. Log in once, then pass the token on every call.

## First Checks

```sh
# Authenticate (prompts for password if not given); prints the JWT token
python3 -m hamilton_tools --host 192.168.1.50 login --username labuser

export HAMILTON_HOST=192.168.1.50
export HAMILTON_TOKEN=<token-from-login>

python3 -m hamilton_tools system-ready
python3 -m hamilton_tools snapshot
python3 -m hamilton_tools instruments
python3 -m hamilton_tools run-state
```

Defaults are read from `HAMILTON_HOST`, `HAMILTON_PORT`, `HAMILTON_TOKEN`,
`HAMILTON_TIMEOUT`, and `HAMILTON_HTTPS`. The `login` subcommand also reads
`HAMILTON_USER` / `HAMILTON_PASSWORD`.

## Safe Motion Command

The equivalent of Opentrons homing is **`initialize`**, which homes all axes to a
known safe position. It is the first motion to run on a clear deck:

```sh
python3 -m hamilton_tools is-initialized          # read-only: false before
python3 -m hamilton_tools initialize \
  --allow-action --confirm ACTIONS_CAN_MOVE_HARDWARE
python3 -m hamilton_tools run-state               # -> Initialized
```

## Protocols And Runs

```sh
python3 -m hamilton_tools list-protocols
python3 -m hamilton_tools get-protocol 1
python3 -m hamilton_tools validate-protocol 1
python3 -m hamilton_tools preview-protocol 1

# Execute: create run -> load -> (runs) -> cleanup
python3 -m hamilton_tools create-run 1 \
  --allow-action --confirm ACTIONS_CAN_MOVE_HARDWARE
python3 -m hamilton_tools load-instructions
python3 -m hamilton_tools load-complete \
  --allow-action --confirm ACTIONS_CAN_MOVE_HARDWARE

python3 -m hamilton_tools pause  --allow-action --confirm ACTIONS_CAN_MOVE_HARDWARE
python3 -m hamilton_tools resume --allow-action --confirm ACTIONS_CAN_MOVE_HARDWARE
python3 -m hamilton_tools abort  --allow-action --confirm ACTIONS_CAN_MOVE_HARDWARE

python3 -m hamilton_tools list-run-data
python3 -m hamilton_tools get-run-data <run-data-id>
```

## Choosing the pipetting tool

Pipetting happens inside protocol steps; each step's `channelSelection` picks the
tool: `OneChannel` / `TwoChannel` (the roaming independent channels) or
`EightChannel` (the MPH). Both can be used across one protocol — one tool per
step. Add a step with the generic `request` command:

```sh
python3 -m hamilton_tools request POST /api/v1/protocols/1/step \
  --body-json '{"stepType":"TransferSamples","name":"stamp col","channelSelection":"EightChannel"}' \
  --allow-action --confirm ACTIONS_CAN_MOVE_HARDWARE
```

(See `CAPABILITIES.md` §3–§4 for full step bodies and pipetting settings.)

## Generic API

Any endpoint in the spec is reachable directly:

```sh
python3 -m hamilton_tools get /api/v1/diagnostics
python3 -m hamilton_tools request PUT /api/v1/thermal-device/hhc/start-temperature-control \
  --body-json '{"temperature":37.0}' \
  --allow-action --confirm ACTIONS_CAN_MOVE_HARDWARE
```

## Notes

- The Prep exposes no ad-hoc move/aspirate calls — all liquid handling is authored
  as protocol steps and executed as a run. See `CAPABILITIES.md` §2.
- JWT tokens expire (~5 min). Use `renew-token` or re-`login` for long sessions.
- Without hardware, point the API at the built-in mock instrument (`use-mock`).
- The repo's `venus api.json` is a *separate* API for STAR/Vantage robots and does
  not apply to the Prep (CAPABILITIES.md §14).
- Do not run mutating commands unless the deck is clear and you intend to change
  instrument state.
