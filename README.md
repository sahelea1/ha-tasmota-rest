<p align="center">
  <img src="brands/logo.png" alt="Tasmota REST" width="520">
</p>

# Tasmota REST for Home Assistant

A fully-featured Home Assistant **custom integration** that controls
[Tasmota](https://tasmota.github.io/) devices over plain HTTP — no MQTT
broker required. Designed as a drop-in replacement for hand-rolled
`rest_command:` / `rest:` / `template:` blocks in `configuration.yaml`,
**plus** an auto-discovery & WiFi-provisioning hub so newly-plugged
Tasmotas appear in Home Assistant by themselves.

* Local polling, default 5 s, configurable per device.
* Add devices through the **UI**, via **YAML**, or have them found
  automatically by **DHCP / mDNS / LAN scanner**.
* Each device produces:
  * a primary power **switch** (`switch.tasmota_<name>`)
  * sensors for **state, power, current, voltage** + apparent / reactive
    power, power factor, energy today / yesterday / total
  * an optional **virtual switch** driven by a power-draw threshold
    (mirrors the manual *Dehumidifier Virtual* pattern)
* Global **Auto-discovery & provisioning hub** that:
  * remembers your WiFi credentials and Tasmota-admin defaults
  * periodically sweeps the LAN for Tasmota devices
  * pushes WiFi creds to any Tasmota currently broadcasting an AP
    (auto-provisioning)
  * surfaces nearby Tasmota AP SSIDs in a notification (best-effort,
    requires `nmcli` / `iw` on the host)
  * listens for Home Assistant's built-in DHCP and Zeroconf discovery
    hooks
* Services for **timers** (set / disable / get), **timezone**,
  **restart**, **backlog**, raw **send_command**, **normalize_time**,
  **provision_ap**, **provision_device**, **scan_now**, plus explicit
  **power_on / power_off**.
* HACS-compatible.
* Brand assets included (`brands/`) + script to regenerate them.

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

## Quick start

`Settings → Devices & Services → Add Integration → Tasmota REST` →
choose one of:

* **Add a device** — point at a single Tasmota (works exactly like the
  legacy YAML did).
* **Configure auto-discovery & provisioning** — enter your home WiFi
  credentials and let the integration find devices by itself.

Both can coexist.

### Hub fields

| Field                                 | Purpose                                                                 |
|---------------------------------------|-------------------------------------------------------------------------|
| WiFi SSID / password                  | Pushed to any Tasmota in AP mode the integration can reach              |
| Backup SSID / password                | Optional secondary network (`SSID2` / `Password2`)                      |
| Default Tasmota web username/password | Used both for the LAN scanner and as defaults for new device entries    |
| Subnets to scan                       | Comma-separated CIDRs (`192.168.1.0/24`); blank = auto-detect adapter   |
| Scan interval                         | Minutes between full sweeps (default 10)                                |
| Auto-add discovered devices           | If on, found Tasmotas are added without prompting                       |
| Auto-provision when AP is reachable   | If on, hitting `192.168.4.1` (configurable) and finding a Tasmota in setup mode pushes the stored creds + reboots |
| Tasmota AP gateway IP                 | Default `192.168.4.1`                                                   |
| AP SSID match pattern                 | Used by the WiFi sniffer (`tasmota` matches `tasmota_XXXX-NNNN`)        |
| Scan nearby WiFi for Tasmota APs      | Best-effort; uses `nmcli` or `iwlist` on the host                       |
| Hostname template                     | E.g. `cabinet-{mac}` → `cabinet-a1b2c3` for the last 6 MAC nibbles      |

### Per-device fields (UI add)

| Field                            | Description                                  |
|----------------------------------|----------------------------------------------|
| Host                             | IP / hostname                                |
| Friendly name                    | Defaults to Tasmota's FriendlyName           |
| Username / Password              | If web admin auth is enabled                 |
| Scan interval                    | Seconds between polls (default 5)            |
| Use HTTPS / Verify SSL           | Off by default                               |
| Virtual switch enabled/threshold | Power-threshold helper                       |
| Button entity to press           | A `button.*` entity used by the helper       |

### YAML (devices only)

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

YAML entries are imported into config entries on startup. The hub is
UI-only because it stores WiFi credentials.

---

## Auto-discovery & provisioning paths

A freshly-bought Tasmota is found and added through one of these paths
(in order of preference):

1. **DHCP discovery** — declared in `manifest.json` for common Espressif
   OUIs and the `tasmota*` hostname pattern. As soon as the device
   joins your LAN and asks for DHCP, Home Assistant fires a discovery
   flow.
2. **Zeroconf / mDNS** — `_tasmota._tcp.local.` and any `_http._tcp.local.`
   record whose name starts with `tasmota` triggers discovery.
3. **LAN HTTP scanner** — every N minutes the hub probes the configured
   subnets for `Status 0` responses with a Tasmota signature, dedupes
   by MAC, and creates discovery flows for new devices.
4. **AP auto-provisioning** — every cycle the hub also probes the
   configured AP IP (`192.168.4.1` by default). If a Tasmota in setup
   mode answers, it gets `Backlog0 SSID1 …; Password1 …; Restart 1`
   and joins your network — where path 1/2/3 immediately picks it up.
5. **WiFi environment scan** — a best-effort `nmcli`/`iwlist` sweep
   surfaces nearby `tasmota_*` AP SSIDs as a persistent notification so
   you know provisioning is pending. Silently no-ops on installs where
   neither tool is reachable (most Docker / Container HA installs).

### Manual provisioning

If your HA host can't reach `192.168.4.1` directly (typical), connect
any device (your phone) to the Tasmota AP, browse to its admin page
once and feed it the right WiFi creds — or use this service from a
browser already on the AP:

```yaml
service: tasmota_rest.provision_ap
data:
  host: 192.168.4.1   # default; override if needed
  # ssid / password / ssid2 / password2 / hostname all optional —
  # the hub's stored values are used when omitted
```

`tasmota_rest.provision_device` does the same against an
already-configured device (e.g. to roll over to a new SSID).

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

All per-device services accept a `device:` target. Multiple devices may
be selected and are dispatched in parallel.

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
| `tasmota_rest.provision_ap`        | Hub-level: push WiFi creds to a reachable AP                            |
| `tasmota_rest.provision_device`    | Hub-level: push WiFi creds to existing device(s) and reboot             |
| `tasmota_rest.scan_now`            | Trigger an immediate LAN + AP + WiFi scan                               |

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

---

## Migrating from the old YAML setup

| Old YAML                                                                    | Replacement                                                                    |
|-----------------------------------------------------------------------------|--------------------------------------------------------------------------------|
| `rest:` block per device polling `Status 10`                                | Coordinator inside this integration                                            |
| `sensor.tasmota_<n>_power / current / voltage`                              | `sensor.tasmota_<n>_power` / `…_current` / `…_voltage`                          |
| `sensor.tasmota_<n>_state` (`platform: rest`, polling `Power`)              | `sensor.tasmota_<n>_state` *(this integration)*                                |
| `template:` switch wrapping the REST command                                | `switch.tasmota_<n>` *(this integration)*                                      |
| `rest_command.tasmota_power_on / off`                                       | `switch.turn_on/off` on `switch.tasmota_<n>` **or** `tasmota_rest.power_on/off`|
| `rest_command.tasmota_set_timer`                                            | `tasmota_rest.set_timer`                                                       |
| `rest_command.tasmota_disable_all_timers`                                   | `tasmota_rest.disable_all_timers`                                              |
| `rest_command.tasmota_get_timers`                                           | `tasmota_rest.get_timers` (with `response_variable`)                           |
| `rest_command.tasmota_backlog`                                              | `tasmota_rest.backlog` *(or `tasmota_rest.send_command`)*                      |
| `rest_command.tasmota_set_timezone`                                         | `tasmota_rest.set_timezone`                                                    |
| `Restart 1` via `tasmota_backlog`                                           | `tasmota_rest.restart`                                                         |
| The `Dehumidifier Virtual` template switch                                  | Built-in virtual switch (enable in device options + supply button entity)      |

---

## Notes & limitations

* The integration uses `Status 0` to fetch all data in one HTTP call.
  Devices without energy monitoring simply don't get the energy sensors.
* On Power on/off, the response is applied optimistically to the
  coordinator state so the UI updates instantly, then a poll confirms.
* Authentication uses Tasmota's `?user=&password=` query parameters.
* WiFi-environment scanning depends on `nmcli` or `iwlist` being
  reachable from the Home Assistant runtime. On HAOS-supervisor and
  Docker installations these are usually unavailable; the feature
  no-ops cleanly in that case. The DHCP/Zeroconf/LAN scanner paths
  remain fully functional.
* The integration **never** changes the Home Assistant host's WiFi
  network. AP provisioning only works against APs the HA host can
  already route to (e.g. dual-network HA host, secondary adapter on
  the AP, or a manual bridge). When that's not possible, use the
  `provision_ap` service from any browser/phone on the AP.
* Only one auto-discovery hub per HA instance is allowed; per-device
  entries are unlimited.

## License

MIT
