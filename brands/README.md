# Brand assets

Master files:

* `icon.svg` — 256×256 square icon (master)
* `logo.svg` — 720×256 banner (icon + wordmark)
* `_render_logo.py` — renders all four PNGs from primitive shapes (no SVG
  rasterizer required); run with `python brands/_render_logo.py`

Generated PNGs (committed for immediate use):

| File              | Dimensions  | Use                                      |
|-------------------|-------------|------------------------------------------|
| `icon.png`        | 256×256     | Default integration icon                 |
| `icon@2x.png`     | 512×512     | Hi-DPI integration icon                  |
| `logo.png`        | 720×256     | Wordmark for documentation / HACS card   |
| `logo@2x.png`     | 1440×512    | Hi-DPI wordmark                          |

## Submitting to the official Home Assistant brands repository

To make the icon appear inside Home Assistant (Settings → Devices & Services
card art), open a PR against [home-assistant/brands](https://github.com/home-assistant/brands)
adding:

```
custom_integrations/tasmota_rest/icon.png         (copy of brands/icon.png)
custom_integrations/tasmota_rest/icon@2x.png      (copy of brands/icon@2x.png)
custom_integrations/tasmota_rest/logo.png         (copy of brands/logo.png)
custom_integrations/tasmota_rest/logo@2x.png      (copy of brands/logo@2x.png)
```

Until that PR merges, the icons in this directory are still served by
HACS as part of the repository and shown on the integration's HACS card.
