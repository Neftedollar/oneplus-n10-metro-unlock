# Security policy

This is a research-grade, offline image transformer for one narrowly verified device state. It is not a remote service, device flasher, or general OnePlus unlock framework.

## Supported scope

| Version | Security fixes |
| --- | --- |
| Current `0.1.x` source | Yes |
| Unpublished research scripts and old BE2028/T-Mobile writeups | No |
| Forks with relaxed validation or added automatic flashing | No |

The supported input is an exact 1 MiB, device-owned BE2025 Metro `param` preimage that validates as `metro-pristine`. Other models, software-project IDs, crypto versions, record layouts, and partially modified states are intentionally rejected.

## Reporting a vulnerability

Use the hosting platform's private security-advisory / “Report a vulnerability” feature when available. If no private channel is available, open a minimal public issue asking maintainers to establish one; do not attach device data or exploit details to that issue.

Useful reports include:

- project version or commit;
- Python and operating-system versions;
- the command shape with the SoC serial replaced by `REDACTED`;
- expected and actual behavior;
- a minimal **synthetic** reproducer or test fixture;
- whether any output file was created or replaced.

Do not send a real `param`, `devinfo`, `config`, `persist`, GPT, EFS/modem partition, Firehose programmer, firmware package, full EDL log, SoC serial, Android serial, IMEI, MEID, PCBA number, MAC address, or unlock material. A hash of a private dump can also act as a stable fingerprint; share it only through an agreed private channel when strictly necessary.

## Security properties of the offline tool

The tool is designed to:

- perform no USB, ADB, fastboot, EDL, network, or block-device access;
- require an exact 1,048,576-byte regular input file;
- validate both encrypted SWID records, their integrity fields, versions, counters, contents, and equality;
- accept only known BE2025 Metro/Global states;
- derive the record key from a caller-supplied 32-bit SoC serial without storing that serial in the output;
- limit changes to the two validated SID records and verify the permitted byte ranges;
- keep the source immutable and reject in-place output;
- default patch commands to a no-output dry-run;
- create output with owner-only permissions and verify it after atomic installation;
- refuse to overwrite an output unless `--overwrite` is explicit.

A defect that violates one of these properties is security-relevant.

## What the tool does not secure

The tool cannot:

- prove that the operator owns or is authorized to modify a phone;
- authenticate a `param` dump as coming from the claimed physical device;
- determine whether a Firehose programmer is genuine or compatible;
- bind an external EDL write to the intended phone; the documented pinned client selects the first matching USB transport, so the guide requires exactly one `05c6:9008` device;
- protect a serial typed into shell history;
- prevent an operator from placing private backups inside a clone or later forcing ignored files into Git;
- make an EDL write atomic or safe during cable/power failure;
- back up, read, authenticate, or roll back RPMB;
- prevent the bootloader's factory reset;
- validate the rest of the firmware or make a Metro device an officially supported Global device;
- guarantee that an OEM/service restore repairs every secure or calibration state.

Device writes are deliberately outside the program. Review [docs/recovery.md](docs/recovery.md) before using any external EDL command.

## Dependency and provenance policy

The encrypted OnePlus `param` structure was informed by B. Kerler's GPL-licensed [bkerler/edl](https://github.com/bkerler/edl), especially [`oneplus_param.py`](https://github.com/bkerler/edl/blob/e4266d278728660a79f170d498dab3bb8ed641b1/edlclient/Library/Modules/oneplus_param.py). The BE2025 key derivation in this project follows the tested ABL's ASCII construction and intentionally differs from the upstream module's hex-decoded construction. Keep this attribution and the `GPL-3.0-or-later` license when redistributing modified versions.

This repository must not distribute proprietary Firehose programmers, OPS/MSM packages, stock firmware, real device dumps, or identifiers. Retrieve Python dependencies from a trusted package index, review lock/build metadata before release, and do not replace strict version bounds with unreviewed vendored code.

## Operational disclosure

If a vulnerability could cause the tool to accept a wrong device state, alter bytes outside the documented SID records, overwrite its input, or expose a device identifier, treat it as high severity even though the program is offline. Coordinate a fix and release before publishing detailed reproduction steps.
