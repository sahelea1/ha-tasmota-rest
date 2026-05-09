# Tasmota REST

Local-polling Home Assistant integration for Tasmota devices controlled
over plain HTTP (no MQTT). Drop-in replacement for hand-written
`rest_command:` / `rest:` / `template:` blocks.

* UI or YAML configuration (YAML auto-imports to a config entry)
* Per-device: power switch, state / power / current / voltage sensors,
  energy counters, optional power-threshold virtual switch
* Services: timer set / disable_all / get, set_timezone, restart,
  backlog, send_command, normalize_time, power_on/off
