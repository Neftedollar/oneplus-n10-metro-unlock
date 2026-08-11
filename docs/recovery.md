# Recovery boundaries

Recovery depends on one question: **has ABL executed since the trigger image was written?** Before that boundary, RPMB should still contain its original value. After that boundary, restoring a file-backed partition does not restore RPMB.

Read this document before the first EDL write.

All paths below use the absolute private `N10_PRIVATE_DIR` created by the
Russian guide. Never substitute a path inside the clone. Re-establish the USB
guard after opening a new terminal; every EDL command below intentionally
fails if the guard is absent:

```bash
: "${N10_PRIVATE_DIR:?set the existing absolute private backup directory}"
: "${N10_SOC_SERIAL:?set the SoC serial recorded during the original read}"
: "${N10_EDL:?set the absolute path to the pinned EDL executable}"
: "${N10_EDL_PYTHON:?set the absolute path to the pinned EDL Python}"

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

The pinned upstream EDL client selects the first matching USB device; it does
not bind a write to the expected SoC serial. Disconnect every other phone and
service-mode device, require exactly one `05c6:9008`, and compare the Sahara
`Serial: 0x...` line with the value recorded during the original read before
any write.

## Recovery assets to keep offline

At minimum, keep:

- two independently read, byte-identical copies of the original `param`;
- real 32-sector primary-GPT reads and separately verified XML for all six UFS LUNs;
- the exact Firehose programmer that already completed read-only operations;
- SHA-256 values for every backup and generated image;
- strongly recommended device-owned backups of `devinfo`, `config`, `abl_a`, `abl_b`, `fsc`, `fsg`, `modemst1`, `modemst2`, and `persist`;
- a separate Android user-data backup made before entering this workflow.

None of these files is an RPMB backup. Do not upload them to an issue, paste service logs containing identifiers, or use another phone's files.

## Stage A: nothing has been written

If `inspect` or `patch-global` refuses the input, stop. The tool's refusal is the recovery: no phone state has changed.

Do not work around:

- an image size other than 1,048,576 bytes;
- a state other than `metro-pristine`;
- a wrong-SoC-serial / inner-MD5 failure;
- different primary and backup records;
- an unknown SWID/proc pair or format version.

These checks deliberately exclude other models and firmware layouts.

## Stage B: `param` was written, but ABL has not run

This is the only phase in which restoring the original `param` is a meaningful pre-trigger rollback. Keep the phone in EDL. Do not reset or disconnect it until the written partition has been read back.

If the trigger readback differs from the generated image, save both files locally and read `param` a second time. If the two readbacks differ from each other, the transport is not stable: do not issue another write. Fix the cable/host/loader path or use qualified service recovery.

Only when repeated readbacks are stable but contain the wrong bytes should you restore the exact preimage from this phone:

```bash
require_single_9008 && "$N10_EDL" printgpt \
  --vid=0x05c6 --pid=0x9008 --devicemodel=20885 --memory=ufs \
  --loader=/ABSOLUTE/PATH/TO/MATCHING_FIREHOSE
```

Manually compare `Serial: 0x...` with `N10_SOC_SERIAL`; stop if it is missing
or different. Only then perform the restore and create a new readback:

```bash
require_single_9008 && "$N10_EDL" w param "$N10_PRIVATE_DIR/param.before.bin" \
  --vid=0x05c6 --pid=0x9008 --devicemodel=20885 --memory=ufs \
  --loader=/ABSOLUTE/PATH/TO/MATCHING_FIREHOSE

test ! -e "$N10_PRIVATE_DIR/param.restore-readback.bin" || exit 1
require_single_9008 && "$N10_EDL" r param "$N10_PRIVATE_DIR/param.restore-readback.bin" \
  --vid=0x05c6 --pid=0x9008 --devicemodel=20885 --memory=ufs \
  --loader=/ABSOLUTE/PATH/TO/MATCHING_FIREHOSE

cmp "$N10_PRIVATE_DIR/param.before.bin" \
  "$N10_PRIVATE_DIR/param.restore-readback.bin" || exit 1
shasum -a 256 \
  "$N10_PRIVATE_DIR/param.before.bin" \
  "$N10_PRIVATE_DIR/param.restore-readback.bin"
chmod 400 "$N10_PRIVATE_DIR/param.restore-readback.bin"
```

Reset only if `cmp` succeeds and both hashes match. If restore readback still differs, stop issuing writes. Repeated writes through an unstable cable, incompatible loader, or wrong LUN are more likely to make recovery worse.

The same procedure applies if the trigger readback matched but you changed your mind **before** running ABL.

## Stage C: ABL ran, but bootloader unlock did not

Assume RPMB may already contain the Global 20886 SWID. Restoring `param.before.bin` alone is no longer a rollback and may simply be overwritten or reconciled by ABL on the next boot.

If fastboot still works:

1. Do not flash the trigger again.
2. Save the exact fastboot error locally.
3. Check `fastboot getvar unlocked`.
4. If the normal unlock command still requests a token, stop. Do not try commands or images from BE2028/T-Mobile guides.

If you can safely re-enter EDL, make a new read-only capture:

```bash
test ! -e "$N10_PRIVATE_DIR/param.after-abl.bin" || exit 1
require_single_9008 && "$N10_EDL" r param "$N10_PRIVATE_DIR/param.after-abl.bin" \
  --vid=0x05c6 --pid=0x9008 --devicemodel=20885 --memory=ufs \
  --loader=/ABSOLUTE/PATH/TO/MATCHING_FIREHOSE

oneplus-n10-param inspect "$N10_PRIVATE_DIR/param.after-abl.bin" \
  --soc-serial "$N10_SOC_SERIAL"
chmod 400 "$N10_PRIVATE_DIR/param.after-abl.bin"
```

The observed successful path settled to a cleared Global record after ABL. Any other state is evidence for analysis, not permission to write again.

## Stage D: unlock was confirmed

The factory reset is intentional and cannot be undone with EDL partition backups. Android file-based encryption also means a raw userdata image is not a practical substitute for a pre-unlock user-data backup.

Verify only:

```bash
fastboot getvar unlocked
```

An answer of `unlocked: yes` completes this project's scope. Do not relock after cross-SKU or Ubuntu Touch changes; relocking with images the boot chain does not accept can brick the device.

## Stage E: no normal boot and no fastboot

If Qualcomm 9008 is still available:

1. Use the same previously verified Firehose and cable.
2. Into new create-if-absent paths, repeat the guide's `edl r gpt` primary reads and read current `param`; do not write first.
3. Compare all six `primary.lun0..5` files against the saved copies. The XML-only `edl gpt --genxml` output is not a binary GPT backup.
4. Run the offline `inspect` command on the new `param` read.
5. Preserve every failure message and hash locally.

Restoring the exact original `param` may repair a corrupted file-backed partition, but it still cannot revert an RPMB update. Do not flash a donor `param`, generic GPT, cross-SKU ABL, or a full Global package as an improvised recovery.

The final recovery option may be a model-matched Metro service/unbrick process or authorized repair. Such tooling can be Windows-only, may require a particular signed programmer, and may erase the phone. This repository neither supplies nor validates it, and a stock restore still does not prove that RPMB returned to its original state.

## Experimental `rollback-trigger` command

The CLI exposes `rollback-trigger` so researchers can build and inspect a Metro-target trigger **offline** from the original `metro-pristine` preimage. The generator has software tests for format, change scope, duplicate records, and encryption round trips.

It has **not** established that writing this image to hardware safely restores Metro RPMB state. Symmetric ABL behavior is an inference, and an interruption or different ABL policy could leave the phone in a worse state. Therefore:

- it is not part of the normal recovery procedure;
- its default dry-run does not authorize a device write;
- do not use it after an unknown or partially corrupted state;
- require a separate, explicit risk decision and a model-matched service recovery path before any hardware experiment.

Generating a dry-run report is non-destructive:

```bash
oneplus-n10-param rollback-trigger "$N10_PRIVATE_DIR/param.before.bin" \
  --soc-serial "$N10_SOC_SERIAL"
```

This documentation intentionally provides no routine EDL write command for the experimental rollback image.

## What recovery evidence cannot prove

- A matching pre-reset readback proves the UFS `param` write, not that ABL will accept it.
- A parsed post-ABL Global state supports trigger consumption, not long-term RPMB health.
- EDL availability proves a transport path, not that a programmer is safe for every partition.
- A successful stock boot does not prove all calibration, modem, or secure-firmware state is original.
- A successful bootloader unlock does not make Metro hardware officially supported by UBports.
