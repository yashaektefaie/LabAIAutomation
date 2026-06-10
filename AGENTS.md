# Opentrons Agent Notes

Use this repo's tools through:

```sh
python3 -B -m opentrons_tools
```

The robot HTTP API is on port `31950` and requires `Opentrons-Version: 3`,
which the client sets automatically. Local robot network access from Codex may
need sandbox escalation.

## Safety Rules

- Do not move hardware unless the user explicitly asks and confirms the deck is
  clear.
- Every mutating command must include:

```sh
--allow-action --confirm ACTIONS_CAN_MOVE_HARDWARE
```

- Prefer read-only checks first: `health`, `get /runs`, `get /modules`,
  `get /instruments`.
- For first movement after connecting, use `home`; do not start with arbitrary
  coordinates.
- For coordinate motion, keep `z` high, use slow speed, and move one command at
  a time with default wait behavior.

## Known Live Robot

Live tests on 2026-06-09 used an OT-2 found at `169.254.126.66`:

- name/serial: `OT2CEP20210802R07`
- model: `OT-2 Standard`
- API: `9.0.0`
- left pipette: `p20_single_gen2`
- right pipette: `p300_single_gen2`

Do not assume this IP is still correct. Re-run `health` or `probe` before use.
mDNS discovery may fail on this Mac, so direct probe/checks are more reliable.

## Safe Motion Pattern

The tested movement path is:

1. `health`
2. `get /runs` and confirm no active run conflict
3. `create-run`
4. `home <run-id>`
5. `move-mount <run-id> left --x 200 --y 150 --z 150 --speed 20`
6. Optional tiny high-Z square:
   - `--x 210 --y 150 --z 150`
   - `--x 210 --y 160 --z 150`
   - `--x 200 --y 160 --z 150`
   - `--x 200 --y 150 --z 150`
7. `home <run-id>`
8. `delete-run <run-id>`
9. `get /runs` and confirm empty/expected state

`move-mount` sends Protocol Engine `robot/moveTo`. This is preferable to
`moveToCoordinates` for ad-hoc agent tests because it does not require a
protocol pipette ID and the robot calculates non-direct waypoints through the
movement handler.

## What Has Been Verified

- HTTP health/status reads
- `/runs`, `/modules`, `/instruments`
- run creation and deletion
- `home` command with `waitUntilComplete=true`
- `robot/moveTo` absolute mount movement at high Z
- MQTT connection/subscription with no messages during the test window

Not yet verified: protocol upload/execution, tip pickup/drop, plunger movement,
aspirate/dispense, labware offsets, module control, and camera capture.
