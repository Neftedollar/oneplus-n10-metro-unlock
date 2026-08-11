# OnePlus Nord N10 5G Metro BE2025: preparing a standard bootloader unlock

This guide produces a verified one-time `param` trigger for changing the software project from Metro 20885 to Global 20886; it does not provide a ready-unlocked image. The bootloader performs the unlock through its standard interactive mechanism.

> [!DANGER]
> Unlocking erases user data and may leave the phone unable to boot normally. Once ABL runs, RPMB changes; an ordinary `param.before.bin` is not an RPMB backup and does not guarantee rollback.

## 1. Applicability boundary

This applies **only** to a verified OnePlus Nord N10 5G Metro marked BE2025, with source software project 20885 (`0x3A403A71`), a verified `metro-pristine` source `param`, and target Global project 20886 (`0xB8BD9E39`).

BE2025 is the marketing model. `20885` is the Metro **software project code**, not a model name. bkerler/edl historically calls this CLI parameter `--devicemodel`; use exactly `--devicemodel=20885` in every EDL command below. Retain source value 20885 for reading, writing, readback, and reset: never substitute BE2025, target 20886, or another SKU code.

Stop if any item is unconfirmed. BE2028/T-Mobile guides and scripts concern a different SKU; do not take their keys, serials, images, values, or “similar” mode. This project does not SIM-unlock, alter IMEI, convert complete firmware, unlock critical partitions, or install Ubuntu Touch.

## 2. Confirmed facts and inference

### Confirmed on one physical BE2025

- The source `param` was exactly 1 MiB.
- Primary and backup encrypted SWID records at `0x4F000` and `0xCF000` matched and passed structural and cryptographic checks.
- The offline patch changed only allowed fields within those two records.
- EDL readback before reboot was byte-identical to the generated trigger.
- After ABL ran, it changed `param`; the standard interactive unlock worked without a OnePlus unlock-token image.
- Unlocking performed the standard factory reset.

### Reverse-engineering inference

ABL control flow, diagnostics, and observed state strongly indicate that the trigger makes ABL write the target SWID to RPMB and then clear the trigger flag. This is not OnePlus documentation.

### Not confirmed

- Compatibility with another BE2025, ABL version, or SKU.
- Safety of repeat application.
- Hardware RPMB rollback to Metro.
- Official support by OnePlus, Metro, T-Mobile, or UBports.

## 3. Prerequisites

You need a lawfully owned, erasable BE2025; a separate personal Android-data backup; a stable direct USB cable and charged battery; reproducible Qualcomm EDL 9008 entry/exit; a compatible, lawfully obtained manufacturer-signed Firehose programmer; macOS/Linux with Python 3.11+, `adb`, `fastboot`, Git, and `libusb`; local [bkerler/edl](https://github.com/bkerler/edl); and Android **OEM unlocking** enabled where possible.

The repository intentionally contains no Firehose, OPS/MSM packages, firmware, dumps, or device identifiers. A random internet Firehose can fail or damage the partition layout.

### macOS, including Apple Silicon

From the repository root, install dependencies and place EDL in an absolute directory **outside** the clone. This pinned commit is the verified version; an update needs a new audit.

```bash
brew install libusb git python@3.12
brew install --cask android-platform-tools
export N10_EDL_DIR="/ABSOLUTE/PRIVATE/PATH/oneplus-edl-e4266d2"
git clone https://github.com/bkerler/edl.git "$N10_EDL_DIR"
git -C "$N10_EDL_DIR" checkout e4266d278728660a79f170d498dab3bb8ed641b1
test "$(git -C "$N10_EDL_DIR" rev-parse HEAD)" = \
  e4266d278728660a79f170d498dab3bb8ed641b1 || exit 1
git -C "$N10_EDL_DIR" submodule update --init --recursive
python3.12 -m venv "$N10_EDL_DIR/.venv"
source "$N10_EDL_DIR/.venv/bin/activate"
python -m pip install "$N10_EDL_DIR"
export N10_EDL="$N10_EDL_DIR/.venv/bin/edl"
export N10_EDL_PYTHON="$N10_EDL_DIR/.venv/bin/python"
test -x "$N10_EDL" && test -x "$N10_EDL_PYTHON" || exit 1
```

Check reading only:

```bash
"$N10_EDL" --help
fastboot --version
```

A successful CLI launch does not prove Firehose compatibility. Only a correct GPT read and repeatable error-free readback do that.

## 4. Prepare a private backup directory

From the clone root, set a **new absolute** path outside git; do not use relative `local-backup`. The path must not exist: this prevents reuse of an old/weakly protected directory and broad permission changes. The block creates `0700` and stops on clone intersection or symlink.

```bash
export N10_REPO_ROOT="$(git rev-parse --show-toplevel)"
export N10_PRIVATE_DIR="/ABSOLUTE/PRIVATE/PATH/oneplus-n10-be2025"
umask 077

python3 - <<'PY'
import os
import stat
from pathlib import Path

repo = Path(os.environ["N10_REPO_ROOT"]).resolve()
raw = Path(os.environ["N10_PRIVATE_DIR"])
if not raw.is_absolute():
    raise SystemExit("STOP: N10_PRIVATE_DIR must be absolute")
if raw.is_symlink():
    raise SystemExit("STOP: N10_PRIVATE_DIR must not be a symlink")
if raw.exists():
    raise SystemExit("STOP: choose a new, not-yet-existing backup directory")
target = raw.resolve()
if target == repo or repo in target.parents or target in repo.parents:
    raise SystemExit("STOP: backup directory intersects the git repository")
target.mkdir(parents=True, exist_ok=False, mode=0o700)
target.chmod(0o700)
if not target.is_dir() or stat.S_IMODE(target.stat().st_mode) != 0o700:
    raise SystemExit("STOP: backup directory is not a private 0700 directory")
print("private_backup_dir_ok=yes")
PY
```

Continue only if the final line is `private_backup_dir_ok=yes`. Keep `umask 077` active for every later EDL command. Never publish `param`, `devinfo`, `config`, `persist`, modem/EFS partitions, GPT, SoC serial, IMEI, PCBA, Firehose, or a complete EDL log. Preserve the original `param` unchanged in at least two physical locations.

## 5. Bind operations to one EDL device and save the partition map

Disconnect every other phone and service/download-mode device, then enter EDL on the target phone. Verified transport is Qualcomm `05c6:9008`. Pinned bkerler/edl chooses the first matching USB device and `w` cannot bind to an expected SoC serial. Thus physically leave exactly one matching USB device and check immediately before every EDL command.

Define this fail-closed guard in the terminal where EDL is configured:

```bash
require_single_9008() {
  "$N10_EDL_PYTHON" - <<'PY'
from usb.core import find

devices = list(find(find_all=True, idVendor=0x05C6, idProduct=0x9008))
count = len(devices)
print(f"qualcomm_9008_count={count}")
if count != 1:
    raise SystemExit("STOP: expected exactly one Qualcomm 05c6:9008 device")
PY
}
```

Replace programmer paths in all examples with your local absolute path. First read-only check:

```bash
require_single_9008 && "$N10_EDL" printgpt --vid=0x05c6 --pid=0x9008 \
  --devicemodel=20885 --memory=ufs \
  --loader=/ABSOLUTE/PATH/TO/MATCHING_FIREHOSE
```

Output must show a UFS layout, six LUNs `0..5`, and one expected `param`. Sahara’s `Serial: 0x...` is a 32-bit **SoC serial**, not IMEI, Android serial, or PCBA. Record it locally for offline checks:

```bash
export N10_SOC_SERIAL="0xREPLACE_WITH_THE_RECORDED_SOC_SERIAL"
```

Each later EDL run must show the same serial. Stop if absent or mismatched; do not publish it. A CLI argument value is visible in shell history and local process lists.

Create a new directory and save the actual first 32 GPT sectors for every LUN:

```bash
mkdir -m 700 "$N10_PRIVATE_DIR/gpt" || {
  echo "STOP: GPT backup directory already exists" >&2
  exit 1
}

require_single_9008 && "$N10_EDL" r gpt "$N10_PRIVATE_DIR/gpt/primary" \
  --vid=0x05c6 --pid=0x9008 --devicemodel=20885 --memory=ufs \
  --loader=/ABSOLUTE/PATH/TO/MATCHING_FIREHOSE

for lun in 0 1 2 3 4 5; do
  test -s "$N10_PRIVATE_DIR/gpt/primary.lun$lun" || {
    echo "STOP: missing primary GPT read for LUN $lun" >&2
    exit 1
  }
done
chmod 400 "$N10_PRIVATE_DIR"/gpt/primary.lun{0,1,2,3,4,5}
```

Separately create the XML map and require six non-empty files:

```bash
mkdir -m 700 "$N10_PRIVATE_DIR/gpt/xml" || {
  echo "STOP: GPT XML directory already exists" >&2
  exit 1
}

require_single_9008 && "$N10_EDL" gpt "$N10_PRIVATE_DIR/gpt/xml" --genxml \
  --vid=0x05c6 --pid=0x9008 --devicemodel=20885 --memory=ufs \
  --loader=/ABSOLUTE/PATH/TO/MATCHING_FIREHOSE

for lun in 0 1 2 3 4 5; do
  test -s "$N10_PRIVATE_DIR/gpt/xml/rawprogram$lun.xml" || {
    echo "STOP: missing GPT XML for LUN $lun" >&2
    exit 1
  }
done
chmod 400 "$N10_PRIVATE_DIR"/gpt/xml/rawprogram{0,1,2,3,4,5}.xml
```

Important: pinned upstream `edl gpt` writes XML, but its `gpt_main*.bin`/`gpt_backup*.bin` write is commented out even while CLI says `Dumped GPT`. Do not regard this as a binary backup or use the XML as a QFIL program. The real primary-GPT files above come specifically from `edl r gpt`.

If LUN count differs from six, `param` is ambiguous, the serial changed, automatic LUN selection is wrong, or Firehose errors, stop. Do not guess a LUN by writing.

## 6. Make required backups

First read `param` twice into distinct files:

```bash
test ! -e "$N10_PRIVATE_DIR/param.before.bin" || {
  echo "STOP: original preimage path already exists" >&2
  exit 1
}
test ! -e "$N10_PRIVATE_DIR/param.before.second-read.bin" || {
  echo "STOP: second-read path already exists" >&2
  exit 1
}

require_single_9008 && "$N10_EDL" r param "$N10_PRIVATE_DIR/param.before.bin" \
  --vid=0x05c6 --pid=0x9008 --devicemodel=20885 --memory=ufs \
  --loader=/ABSOLUTE/PATH/TO/MATCHING_FIREHOSE

require_single_9008 && "$N10_EDL" r param "$N10_PRIVATE_DIR/param.before.second-read.bin" \
  --vid=0x05c6 --pid=0x9008 --devicemodel=20885 --memory=ufs \
  --loader=/ABSOLUTE/PATH/TO/MATCHING_FIREHOSE

cmp "$N10_PRIVATE_DIR/param.before.bin" \
  "$N10_PRIVATE_DIR/param.before.second-read.bin" || exit 1
shasum -a 256 "$N10_PRIVATE_DIR/param.before.bin"
chmod 400 "$N10_PRIVATE_DIR/param.before.bin" \
  "$N10_PRIVATE_DIR/param.before.second-read.bin"
```

`cmp` must print nothing and exit 0. Each file must be 1,048,576 bytes.

Also save these if the names are present in your GPT:

| Priority | Partitions | Why |
| --- | --- | --- |
| Required | `param`, primary-GPT read and XML for each UFS LUN | The only writable partition and verifiable recovery map |
| Strongly recommended | `devinfo`, `config`, `abl_a`, `abl_b` | Unlock/model state and ABL processing the trigger |
| Strongly recommended | `fsc`, `fsg`, `modemst1`, `modemst2` | Personal modem/EFS data |
| Strongly recommended | `persist` | Camera/sensor calibration and WLAN data |

Read each partition as follows:

```bash
test ! -e "$N10_PRIVATE_DIR/PARTITION.before.bin" || exit 1
require_single_9008 && "$N10_EDL" r PARTITION "$N10_PRIVATE_DIR/PARTITION.before.bin" \
  --vid=0x05c6 --pid=0x9008 --devicemodel=20885 --memory=ufs \
  --loader=/ABSOLUTE/PATH/TO/MATCHING_FIREHOSE
chmod 400 "$N10_PRIVATE_DIR/PARTITION.before.bin"
```

Substitute only a name from your GPT; no specific LUN is assumed.

## 7. Install and validate the offline patcher

At the project root create a separate environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
oneplus-n10-param --help
```

The tool has no USB/EDL code and does not contact the phone. It always reads a regular file; without `--output`, patch commands are dry runs only.

Validate the source image with the local SoC serial:

```bash
oneplus-n10-param inspect "$N10_PRIVATE_DIR/param.before.bin" \
  --soc-serial "$N10_SOC_SERIAL"
```

Continue only with `size=1048576`, `state=metro-pristine`, `duplicates_match=True`, and two records with matching counters, `swid=0x3A403A71`, and `proc=0x00000000`. `inner MD5 mismatch` normally means wrong SoC serial or an incompatible/corrupt image; do not use another person’s serial or a “static key” from another writeup.

## 8. Create the Global trigger offline

First dry run:

```bash
oneplus-n10-param patch-global "$N10_PRIVATE_DIR/param.before.bin" \
  --soc-serial "$N10_SOC_SERIAL"
```

The report must show `dry_run=True`, `output_state=global-trigger`, target SWID `0xB8BD9E39`, and only two allowed change ranges. Then create a new file:

```bash
oneplus-n10-param patch-global "$N10_PRIVATE_DIR/param.before.bin" \
  --soc-serial "$N10_SOC_SERIAL" \
  --output "$N10_PRIVATE_DIR/param.global-trigger.bin"
```

Do not use `--overwrite` on the first run; the tool deliberately prohibits modifying its input in place. Validate the generated file again:

```bash
oneplus-n10-param inspect "$N10_PRIVATE_DIR/param.global-trigger.bin" \
  --soc-serial "$N10_SOC_SERIAL"

shasum -a 256 \
  "$N10_PRIVATE_DIR/param.before.bin" \
  "$N10_PRIVATE_DIR/param.global-trigger.bin"
```

## 9. The only EDL write

Until now the phone is unchanged. The next command is the dangerous boundary. Confirm source and trigger still pass `inspect`; two matching original `param` copies exist; Firehose has read that `param`; exactly one `05c6:9008` is connected and latest EDL output shows the recorded SoC serial; you read [recovery.md](recovery.md); and you accept data loss and no working RPMB rollback.

Write only `param`:

```bash
require_single_9008 && "$N10_EDL" printgpt --vid=0x05c6 --pid=0x9008 \
  --devicemodel=20885 --memory=ufs \
  --loader=/ABSOLUTE/PATH/TO/MATCHING_FIREHOSE
```

Compare `Serial: 0x...` manually with `N10_SOC_SERIAL` again. If absent or different, **do not write**. Only then:

```bash
require_single_9008 && "$N10_EDL" w param "$N10_PRIVATE_DIR/param.global-trigger.bin" \
  --vid=0x05c6 --pid=0x9008 --devicemodel=20885 --memory=ufs \
  --loader=/ABSOLUTE/PATH/TO/MATCHING_FIREHOSE
```

Do not reset or disconnect power before readback completes.

## 10. Mandatory readback before first reset

Read the written partition into a new file:

```bash
test ! -e "$N10_PRIVATE_DIR/param.pre-reset-readback.bin" || {
  echo "STOP: pre-reset readback path already exists" >&2
  exit 1
}
require_single_9008 && "$N10_EDL" r param "$N10_PRIVATE_DIR/param.pre-reset-readback.bin" \
  --vid=0x05c6 --pid=0x9008 --devicemodel=20885 --memory=ufs \
  --loader=/ABSOLUTE/PATH/TO/MATCHING_FIREHOSE

cmp \
  "$N10_PRIVATE_DIR/param.global-trigger.bin" \
  "$N10_PRIVATE_DIR/param.pre-reset-readback.bin" || exit 1

shasum -a 256 \
  "$N10_PRIVATE_DIR/param.global-trigger.bin" \
  "$N10_PRIVATE_DIR/param.pre-reset-readback.bin"
chmod 400 "$N10_PRIVATE_DIR/param.pre-reset-readback.bin"
```

All must hold: `cmp` exited 0 with no output; both SHA-256 values match; and readback `inspect` reports `global-trigger`. On any mismatch **do not run ABL**; follow the “before the first reset” scenario in [recovery.md](recovery.md).

## 11. Run ABL once

Only after successful readback:

```bash
require_single_9008 && "$N10_EDL" reset --resetmode=reset \
  --vid=0x05c6 --pid=0x9008 --devicemodel=20885 \
  --loader=/ABSOLUTE/PATH/TO/MATCHING_FIREHOSE
```

If reset does not leave EDL, use the physical power combination known for your phone. ABL must run to process the trigger and alter RPMB. Do not flash the trigger again “for reliability”: after ABL runs, the pre-reset image is no longer current state.

## 12. Perform the standard unlock

Enter fastboot and ensure exactly one expected phone is visible:

```bash
fastboot devices
fastboot getvar unlocked
```

Run the ordinary interactive unlock:

```bash
fastboot flashing unlock
```

Confirm using buttons **on the phone**. Bootloader wiping userdata is expected. Do not disconnect USB or power while wiping/rebooting. Then enter fastboot again and check:

```bash
fastboot getvar unlocked
```

Only `unlocked: yes` is success. The orange Verified Boot warning after unlock is expected. If OnePlus unlock-token is required again, do not write again: save exact error text and go to [recovery.md](recovery.md).

## 13. Ubuntu Touch: separate and unsupported

This project ends at `unlocked: yes`. **Do not run standard UBports Installer on a converted BE2025 as-is.** The pinned [billie installer configuration](https://github.com/ubports/installer-configs/blob/f441524a202cd717c2da11d6e9549f7a76febc2d/v2/devices/billie.yml#L103-L135) downloads and flashes `persist.img` during bootstrap, possibly replacing unique calibrated Metro `persist` with a cross-SKU image.

Official support boundary material:

- [official OnePlus Nord N10 5G page](https://devices.ubuntu-touch.io/device/billie/);
- [community-port source](https://gitlab.com/ubports/porting/community-ports/android10/oneplus-nord-n10/oneplus-billie/-/blob/816b30257cee2ab30504cf492f4fd4ae501ff843/README.md).

As of 2026-08-11, the official path needs EU or Global OxygenOS 10.5.7; the port README classifies US Metro/T-Mobile firmware as unsupported. SWID change plus unlock does not make BE2025 officially supported. This repository neither publishes nor validates a safe Ubuntu Touch installation path: retain Metro `persist` and stop at `unlocked: yes`.

## 14. Attribution

The encrypted `param` structure is understood in part from B. Kerler’s GPL code: [bkerler/edl](https://github.com/bkerler/edl) and [`oneplus_param.py`](https://github.com/bkerler/edl/blob/e4266d278728660a79f170d498dab3bb8ed641b1/edlclient/Library/Modules/oneplus_param.py). The BE2025 implementation deliberately hashes the ASCII string recovered from verified ABL, unlike upstream’s hex-decoded construction. This project includes no EDL code, vendor Firehose, or proprietary firmware images.

Project license: [GPL-3.0-or-later](../LICENSE).

