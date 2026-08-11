# OnePlus Nord N10 Metro bootloader-unlock trigger

> A narrowly scoped, offline `param` image tool for one verified OnePlus Nord N10 5G Metro path: BE2025 / software project 20885 to the Global 20886 RPMB trigger, followed by the bootloader's normal unlock flow.

This project does **not** unlock a connected phone. It validates a 1 MiB `param` backup and can create a separate trigger image. Reading or writing the phone remains a deliberate, manual operation with [bkerler/edl](https://github.com/bkerler/edl) or another trusted service tool.

> [!CAUTION]
> Writing `param`, letting ABL update RPMB, and unlocking the bootloader can erase all user data or permanently prevent normal boot. A file backup of `param` does not back up RPMB. Treat the RPMB change as potentially irreversible.

- Full English guide: [docs/en.md](docs/en.md)
- Russian guide: [docs/ru.md](docs/ru.md)
- Recovery boundaries: [docs/recovery.md](docs/recovery.md)
- Security policy: [SECURITY.md](SECURITY.md)

## Scope

The only hardware path verified for this repository is:

| Property | Verified value |
| --- | --- |
| Device | OnePlus Nord N10 5G Metro |
| Marketing model | BE2025 |
| Starting software project | 20885 / `0x3A403A71` |
| Target software project | Global 20886 / `0xB8BD9E39` |
| Input | An unmodified, device-owned 1 MiB `param` read |
| Result | A one-shot ABL trigger image; **not** an unlocked image |

BE2025 is the phone's marketing model. `20885` is the starting Metro
**software-project code**, not another marketing model. In bkerler/edl the
required selector is nevertheless named `--devicemodel`; every EDL command in
the Russian guide deliberately uses `--devicemodel=20885`. Keep that source
value during backup, write, readback, and reset. Do not substitute `BE2025`, the
target project `20886`, or a code from another SKU.

Do not infer compatibility with BE2028, other carrier variants, another ABL build, another `param` layout, or another physical device. Never use a donor `param` image. There is no static-key or cross-model fallback: a wrong SoC serial or incompatible record fails closed.

This is also **not** a SIM/network unlock, IMEI change, firmware conversion, critical-partition unlock, or Ubuntu Touch installer.

## Evidence and interpretation

### Directly observed on the tested BE2025

- The original image was exactly 1,048,576 bytes and contained matching primary and backup encrypted software-ID records at `0x4F000` and `0xCF000`.
- Both records validated cryptographically with the tested device's SoC serial and reported the pristine Metro state.
- The generated Global trigger changed bytes only in the counter, integrity fields, and encrypted payload of those two records.
- The EDL readback before reboot was byte-for-byte identical to the generated trigger image.
- After ABL ran, `param` changed again and the normal bootloader-unlock flow succeeded without a OnePlus unlock-token image.
- Bootloader unlock performed the expected factory reset.

### Reverse-engineering interpretation

ABL appears to recognize the one-shot `sw_proj_id_proc` value, copy the selected software-project ID from `param` to RPMB, and clear the trigger. This interpretation is supported by ABL control-flow analysis, its diagnostic strings, the pre/post-boot images, and the successful unlock. It is not vendor documentation.

### What this does not prove

- That the procedure is repeatable on every BE2025 or safe on a different firmware revision.
- That restoring the original `param` restores RPMB. It does not.
- That the experimental Metro rollback trigger works on hardware or is safe to use.
- That changing the SWID converts the rest of the phone to Global firmware.
- That OnePlus, Metro, T-Mobile, or UBports supports the resulting device.

## Install the offline tool

Requirements: Python 3.11 or newer. The tool uses PyCryptodome for the legacy on-disk AES/MD5 format; it has no USB, ADB, fastboot, or EDL integration.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
```

Confirm the CLI is the expected build:

```bash
oneplus-n10-param --help
```

Keep device dumps outside the repository. The supplied `.gitignore` rejects common dump, firmware, loader, log, and identifier filenames, but that is not a substitute for careful handling.

The examples below assume `N10_PRIVATE_DIR` is an absolute private directory
outside the clone. The Russian guide creates and verifies it before any read:

```bash
export N10_PRIVATE_DIR="/ABSOLUTE/PRIVATE/PATH/oneplus-n10-be2025"
export N10_SOC_SERIAL="0xREPLACE_WITH_THE_RECORDED_SOC_SERIAL"
```

## Offline use

Obtain the SoC serial from the local Sahara/EDL connection output. It is the value printed as `Serial: 0x...`; it is not the IMEI, Android serial, or PCBA number. Do not publish it.

First inspect the untouched device-owned backup:

```bash
oneplus-n10-param inspect "$N10_PRIVATE_DIR/param.before.bin" \
  --soc-serial "$N10_SOC_SERIAL"
```

Continue only if the report says all of the following:

- `size=1048576`
- `state=metro-pristine`
- `duplicates_match=True`
- both records show the same counter, `swid=0x3A403A71`, and `proc=0x00000000`

Run a dry-run. Without `--output`, this command writes nothing:

```bash
oneplus-n10-param patch-global "$N10_PRIVATE_DIR/param.before.bin" \
  --soc-serial "$N10_SOC_SERIAL"
```

Generate a new image only after reviewing the dry-run report:

```bash
oneplus-n10-param patch-global "$N10_PRIVATE_DIR/param.before.bin" \
  --soc-serial "$N10_SOC_SERIAL" \
  --output "$N10_PRIVATE_DIR/param.global-trigger.bin"
```

Inspect the result independently:

```bash
oneplus-n10-param inspect "$N10_PRIVATE_DIR/param.global-trigger.bin" \
  --soc-serial "$N10_SOC_SERIAL"
```

The expected state is `global-trigger`. The tool refuses unknown layouts and states, mismatched duplicate records, invalid hashes, a wrong SoC serial, in-place modification, and accidental output replacement. It never alters the source image.

## Device operation

Do not automate the irreversible steps. The safe sequence is:

1. Disconnect every other phone and service-mode USB device. Require exactly one `05c6:9008` transport; the pinned upstream EDL client otherwise selects the first match rather than binding a write to the expected SoC serial.
2. Verify that single target's SoC serial and GPT with a matching, legally obtained, vendor-signed Firehose programmer.
3. Save real primary-GPT reads for every UFS LUN, a separately verified XML layout, and device-owned recovery partitions including an untouched `param` preimage.
4. Generate the trigger offline from that exact preimage.
5. Write only the `param` partition in EDL.
6. Before any reset, read `param` back to a different file and require a byte-for-byte match with the generated image.
7. Let ABL run once so it can consume the trigger.
8. Enter fastboot and invoke the normal interactive unlock command. Confirm the wipe on the phone itself.
9. Verify `fastboot getvar unlocked` reports `yes`.

The exact macOS/Linux commands, backup set, and stop conditions are in [the Russian guide](docs/ru.md). Recovery depends on whether ABL has already run; read [docs/recovery.md](docs/recovery.md) before writing anything.

## Ubuntu Touch support boundary

Unlocking is only a prerequisite. As of the evidence snapshot on 2026-08-11:

- The [official UBports device page](https://devices.ubuntu-touch.io/device/billie/) instructs users to start from EU or Global OxygenOS 10.5.7.
- The [community port README](https://gitlab.com/ubports/porting/community-ports/android10/oneplus-nord-n10/oneplus-billie/-/blob/816b30257cee2ab30504cf492f4fd4ae501ff843/README.md) lists US Metro/T-Mobile firmware as unsupported.
- The pinned [installer configuration](https://github.com/ubports/installer-configs/blob/f441524a202cd717c2da11d6e9549f7a76febc2d/v2/devices/billie.yml#L103-L135) downloads and flashes `persist.img` during bootstrap. It does not validate or support this Metro-to-Global SWID procedure.

> [!WARNING]
> Do **not** run the unmodified UBports Installer on a converted BE2025. Its
> `billie` flow can replace the device-owned Metro `persist` partition with a
> cross-SKU image containing calibration data. A successful unlock or Global
> SWID does not make the hardware an officially supported variant. This
> repository does not publish or validate a safe Ubuntu Touch installation
> path; preserve the Metro `persist` backup and stop at `unlocked: yes`.

## Upstream credit and license

The understanding of the OnePlus encrypted `param` record structure was informed by B. Kerler's GPL-licensed [bkerler/edl](https://github.com/bkerler/edl), in particular [`oneplus_param.py`](https://github.com/bkerler/edl/blob/e4266d278728660a79f170d498dab3bb8ed641b1/edlclient/Library/Modules/oneplus_param.py). The BE2025 implementation here deliberately hashes the 26 ASCII hex characters reconstructed by the tested ABL; it does **not** use the hex-decoded seed construction in that upstream module. This repository does not bundle upstream EDL code, proprietary Firehose programmers, firmware, device dumps, or device identifiers.

This project is licensed under **GPL-3.0-or-later**. See [LICENSE](LICENSE).
