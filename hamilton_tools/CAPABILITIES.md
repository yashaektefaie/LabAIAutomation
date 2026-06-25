# Hamilton Microlab Prep — Machine Capabilities

> A reference journal of **everything the Microlab Prep can do** through its REST
> API (`ML Prep API`, OpenAPI v1, 279 paths / 318 operations / 42 tags), mapped to
> the `hamilton_tools` CLI. Read this first to know what is possible before
> writing a protocol or driving the instrument.
>
> Base URL: `http://<prep-ip>/api/v1/...` · Auth: JWT bearer (5-min expiry, renewable).
> Mutating operations in the CLI require `--allow-action --confirm ACTIONS_CAN_MOVE_HARDWARE`.
>
> ⚠️ **Source of truth:** everything below is derived from the **OpenAPI spec**, not
> yet from a live instrument. Endpoints and step types are real per the spec, but
> field-level details (exact required keys for a valid step body, runtime behavior)
> should be confirmed against hardware. See [§15 Verification log](#15-verification-log)
> for what has actually been exercised.

---

## 1. Hardware at a glance

The Microlab Prep is a compact, camera-guided benchtop liquid handler. The
pipetting head carries **two distinct tools that can both be used in one
protocol** (one tool per step):

| Tool | API name(s) | "Plain" name | Use |
|------|-------------|--------------|-----|
| Independent channels (×2) | `IndependentFrontChannel`, `IndependentRearChannel` | the **two roaming pipette tips** | Address arbitrary single wells anywhere on deck; cherry-pick, low-replicate transfers |
| Multi-Probe Head (8) | `MphChannels`, `MphChannel1`…`MphChannel8` | the **8-channel head** | Whole-column / 96-well stamping, parallel transfers |

At the **step** level you choose the tool with `channelSelection`:

| `channelSelection` | Physical tool engaged |
|--------------------|-----------------------|
| `OneChannel` | one independent CO-RE channel |
| `TwoChannel` | both independent (roaming) channels |
| `EightChannel` | the 8-channel MPH |

> **Both tools in one protocol:** normal and supported. e.g. a `TwoChannel`
> Add-Reagent step to dose specific wells, then an `EightChannel` Transfer step to
> stamp a full column. It is *one tool per step*, never both within a single step.

Camera-based **vision system** (deck scanning, labware detection, tip detection),
a **transport/gripper** motion for moving plates and lids on-deck, and optional
integrated devices: **Heater-Shaker / Heater-Cooler (HHC)**, **HEPA/UV** hood,
and **enclosure lighting**.

---

## 2. How work is expressed

The Prep does **not** expose ad-hoc "move/aspirate" calls. All liquid handling is
authored as a **Protocol** = ordered list of **Steps**, then executed as a **Run**:

```
Protocol (create/import) ──> add Steps ──> validate/verify ──> create Run
   ──> load instructions ──> load-complete ──> [runs] ──> pause/resume/abort
   ──> cleanup-unloading ──> Run Data (PDF / pipetting CSV)
```

- Create protocol: `POST /api/v1/protocols`
- Add a step: `POST /api/v1/protocols/{protocolId}/step` (body's `stepType` selects the kind)
- Validate / verify / preview: `GET /api/v1/protocols/validate|verify|preview/{id}`
- Run lifecycle: see §10.

---

## 3. Step types — the core capabilities

Every entry below is a `stepType` you can put in a protocol (`…StepGetDto` schemas).

### Liquid-handling steps (use `channelSelection`)

| Step type | What it does | Key fields |
|-----------|--------------|------------|
| **TransferSamples** | Source→destination transfers | `sources`, `destinations`, `aspirateSettings`, `dispenseSettings`, `channelSelection`, `tipReuseOption`, `mixBeforeAspirate`, `mixAfterDispense`, `dispenseToWaste` |
| **AddReagent** | Add a reagent (single source liquid) to many destinations, with multi-dispense | `destinations`, `multiDispense`, `multiDispenseSettings`, `liquidLabwareGroupId` |
| **ReplicateSamples** | Replicate samples across wells | `wellAssignments`, `multiDispense` |
| **SerialDilution** | Full serial-dilution series (diluent + samples + dilution stages) | `dilutions`, `diluent`, `dilutionTargets`, `calculateWithFactors`, per-stage aspirate/dispense/mix/tip settings |
| **Normalization** | Normalize samples to a target concentration/volume from a worklist | `finalConcentration`, `finalVolume`, `minimumSampleVolume`, `diluent`, input/output worklist files |
| **HitPicking** | Cherry-pick from a worklist file (sources/targets/volumes from file) | `fileContents`, `fileSpecifiesSources/Targets/Volumes`, `followWorklistOrder` |
| **ReagentFromFile** | Drive reagent additions from an external worklist file | worklist file submission |

### Plate-handling / motion steps

| Step type | What it does | Key fields |
|-----------|--------------|------------|
| **Transport** | Move a plate/labware with the gripper between deck positions | `startPosition`, `endPosition` |
| **Lid** | Move a lid on/off (de-lid / re-lid) | `startPosition`, `endPosition` |

### Device / control steps

| Step type | What it does | Key fields |
|-----------|--------------|------------|
| **HeatShake** | Heat and/or shake a plate (Heater-Shaker) | `platePosition`, `heat`, `shake`, `rpm`, `temperature`, `duration`, `heatStartOptions` |
| **HeatCool** | Hold a plate at a temperature (Heater-Cooler) | `platePosition`, `temperature`, `temperatureSet`, `heatCoolStartOptions` |
| **Hepa** | Run the HEPA fan around the protocol | `hepaStartOptions` (`StartBeforeProtocol`/`StartBeforeLoading`), `waitTime` |
| **Lighting** | Set enclosure lighting as a protocol step | lighting params |
| **Barcode** | Read barcodes at targets | `targets` |
| **Rtsa** | Run-Time Sample Assignment prompt (assign samples at runtime) | `message`, `targets` |
| **Pause** | Pause for a duration or for the operator | `duration`, `message`, `pauseForSetDuration` |

`heatStartOptions` / `heatCoolStartOptions` enum: `PauseProtocolUntilTemp`,
`PauseStepUntilTemp`, `PauseLoadingUntilTemp`.

---

## 4. Pipetting settings detail

`AspirateSettingsDto` / `DispenseSettingsDto` (per transfer):

- `transferVolume` (µL)
- `pipettingHeight` + `pipettingHeightStartPoint` — height in the well to pipette at
- `followLiquid` — track the liquid surface as it rises/falls
- `retractToWellTop` / `retractDistance` — exit behavior
- `enableMad` — Monitored Air Displacement
- Integrated mixing: `mixVolume`, `mixCycles`, `mixSpeed`, `mixHeight`, `mixHeightStartPoint`
- `offset` / `useOffset` — XYZ fine offset

Tip management on liquid steps:

- `tipReuseOption`: `PerSample`, `PerReplica`, `PerPool`, `PerTransfer`
- `tipDiscardLocation`: `DiscardToWaste`, `ReturnToRack`, `ReuseForSamplesAndDilution`
- `newTipsEachTransfer` (bool), `dispenseToWaste` (bool, ignores destinations → waste)
- `MultiDispenseSettingsDto`: `usePreAliquot`/`usePostAliquot` + their settings

---

## 5. Integrated devices

| Device | Capability | Endpoints / step |
|--------|-----------|------------------|
| **Heater-Cooler (HHC)** | Set/hold temperature; query current vs target; configure adapter | `…/thermal-device/hhc/start-temperature-control`, `…/stop-temperature-control`, `…/temperature-status`, `…/configuration`; **HeatCool** step |
| **Heater-Shaker** | Heat + shake at RPM for a duration | **HeatShake** step |
| **HEPA/UV hood** | Start/stop HEPA fan, read filter pressure & pre-filter usage; UV decontamination routine scheduling | `…/hepa-uv/*`, `…/maintenance/uv-routine-settings`; **Hepa** step |
| **Enclosure lighting** | Automatic or custom RGB lighting; fan-state monitoring | `…/enclosure/*`, `…/lighting/*`; **Lighting** step |
| **Gripper / transport** | Move plates and lids between deck positions | **Transport** / **Lid** steps |

---

## 6. Vision / camera

- Capture frames (raw, rectified, weighted, calibration-overlay): `…/camera/get-frame`, `…/camera/{rectify}`, `…/camera/calibration-pattern`
- Per-deck-position crops, tip-rack overlay: `…/camera/position/...`
- Live feed control, crop adjust, multi-camera select: `…/camera/start|stop-camera-feed`, `…/camera/active/{id}`
- Vision system status: `…/camera/vision-system-status`
- **Deck scanning** (auto-discover labware on deck via camera): `GET /api/v1/deck/scan/{numMatches}`
- **Tip detection** at a position: `GET /api/v1/protocol-verification/detect-tips/{protocolId}/{positionId}`

---

## 7. Deck & labware

- Deck layout get/update: `GET /api/v1/deck/{deckLayoutId}`, `PUT /api/v1/deck/{protocolId}`
- Deck has up to **8 positions** (`PipetteTargetDto.position` = 1–8).
- Deck calibration relative to camera: `PUT /api/v1/deck/calibrate`
- Labware catalog: list / by-name / by-id / import / export / delete / favorite / restore-default — `…/labware/*`
- Labware categories & classifications: `…/labware-categories/*`, `…/labware/properties/classifications`
- Labware signatures (camera recognition templates): `…/labware-signature/*`
- Container properties: `…/labware/properties-container/{name}`

---

## 8. Liquid classes

- List / create / update / batch-delete / import / export: `…/liquid-classes`
- Find usage across protocols, find existing imports: `…/liquid-classes/find-usage`, `…/find-existing-imports`
- Resolve settings for a query: `GET /api/v1/liquid-classes/settings`

---

## 9. Calibration, diagnostics, maintenance, verification

**Calibration** (`…/calibration/*`): self-calibration, channel height-squeeze,
HEPA-filter calibration, deck load/cleanup workflow, channel results get/submit,
images, export, abort.

**Diagnostics** (`…/diagnostics/*`): instrument tests — `transport`, `tip-pickup`,
`pressure`, `drip`, `hhs`, `motor-diagnostics` (+cancel); demo protocol; camera
snapshot; network diagnostics; downloadable diagnostic zip.

**Maintenance** (`…/maintenance/*`): list/get/start procedures, abort, per-channel
counters + reset (`reset-channel-counters/{channel}`), UV-decontamination routine
settings, error list, initialize values.

**Verification** (`…/verification/*`, `…/verification-result/*`, `…/report/pvk/*`):
PVK service/verification routines & workflows, signatures, run reports — IQ/OQ-style
qualification. Service-password gated.

**Service / sensors** (`…/service-software-api/*`): door state, fan state,
**has-tips** (per-channel tip presence), parked state, sensor status, powerdown.

---

## 10. Run lifecycle & data

| Phase | Endpoint | CLI |
|-------|----------|-----|
| Create run from protocol | `POST …/protocol-run/create` | `create-run <protocol_id>` |
| Get load instructions | `GET …/protocol-run/load-instructions` | `load-instructions` |
| Signal loading done | `PUT …/protocol-run/load-complete` | `load-complete` |
| Pause / Resume / Abort | `PUT …/protocol-run/{pause,resume,abort}` | `pause` / `resume` / `abort` |
| Submit barcodes / RTSA / worklist files | `…/protocol-run/submit-*`, `…/rtsa` | `rtsa` |
| Simulation speed (dry runs) | `GET/PUT …/protocol-run/simulation-speed` | — |
| Post-run cleanup/unloading | `PUT …/protocol-run/cleanup-unloading` | `cleanup` |
| Results | `GET …/run-data`, `…/{id}`, `…/{id}/pdf`, `…/{id}/pipetting-csv` | `list-run-data`, `get-run-data` |

Global run state (`PrepChannel`/run enum, see client `RUN_STATES`): 0 NotInitialized
→ 1 Initialized → 2 Running → 6/7 Pausing/Paused → 3/4 Aborting/Aborted → 5 Processed …

---

## 11. Power & instrument control

- Initialize instrument (**the safe "home" move** — homes all axes): `POST …/instruments/initialize` → CLI `initialize`
- Connect / list / serial number / active system / connection status: `…/instruments/*`
- Mock instrument (no hardware): `PUT …/instruments/mock` → CLI `use-mock`
- Power: `is-initialized`, request/confirm/cancel powerdown, channel-power on/off, servo-power on/off, monitor powerdown — `…/power/*`

---

## 12. System & administration

- **Auth**: login, logout, renew-token, check-authentication, password reset / KBA, setup wizard — `…/authenticate/*`, `…/user-kba/*`
- **Users & roles**: CRUD users, roles & permissions, user-management enable/disable, password policy — `…/users/*`, `…/roles/*`
- **Settings**: instrument / software / policy settings, verification importance, service contract — `…/settings/*`
- **Network**: network config, remote-desktop enable/disable — `…/network-configuration/*`
- **System**: ready check, software versions (incl. instrument & service-software), system time & time zones, environment (temp/humidity) — `…/system-ready`, `…/software-versions/*`, `…/system-time/*`, `…/environment`
- **Ops/data**: backups (db), screenshots, traces/logs, repair, configuration (CORS), credentials — `…/backups/*`, `…/screenshots/*`, `…/traces/*`, `…/repair`, `…/configuration/cors`, `…/credentials/*`
- **Errors**: list, get by id, check pending, clear, handle runtime error (with chosen response) — `…/errors/*`

---

## 13. Capability → CLI quick map

Read-only (no confirmation):
`login` · `check-auth` · `system-ready` · `software-versions` · `environment` ·
`snapshot` · `errors` · `runtime-errors` · `instruments` · `connection-status` ·
`run-state` · `serial-number` · `is-initialized` · `list-protocols` ·
`get-protocol` · `protocol-names` · `verify-protocol` · `validate-protocol` ·
`preview-protocol` · `list-steps` · `get-step` · `load-instructions` · `rtsa` ·
`list-run-data` · `get-run-data` · `list-labware` · `get-labware` ·
`get-labware-by-name` · `labware-classifications` · `list-liquid-classes` ·
`get-deck` · `scan-deck` · `diagnostics` · `calibration-results` · `maintenance` ·
`channel-counters` · `sensor-status` · `door-state` · `is-parked` · `cameras` ·
`vision-status` · `hepa-status` · `get` · generic `request GET`

Mutating (need `--allow-action --confirm ACTIONS_CAN_MOVE_HARDWARE`):
`initialize` (safe home) · `use-mock` · `clear-errors` · `import-protocols` ·
`create-run` · `load-complete` · `pause` · `resume` · `abort` · `cleanup` ·
`diag-transport` · `diag-tip-pickup` · `diag-pressure` · `diag-drip` ·
`self-calibration` · `abort-calibration` · `request-powerdown` ·
`confirm-powerdown` · `start-hepa` · `stop-hepa` · generic `request POST|PUT|DELETE`

> Anything in §1–§12 without a dedicated CLI subcommand is reachable through the
> generic `get` / `request` commands, e.g.:
> `hamilton-tools request POST /api/v1/protocols/1/step --body-json '{"stepType":"TransferSamples", ...}' --allow-action --confirm ACTIONS_CAN_MOVE_HARDWARE`

---

## 14. Related: VENUS WebAPI (different machines)

The repo also includes `venus api.json` — the **VENUS WebAPI Host v3** REST API
(`http://localhost:51745` style), which drives **STAR / STARlet / Vantage**
instruments (not the Prep). Scope: `RunExecutor` (load/start/pause/resume/abort
VENUS methods, 13 ops), `Files`, `Devices`, `Cameras`, `InstrumentData`,
`ErrorHandler`, `System`, `Users`. If a future task targets a STAR-class robot
rather than the Prep, build a sibling client against that spec — the Prep API
described here does **not** apply to those machines.

---

## 15. Verification log

Track what has been exercised against a real (or mock) instrument here, so future
iterations know which capabilities are **spec-only** vs. **confirmed**. Append a
dated row when you test something; keep `Source` honest (`spec`, `mock`, `live`).

Status legend: ✅ confirmed · ⚠️ partial / caveats · ❌ failed · ⬜ untested (spec only)

| Date | Capability / endpoint | Source | Status | Notes |
|------|-----------------------|--------|--------|-------|
| 2026-06-25 | Entire catalog (§1–§14) | spec | ⬜ | Derived from `ML Prep API` OpenAPI v1; no hardware contacted. |
| 2026-06-25 | CLI ↔ API plumbing: `login`, `system-ready`, `run-state`, `is-initialized`, `snapshot`, `initialize` | mock | ✅ | Exercised end-to-end against a local mock server (JWT round-trip, safety gate, state change `NotInitialized`→`Initialized`). Mock has since been removed. |

Not yet verified against live hardware: **all** of it — authentication against a
real Prep, protocol create/import, step bodies (TransferSamples/AddReagent/
SerialDilution/etc.), run lifecycle, gripper Transport/Lid, HHC thermal, HEPA/UV,
camera/vision, calibration, diagnostics, run-data export.

When testing on a live machine, record: instrument serial/`get-active-system`,
software versions, and which exact step JSON bodies validated — those field-level
shapes are the highest-risk gap between this spec-derived doc and reality.
