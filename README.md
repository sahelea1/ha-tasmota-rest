# Tasmota REST for Home Assistant

A fully-featured Home Assistant **custom integration** that controls
[Tasmota](https://tasmota.github.io/) devices over plain HTTP — no MQTT
broker required. Designed as a drop-in replacement for hand-rolled
`rest_command:` / `rest:` / `template:` blocks in `configuration.yaml`.

* Local polling (default 5 s, configurable per device)
* Add devices through the UI (`Settings → Devices & Services → Add Integration`)
  **or** via YAML, with automatic import to a config entry
* Each device produces:
  * a primary power **switch** (`switch.tasmota_<name>`)
  * sensors for **state, power, current, voltage** plus apparent / reactive
    power, power factor, energy today / yesterday / total
  * an optional **virtual switch** driven by a power-draw threshold
    (mirrors the manual *Dehumidifier Virtual* pattern)
* Services for **timers**, **timezone setup**, **restart**, **backlog**,
  raw **send_command**, **normalize_time**, and explicit **power_on / power_off**
* HACS-compatible (`custom` repository)
* Devices appear in the device registry → use them as targets in
  scripts/automations/services

---

## Installation

### HACS (recommended)

1. HACS → *Integrations* → ⋮ → *Custom repositories*.
2. Add `https://github.com/sahelea1/ha-tasmota-rest` as type **Integration**.
3. Install **Tasmota REST**, restart Home Assistant.

### Manual

Copy `custom_components/tasmota_rest/` into `<config>/custom_components/`
and restart Home Assistant.

---

## Adding devices

### Via UI

`Settings → Devices & Services → Add Integration → Tasmota REST` and enter:

| Field                       | Required | Description                                        |
|----------------------------|----------|----------------------------------------------------|
| Host                        | yes      | IP address or hostname                             |
| Friendly name               | no       | Defaults to the Tasmota FriendlyName               |
| Username / Password         | no       | If web admin auth is enabled                       |
| Scan interval               | no       | Seconds between polls (default 5)                  |
| Use HTTPS / Verify SSL      | no       | Off by default                                     |
| Virtual switch enabled      | no       | Toggles the power-threshold helper                 |
| Power threshold (W)         | no       | State is *on* when device draws more than this     |
| Button entity to press      | no       | A `button.*` entity used to toggle the load        |

Re-open the device → ⋮ → **Configure** to change scan interval / virtual
switch settings without removing the device.

### Via YAML

```yaml
tasmota_rest:
  devices:
    - host: 192.168.1.104
      name: Tasmota 104
    - host: 192.168.1.244
      name: Tasmota 244
    - host: 192.168.1.234
      name: Tasmota 234
    - host: 192.168.1.190
      name: Tasmota 190
      virtual_switch_enabled: true
      virtual_switch_threshold: 30
      virtual_switch_press_entity: button.bf1d60e4rwx4sc5u_push
    - host: 192.168.1.162
      name: Tasmota 162
```

Each entry is imported as a config entry on startup. After import the
block can be removed; settings are managed through the UI.

---

## Entities created per device

For a device named *Tasmota 104* you will get:

```
switch.tasmota_104                 # primary relay
sensor.tasmota_104_state           # ON / OFF (raw)
sensor.tasmota_104_power           # W
sensor.tasmota_104_current         # A
sensor.tasmota_104_voltage         # V
sensor.tasmota_104_power_factor    # disabled by default
sensor.tasmota_104_apparent_power  # disabled by default
sensor.tasmota_104_reactive_power  # disabled by default
sensor.tasmota_104_energy_today    # kWh, total_increasing
sensor.tasmota_104_energy_yesterday
sensor.tasmota_104_energy_total
```

If `virtual_switch_enabled: true`:

```
switch.tasmota_104_virtual         # ON when sensor.tasmota_104_power > threshold
```

---

## Services

All services accept a `device:` target. Multiple devices may be selected
and are dispatched in parallel.

| Service                            | Purpose                                                                 |
|------------------------------------|-------------------------------------------------------------------------|
| `tasmota_rest.set_timer`           | Configure a single Tasmota timer slot (1-16)                            |
| `tasmota_rest.disable_all_timers`  | Disable timers 1..N in a single Backlog                                 |
| `tasmota_rest.get_timers`          | Returns the `Timers` JSON (response variable)                           |
| `tasmota_rest.set_timezone`        | Apply timezone (defaults to Europe DST settings)                        |
| `tasmota_rest.send_command`        | Send a raw `cmnd=…` and return the parsed JSON                          |
| `tasmota_rest.backlog`             | Wrap a `;`-separated payload in `Backlog0`                              |
| `tasmota_rest.restart`             | `Restart 1` (default — does not change relay state)                     |
| `tasmota_rest.normalize_time`      | Push HA's current local time to the device via `Time …`                 |
| `tasmota_rest.power_on/off`        | Explicit relay control                                                  |

### Example: set timer 1

```yaml
service: tasmota_rest.set_timer
target:
  device_id: 8a3f1c4e0b...
data:
  timer_number: 1
  enable: true
  time: "06:30"
  window: 0
  days: "1111111"
  repeat: true
  output: 1
  action: 1     # 0=Off, 1=On, 2=Toggle, 3=Rule
```

### Example: disable all 6 timers

```yaml
service: tasmota_rest.disable_all_timers
target:
  device_id: 8a3f1c4e0b...
data:
  count: 6
```

### Example: read timers into a variable

```yaml
- service: tasmota_rest.get_timers
  target:
    device_id: 8a3f1c4e0b...
  response_variable: timers
- service: system_log.write
  data:
    message: "Timers => {{ timers }}"
```

### Example: send arbitrary command

```yaml
service: tasmota_rest.send_command
target:
  device_id: 8a3f1c4e0b...
data:
  command: "Status 11"
response_variable: status
```

### Example: backlog

```yaml
service: tasmota_rest.backlog
target:
  device_id: 8a3f1c4e0b...
data:
  command: "Power On; Delay 10; Power Off"
```

---

## Migrating from the old YAML setup

The integration is designed to replace the manual `rest_command:` / `rest:` /
`template:` / `sensor:` blocks. The mapping is:

| Old YAML                                                                    | Replacement                                                                    |
|-----------------------------------------------------------------------------|--------------------------------------------------------------------------------|
| `rest:` block per device polling `Status 10`                                | Coordinator inside this integration                                            |
| `sensor.tasmota_<n>_power / current / voltage`                              | `sensor.tasmota_<n>_power` / `…_current` / `…_voltage`                          |
| `sensor.tasmota_<n>_state` (`platform: rest`, polling `Power`)              | `sensor.tasmota_<n>_state` *(this integration)*                                |
| `template:` switch wrapping the REST command                                | `switch.tasmota_<n>` *(this integration)*                                      |
| `rest_command.tasmota_power_on / off`                                       | `switch.turn_on/off` on the `switch.tasmota_<n>` entity, **or** the explicit `tasmota_rest.power_on/off` services |
| `rest_command.tasmota_set_timer`                                            | `tasmota_rest.set_timer`                                                       |
| `rest_command.tasmota_disable_all_timers`                                   | `tasmota_rest.disable_all_timers`                                              |
| `rest_command.tasmota_get_timers`                                           | `tasmota_rest.get_timers` (with `response_variable`)                           |
| `rest_command.tasmota_backlog`                                              | `tasmota_rest.backlog` *(or `tasmota_rest.send_command`)*                      |
| `rest_command.tasmota_set_timezone`                                         | `tasmota_rest.set_timezone`                                                    |
| `Restart 1` via `tasmota_backlog`                                           | `tasmota_rest.restart`                                                         |
| The `Dehumidifier Virtual` template switch                                  | Built-in virtual switch (enable in device options + supply button entity)      |

Once each device is added to the integration you can delete the
corresponding `rest_command:`, `rest:`, the per-device `sensor:` REST
entries and the `template:` switches. The unique IDs and entity IDs are
preserved by name so existing automations referencing
`switch.tasmota_104` etc. keep working *as long as you remove the legacy
template before adding the device*, or rename one of them.

### Trimmed `configuration.yaml`

```yaml
default_config:

frontend:
  themes: !include_dir_merge_named themes

automation: !include automations.yaml
script: !include scripts.yaml
scene: !include scenes.yaml

# VPD helpers (unchanged)
input_number: !include input_numbers.yaml   # or keep inline
input_boolean: !include input_booleans.yaml

# Tasmotas (one block instead of ~250 lines)
tasmota_rest:
  devices:
    - host: 192.168.1.104
      name: Tasmota 104
    - host: 192.168.1.244
      name: Tasmota 244
    - host: 192.168.1.234
      name: Tasmota 234
    - host: 192.168.1.190
      name: Tasmota 190
      virtual_switch_enabled: true
      virtual_switch_threshold: 30
      virtual_switch_press_entity: button.bf1d60e4rwx4sc5u_push
    - host: 192.168.1.162
      name: Tasmota 162

# Healthchecks.io stays generic
rest_command:
  hc_ping:
    url: "https://hc-ping.com/0a166f8e-33ae-48ee-ab83-4ec1f7d172ba"
    method: GET
    timeout: 10
```

### Updating existing automations

Where you previously had:

```yaml
action: rest_command.tasmota_set_timer
data:
  ip: "192.168.1.244"
  timer_number: 1
  timer_payload: '{"Enable":1,"Time":"06:30","Window":0,"Days":"1111111","Repeat":1,"Output":1,"Action":1}'
```

Use:

```yaml
action: tasmota_rest.set_timer
target:
  device_id: <device id of Tasmota 244>
data:
  timer_number: 1
  enable: true
  time: "06:30"
  window: 0
  days: "1111111"
  repeat: true
  output: 1
  action: 1
```

The reboot-after-off automation becomes:

```yaml
action: tasmota_rest.restart
target:
  device_id: <Tasmota 244>
data:
  type: 1
```

The healthchecks ping is unchanged (still uses `rest_command.hc_ping`).

---

## Notes

* The integration uses `Status 0` to fetch all data in one HTTP call.
  Devices without energy monitoring simply don't get the energy sensors
  (they self-report as unavailable on first refresh).
* On Power on/off, the result returned by Tasmota is applied
  optimistically to the coordinator state so the UI updates instantly,
  then a poll confirms.
* Authentication uses Tasmota's `?user=&password=` query parameters —
  set `Web Admin Password` in Tasmota and supply the same credentials
  in the config flow.
* If you change `scan_interval` in options, the integration reloads
  automatically.

## License

MIT
