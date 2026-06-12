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
- Raspberry Pi 5 to OT-2 bridge over a USB Ethernet adapter
- OT-2 lights endpoint: `GET /robot/lights`, `POST /robot/lights`
- MQTT connection/subscription with no messages during the test window

Not yet verified: protocol upload/execution, tip pickup/drop, plunger movement,
aspirate/dispense, labware offsets, module control, and camera capture.

## Raspberry Pi to OT-2 Bridge

On 2026-06-12, `raspi-codex` was used as the network bridge to the live OT-2.
The OT-2 was connected to the Pi through a TP-Link USB Ethernet adapter:

- USB device: `2357:0601 TP-Link UE300 10/100/1000 LAN`
- Pi interface: `eth1`
- interface state observed: link up, 100 Mbps
- OT-2 address reached from the Pi: `169.254.126.66`
- temporary Pi link-local address used: `169.254.200.1/16`

NetworkManager may keep trying DHCP on `eth1` and may remove the temporary
address. If robot requests time out, restore the temporary address first:

```sh
ssh yasha@raspi-codex 'sudo ip addr add 169.254.200.1/16 dev eth1 2>/dev/null || true'
ssh yasha@raspi-codex 'ping -c 1 -W 1 -I eth1 169.254.126.66'
```

To use this repo's local `opentrons_tools` through the Pi, open an SSH tunnel
from the Mac to the OT-2 HTTP API:

```sh
ssh -f -N -o BatchMode=yes -o StrictHostKeyChecking=accept-new \
  -o ExitOnForwardFailure=yes \
  -L 127.0.0.1:31951:169.254.126.66:31950 \
  yasha@raspi-codex
```

Then point the tools at the tunnel:

```sh
python3 -B -m opentrons_tools --host 127.0.0.1 --port 31951 health
python3 -B -m opentrons_tools --host 127.0.0.1 --port 31951 get /runs
python3 -B -m opentrons_tools --host 127.0.0.1 --port 31951 get /modules
python3 -B -m opentrons_tools --host 127.0.0.1 --port 31951 get /instruments
```

Local network access from Codex may require sandbox escalation even though the
target is `127.0.0.1`, because the port is an SSH tunnel to the robot.

Lights were tested with:

```sh
python3 -B -m opentrons_tools --host 127.0.0.1 --port 31951 get /robot/lights
python3 -B -m opentrons_tools --host 127.0.0.1 --port 31951 \
  request POST /robot/lights --body-json '{"on": true}' \
  --allow-action --confirm ACTIONS_CAN_MOVE_HARDWARE
```

For movement over this bridge, use a longer timeout. Homing took about 18-23
seconds in the 2026-06-12 test, so the default 10 second client timeout can
expire even when the robot command succeeds. Inspect run commands before sending
additional movement if a timeout happens.

The successful 2026-06-12 bridge movement sequence was:

```sh
python3 -B -m opentrons_tools --host 127.0.0.1 --port 31951 \
  create-run --allow-action --confirm ACTIONS_CAN_MOVE_HARDWARE

python3 -B -m opentrons_tools --host 127.0.0.1 --port 31951 --timeout 60 \
  home <run-id> --allow-action --confirm ACTIONS_CAN_MOVE_HARDWARE

python3 -B -m opentrons_tools --host 127.0.0.1 --port 31951 --timeout 60 \
  move-mount <run-id> left --x 200 --y 150 --z 150 --speed 20 \
  --allow-action --confirm ACTIONS_CAN_MOVE_HARDWARE

python3 -B -m opentrons_tools --host 127.0.0.1 --port 31951 --timeout 60 \
  move-mount <run-id> left --x 210 --y 150 --z 150 --speed 20 \
  --allow-action --confirm ACTIONS_CAN_MOVE_HARDWARE

python3 -B -m opentrons_tools --host 127.0.0.1 --port 31951 --timeout 60 \
  move-mount <run-id> left --x 210 --y 160 --z 150 --speed 20 \
  --allow-action --confirm ACTIONS_CAN_MOVE_HARDWARE

python3 -B -m opentrons_tools --host 127.0.0.1 --port 31951 --timeout 60 \
  move-mount <run-id> left --x 200 --y 160 --z 150 --speed 20 \
  --allow-action --confirm ACTIONS_CAN_MOVE_HARDWARE

python3 -B -m opentrons_tools --host 127.0.0.1 --port 31951 --timeout 60 \
  move-mount <run-id> left --x 200 --y 150 --z 150 --speed 20 \
  --allow-action --confirm ACTIONS_CAN_MOVE_HARDWARE

python3 -B -m opentrons_tools --host 127.0.0.1 --port 31951 --timeout 60 \
  home <run-id> --allow-action --confirm ACTIONS_CAN_MOVE_HARDWARE

python3 -B -m opentrons_tools --host 127.0.0.1 --port 31951 --timeout 60 \
  delete-run <run-id> --allow-action --confirm ACTIONS_CAN_MOVE_HARDWARE

python3 -B -m opentrons_tools --host 127.0.0.1 --port 31951 get /runs
```

In the verified run, the temporary run was deleted afterward and `/runs`
returned an empty list. Lights were left on at the user's request.

## Raspberry Pi 5 USB Bootstrap Notes

On 2026-06-11, a SanDisk Cruzer Blade USB stick was prepared as a Raspberry Pi 5
boot drive using Raspberry Pi OS Lite 64-bit:

- image: `2026-04-21-raspios-trixie-arm64-lite.img`
- source: Raspberry Pi official image index
- target observed on the Mac: `/dev/disk4`, external physical, 31.4 GB
- boot partition after flashing: `/Volumes/bootfs`
- hostname: `raspi-codex`
- local user: `yasha`
- temporary console password: `raspberry`
- SSH password auth: disabled
- SSH key: Mac `~/.ssh/id_ed25519.pub`
- Wi-Fi: open SSID `Broad Guest`
- remote access goal: Tailscale node `raspi-codex` in tailnet `Lab Internet`

As of 2026-06-12, the Pi successfully joined Tailscale:

- observed Tailscale IP: `100.96.152.25`
- tested SSH target from the Mac: `ssh yasha@raspi-codex`
- Tailscale SSH may require a browser approval link on first connection
- Codex CLI version observed on the Pi: `codex-cli 0.139.0`
- Codex user install path: `/home/yasha/.local/bin/codex`
- convenience symlink added: `/usr/local/bin/codex`

Do not assume the Tailscale IP is permanent; prefer `raspi-codex` or re-run
`tailscale status`.

Camera state checked on 2026-06-12:

- USB webcam detected: `Logitech Webcam C930e`
- device nodes: `/dev/video0`, `/dev/video1`, `/dev/media3`
- `rpicam-hello --list-cameras` reported `No cameras available!`, which means
  no Raspberry Pi CSI camera was detected by the `rpicam` stack
- use V4L2/USB camera tools for the Logitech webcam rather than assuming a CSI
  camera path

Useful read-only camera checks:

```sh
ssh yasha@raspi-codex 'lsusb'
ssh yasha@raspi-codex 'v4l2-ctl --list-devices'
ssh yasha@raspi-codex 'rpicam-hello --list-cameras'
```

Do not commit Tailscale auth keys or other bootstrap secrets. The one-off
Tailscale auth key was written only into `/Volumes/bootfs/user-data` on the USB
stick.

If the Pi boots but does not become reachable, plug the USB stick back into the
Mac and edit these Raspberry Pi `cloudinit-rpi` files on the FAT boot partition:

```sh
/Volumes/bootfs/user-data
/Volumes/bootfs/network-config
/Volumes/bootfs/meta-data
```

Important: bump `instance_id` in `meta-data` after changing cloud-init content;
Raspberry Pi OS caches prior cloud-init runs and uses `instance_id` to decide
whether first-boot setup should run again.

If local console login says the temporary password is incorrect, force the
password reset in `user-data` and bump `instance_id` again. The current recovery
pattern is:

```yaml
chpasswd:
  expire: false
  list: |
    yasha:raspberry

runcmd:
  - [ sh, -lc, "echo 'yasha:raspberry' | chpasswd && passwd -u yasha || true" ]
```

This handles the case where `yasha` already existed from an earlier first boot
with a locked password and cloud-init did not overwrite it from the `users:`
block alone.

If the password still does not change after bumping `instance_id`, assume the
root filesystem has stale cloud-init state and reimage from the original
verified `.img.xz` instead of continuing to patch only `bootfs`. In the 2026-06
debug session, the fresh image was rebuilt from:

```sh
/private/tmp/2026-04-21-raspios-trixie-arm64-lite.img.xz
```

Then the corrected `user-data`, `network-config`, and `meta-data` files were
copied into the fresh image's FAT boot partition before reflashing the SanDisk
USB. Mac raw-device writes from Codex were blocked by macOS, so the user ran a
guarded `sudo dd` script from Terminal.

The bootstrap service is `lab-pi-bootstrap.service`. It writes progress to:

```sh
/var/log/lab-pi-bootstrap.log
```

During debugging, a misspelled path `/var/log/lab-pi-boostrap.log` was also
seen. On the live Pi, that path is now a symlink to the real bootstrap log.

The debug version also mirrors progress to the display/console and no longer
uses a blocking `Type=oneshot` service. If a display and keyboard are attached,
log in locally as `yasha` with the temporary password and inspect:

```sh
sudo tail -f /var/log/lab-pi-bootstrap.log
ip addr
iw dev wlan0 link
journalctl -u cloud-init -u lab-pi-bootstrap --no-pager
```

Likely failure modes are guest Wi-Fi captive portal/client isolation, expired or
used one-off Tailscale auth key, or the Pi not booting from the USB stick. Use a
phone hotspot or normal WPA Wi-Fi if `Broad Guest` blocks headless internet.
