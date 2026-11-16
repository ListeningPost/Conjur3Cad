# Third-party notices

Conjur3 is MIT-licensed (see [LICENSE](./LICENSE)). It includes, adapts, or
depends at runtime on the third-party work below. npm and PyPI dependencies are
not vendored; their licenses are recorded in each `package-lock.json` and in
the installed packages.

## Code included in this repository

| Component | Where | Copyright | License |
| --- | --- | --- | --- |
| nextjs-firebase-starter | web app scaffold (`src/`, config) | (c) 2023 Scott Milliorn | MIT |
| freecad-mcp | bridge pattern adapted in `conjur3/conjur3-pilot/addon/` (XML-RPC addon, GUI task queue, screenshot capture) | (c) 2025 Shirokuma (k tanaka) | MIT |
| Hermes Agent | patched files in `conjur3/hermes-patches/` | (c) 2025-2026 Nous Research, Inc. | MIT |
| Hermes WebUI | patched files in `conjur3/hermes-patches/app/` | (c) 2026 nesquena and contributors | MIT |
| websocket-client 1.8.0 | vendored unmodified in `conjur3/conjur3-pilot/addon/conjur3_pilot/vendor/websocket/` | (c) 2024 engn33r | Apache-2.0 (text in that directory's `LICENSE`) |

The MIT license text that applies to each MIT component above is the text in
[LICENSE](./LICENSE), with that component's copyright line. Full copies for the
Hermes projects are in [conjur3/THIRD_PARTY_LICENSES.md](./conjur3/THIRD_PARTY_LICENSES.md).

## Software used at runtime but not distributed here

| Component | How it is used | License |
| --- | --- | --- |
| [FreeCAD](https://www.freecad.org) | Conjur3 drives a FreeCAD process the user installs; the Docker image builds on `freecad/freecad-cli` | LGPL-2.1-or-later |
| [FreeCAD Fasteners Workbench](https://github.com/shaise/FreeCAD_FastenersWB) | cloned at install/build time by `conjur3/scripts/install_fasteners_wb.sh` | LGPL-2.1 |
| [freecad-ai](https://github.com/ghbalf/freecad-ai) | design inspiration for the tool surface; no code included | LGPL-2.1 |

The Conjur3 addon is loaded by FreeCAD as a Python module and calls its public
scripting API. If you redistribute a bundle that contains FreeCAD or the
Fasteners Workbench (for example a prebuilt container image), their LGPL terms
apply to those parts of the bundle.
