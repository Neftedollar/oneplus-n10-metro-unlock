# OnePlus Nord N10 5G Metro BE2025: подготовка обычной разблокировки bootloader

После этого руководства у вас будет не «готовый разблокированный образ», а проверенный одноразовый `param`-триггер для перехода software project из Metro 20885 в Global 20886. Саму разблокировку выполняет штатный интерактивный механизм bootloader.

> [!DANGER]
> Процедура стирает пользовательские данные при разблокировке и может лишить телефон возможности нормально загружаться. После запуска ABL изменяется RPMB; обычный файл `param.before.bin` не является резервной копией RPMB и не гарантирует откат.

## 1. Граница применимости

Это руководство относится **только** к проверенной комбинации:

- OnePlus Nord N10 5G Metro;
- маркировка устройства BE2025;
- исходный software project 20885 (`0x3A403A71`);
- проверенный исходный `param` в состоянии `metro-pristine`;
- целевой Global software project 20886 (`0xB8BD9E39`).

BE2025 — это маркировка (marketing model) телефона. `20885` — исходный Metro
**software project code**, а не название модели. В CLI bkerler/edl
соответствующий параметр исторически называется `--devicemodel`; для этого
проверенного пути во всех EDL-командах ниже указывается именно
`--devicemodel=20885`. Сохраняйте исходное значение `20885` при чтении,
записи, readback и reset: не подставляйте `BE2025`, целевой `20886` или код
другого SKU.

Остановитесь, если хотя бы один пункт не подтверждён. Старые инструкции и скрипты для BE2028/T-Mobile относятся к другому SKU и не являются источником допустимых ключей, serial или образов для этой процедуры. Не переносите из них значения и не пробуйте «похожий» режим.

Этот проект не выполняет SIM-unlock, не меняет IMEI, не конвертирует весь firmware, не открывает critical partitions и не устанавливает Ubuntu Touch.

## 2. Что подтверждено, а что является выводом

### Подтверждено на одном физическом BE2025

- Исходный `param` имел размер ровно 1 МиБ.
- Основная и резервная зашифрованные записи SWID по смещениям `0x4F000` и `0xCF000` совпадали и проходили структурную и криптографическую проверку.
- Offline-патч менял только разрешённые поля внутри этих двух записей.
- Прочитанный через EDL образ до перезагрузки побайтно совпал с созданным trigger-образом.
- После выполнения ABL изменил `param`, а обычная интерактивная команда unlock сработала без OnePlus unlock-token image.
- Разблокировка вызвала штатный factory reset.

### Вывод по reverse engineering

По управляющему потоку ABL, его диагностическим строкам и наблюдаемому состоянию триггер заставляет ABL записать целевой SWID в RPMB, после чего ABL очищает trigger-флаг. Это сильное подтверждение механизма, но не документация OnePlus.

### Не подтверждено

- Совместимость с другим экземпляром BE2025, другой версией ABL или другим SKU.
- Безопасность повторного применения.
- Аппаратный откат RPMB обратно на Metro.
- Официальная поддержка результата OnePlus, Metro, T-Mobile или UBports.

## 3. Предварительные условия

Перед началом вам нужны:

- законно принадлежащий вам BE2025, с которого вы можете удалить все данные;
- отдельная пользовательская резервная копия фото, сообщений, ключей 2FA и других данных из Android;
- стабильный USB-кабель без хаба и достаточно заряженная батарея;
- воспроизводимый вход в Qualcomm EDL 9008 и выход из него;
- совместимый с этим устройством, легально полученный и подписанный производителем Firehose programmer;
- macOS или Linux с Python 3.11+, `adb`, `fastboot`, Git и `libusb`;
- локальная установка [bkerler/edl](https://github.com/bkerler/edl);
- включённый в Android параметр **OEM unlocking**, если исходная система позволяет его включить.

Репозиторий намеренно не содержит Firehose, OPS/MSM-пакетов, firmware, дампов или идентификаторов устройства. Случайный Firehose из интернета может отказать либо повредить разметку.

### macOS, включая Apple Silicon

Из корня этого репозитория установите системные зависимости и задайте
абсолютный каталог EDL **вне** клона. Закреплённый commit — тот, на котором
проверены команды и поведение этой инструкции; обновление требует повторного
аудита:

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

Проверьте только чтение:

```bash
"$N10_EDL" --help
fastboot --version
```

Не считайте успешный запуск CLI подтверждением совместимости Firehose. Совместимость подтверждает только корректное чтение GPT и повторяемый readback без ошибок Firehose.

## 4. Подготовьте закрытый каталог резервных копий

Из корня клона задайте **новый абсолютный** путь вне git-репозитория. Не
заменяйте его относительным `local-backup`. Путь не должен существовать заранее:
это не позволяет случайно переиспользовать старый/слабозащищённый каталог или
изменить права широкой директории. Блок создаёт его с `0700` и останавливается,
если путь пересекается с клоном или является symlink:

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

Не продолжайте, если последняя строка не равна
`private_backup_dir_ok=yes`. `umask 077` должен оставаться активным в терминале
со всеми следующими EDL-командами.

Никогда не публикуйте `param`, `devinfo`, `config`, `persist`, modem/EFS-разделы, GPT, SoC serial, IMEI, PCBA, Firehose или полный EDL-лог. Храните исходный `param` неизменным и минимум в двух физических местах.

## 5. Привяжите операции к единственному EDL-устройству и сохраните разметку

Отключите все остальные телефоны и устройства в service/download mode, затем
переведите целевой телефон в EDL. Проверенный transport — Qualcomm
`05c6:9008`. В закреплённой версии bkerler/edl USB-клиент выбирает первое
совпадение, а команда `w` не умеет привязаться к ожидаемому SoC serial.
Поэтому единственная безопасная привязка здесь — физически оставить ровно один
такой USB-девайс и проверять это непосредственно перед каждой EDL-командой.

Определите fail-closed guard в том же терминале, где установлен EDL:

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

Во всех примерах замените путь к programmer на свой локальный абсолютный путь.
Первая read-only проверка:

```bash
require_single_9008 && "$N10_EDL" printgpt --vid=0x05c6 --pid=0x9008 \
  --devicemodel=20885 --memory=ufs \
  --loader=/ABSOLUTE/PATH/TO/MATCHING_FIREHOSE
```

Вывод должен показывать UFS-разметку, шесть LUN `0..5` и единственный ожидаемый
раздел `param`. Sahara печатает `Serial: 0x...`: это 32-битный **SoC serial**,
а не IMEI, Android serial или PCBA. Запишите его локально и задайте для
offline-проверок:

```bash
export N10_SOC_SERIAL="0xREPLACE_WITH_THE_RECORDED_SOC_SERIAL"
```

Каждый последующий EDL-запуск должен показывать то же значение. При отсутствии
или несовпадении serial остановитесь. Не публикуйте его и помните, что значение
в аргументе CLI видно в shell history и локальном списке процессов.

Создайте новый каталог и сохраните реальные первые 32 сектора GPT каждого LUN:

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

Отдельно создайте XML-карту и потребуйте шесть непустых файлов:

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

Важно: в закреплённом upstream обработчик `edl gpt` пишет XML, но его запись
`gpt_main*.bin`/`gpt_backup*.bin` закомментирована, хотя CLI печатает
`Dumped GPT`. Не считайте эти строки доказательством бинарного backup и не
используйте созданный XML как QFIL-программу. Реальные primary-GPT файлы выше
созданы именно командой `edl r gpt`.

Если LUN не шесть, имя `param` неоднозначно, serial изменился, автоматическое
определение LUN ошибается или Firehose сообщает ошибку, остановитесь. Не
подбирайте LUN записью.

## 6. Сделайте обязательные резервные копии

Сначала прочитайте `param` дважды в разные файлы:

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

`cmp` не должен вывести ничего и должен завершиться с кодом 0. Размер каждого файла должен быть 1,048,576 байт.

Также сохраните, если эти имена присутствуют в вашей GPT:

| Приоритет | Разделы | Зачем |
| --- | --- | --- |
| Обязательно | `param`, primary-GPT read и XML каждого UFS LUN | Единственный записываемый раздел и проверяемая карта восстановления |
| Настоятельно рекомендуется | `devinfo`, `config`, `abl_a`, `abl_b` | Состояние unlock/модели и ABL, который обрабатывает trigger |
| Настоятельно рекомендуется | `fsc`, `fsg`, `modemst1`, `modemst2` | Персональные modem/EFS-данные |
| Настоятельно рекомендуется | `persist` | Калибровки камер/датчиков и WLAN-данные |

Читайте каждый раздел командой вида:

```bash
test ! -e "$N10_PRIVATE_DIR/PARTITION.before.bin" || exit 1
require_single_9008 && "$N10_EDL" r PARTITION "$N10_PRIVATE_DIR/PARTITION.before.bin" \
  --vid=0x05c6 --pid=0x9008 --devicemodel=20885 --memory=ufs \
  --loader=/ABSOLUTE/PATH/TO/MATCHING_FIREHOSE
chmod 400 "$N10_PRIVATE_DIR/PARTITION.before.bin"
```

Подставляйте только имя из вашей GPT. Репозиторий не предполагает конкретный номер LUN.

## 7. Установите и проверьте offline-патчер

В корне этого проекта создайте отдельное окружение:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
oneplus-n10-param --help
```

Инструмент не имеет USB/EDL-кода и не обращается к телефону. Он всегда читает обычный файл; без `--output` patch-команды выполняют только dry-run.

Проверьте исходный образ, подставив локальный SoC serial:

```bash
oneplus-n10-param inspect "$N10_PRIVATE_DIR/param.before.bin" \
  --soc-serial "$N10_SOC_SERIAL"
```

Продолжайте только при одновременном выполнении условий:

- `size=1048576`;
- `state=metro-pristine`;
- `duplicates_match=True`;
- обе записи имеют одинаковые counter, `swid=0x3A403A71` и `proc=0x00000000`.

Ошибка `inner MD5 mismatch` обычно означает неверный SoC serial либо несовместимый/повреждённый образ. Не пробуйте чужой serial или «статический ключ» из другого writeup.

## 8. Создайте Global trigger offline

Сначала dry-run:

```bash
oneplus-n10-param patch-global "$N10_PRIVATE_DIR/param.before.bin" \
  --soc-serial "$N10_SOC_SERIAL"
```

Отчёт должен показать `dry_run=True`, `output_state=global-trigger`, target SWID `0xB8BD9E39`, а также только два допустимых диапазона изменений. После проверки создайте новый файл:

```bash
oneplus-n10-param patch-global "$N10_PRIVATE_DIR/param.before.bin" \
  --soc-serial "$N10_SOC_SERIAL" \
  --output "$N10_PRIVATE_DIR/param.global-trigger.bin"
```

Не используйте `--overwrite` в первом проходе. Инструмент специально запрещает изменение input in place.

Повторно проверьте созданный файл:

```bash
oneplus-n10-param inspect "$N10_PRIVATE_DIR/param.global-trigger.bin" \
  --soc-serial "$N10_SOC_SERIAL"

shasum -a 256 \
  "$N10_PRIVATE_DIR/param.before.bin" \
  "$N10_PRIVATE_DIR/param.global-trigger.bin"
```

## 9. Единственная запись в EDL

До этой точки телефон не изменялся. Следующая команда — опасная граница.

Убедитесь, что:

- исходный и trigger-образы по-прежнему проходят `inspect`;
- у вас есть две совпадающие копии исходного `param`;
- Firehose уже успешно читал этот же `param`;
- подключён ровно один `05c6:9008`, а последний EDL-вывод показывает записанный ранее SoC serial;
- вы прочитали [recovery.md](recovery.md);
- вы готовы потерять все пользовательские данные и допускаете отсутствие рабочего RPMB-отката.

Запишите только `param`:

```bash
require_single_9008 && "$N10_EDL" printgpt --vid=0x05c6 --pid=0x9008 \
  --devicemodel=20885 --memory=ufs \
  --loader=/ABSOLUTE/PATH/TO/MATCHING_FIREHOSE
```

Ещё раз вручную сверьте `Serial: 0x...` с `N10_SOC_SERIAL`. Если строка
отсутствует или значение отличается, **не записывайте**. Только затем:

```bash
require_single_9008 && "$N10_EDL" w param "$N10_PRIVATE_DIR/param.global-trigger.bin" \
  --vid=0x05c6 --pid=0x9008 --devicemodel=20885 --memory=ufs \
  --loader=/ABSOLUTE/PATH/TO/MATCHING_FIREHOSE
```

Не выполняйте reset и не отключайте питание, пока не завершён readback.

## 10. Обязательный readback до первого reset

Прочитайте записанный раздел в новый файл:

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

Должно быть одновременно верно:

- `cmp` завершился с кодом 0 и ничего не вывел;
- SHA-256 обоих файлов совпадает;
- `inspect` readback-файла сообщает `global-trigger`.

При любом несовпадении **не запускайте ABL**. Следуйте сценарию «до первого reset» в [recovery.md](recovery.md).

## 11. Запустите ABL один раз

Только после успешного readback:

```bash
require_single_9008 && "$N10_EDL" reset --resetmode=reset \
  --vid=0x05c6 --pid=0x9008 --devicemodel=20885 \
  --loader=/ABSOLUTE/PATH/TO/MATCHING_FIREHOSE
```

Если reset не выводит устройство из EDL, используйте известную для вашего телефона физическую комбинацию питания. Важно, чтобы ABL выполнился; именно он должен обработать trigger и изменить RPMB.

Не прошивайте trigger повторно «для надёжности». После запуска ABL pre-reset образ уже не является текущим состоянием телефона.

## 12. Выполните штатную разблокировку

Перейдите в fastboot и убедитесь, что виден ровно один ожидаемый телефон:

```bash
fastboot devices
fastboot getvar unlocked
```

Запустите обычную интерактивную разблокировку:

```bash
fastboot flashing unlock
```

Подтвердите действие кнопками **на самом телефоне**. Bootloader должен стереть userdata; это ожидаемо. Не отключайте USB и питание во время wipe/reboot.

После завершения снова войдите в fastboot и проверьте:

```bash
fastboot getvar unlocked
```

Успех — только ответ `unlocked: yes`. Оранжевое предупреждение Verified Boot после unlock является ожидаемым.

Если снова появляется требование OnePlus unlock token, не повторяйте запись. Сохраните точный текст ошибки и переходите к [recovery.md](recovery.md).

## 13. Ubuntu Touch — отдельная и неподдерживаемая процедура

Этот проект заканчивается на `unlocked: yes`. **Не запускайте штатный UBports
Installer на конвертированном BE2025 как есть.** Точная закреплённая
[installer-конфигурация billie](https://github.com/ubports/installer-configs/blob/f441524a202cd717c2da11d6e9549f7a76febc2d/v2/devices/billie.yml#L103-L135)
загружает и прошивает `persist.img` при bootstrap. Это может заменить
уникальный Metro `persist` с калибровками cross-SKU образом.

Материалы, определяющие официальную границу поддержки:

- [официальная страница OnePlus Nord N10 5G](https://devices.ubuntu-touch.io/device/billie/);
- [community-port source](https://gitlab.com/ubports/porting/community-ports/android10/oneplus-nord-n10/oneplus-billie/-/blob/816b30257cee2ab30504cf492f4fd4ae501ff843/README.md).

На 2026-08-11 официальный путь требует EU или Global OxygenOS 10.5.7, а port
README относит US Metro/T-Mobile firmware к неподдерживаемым. Успешное
изменение SWID и unlock не превращают BE2025 в официально поддерживаемый SKU.
Этот репозиторий не публикует и не подтверждает безопасный путь установки
Ubuntu Touch: сохраните Metro `persist` и остановитесь на `unlocked: yes`.

## 14. Атрибуция

Понимание зашифрованной структуры `param` основано, в частности, на GPL-коде
B. Kerler: [bkerler/edl](https://github.com/bkerler/edl) и
[`oneplus_param.py`](https://github.com/bkerler/edl/blob/e4266d278728660a79f170d498dab3bb8ed641b1/edlclient/Library/Modules/oneplus_param.py).
BE2025-реализация намеренно хэширует ASCII-строку, восстановленную проверенным
ABL, и отличается от hex-decoded construction в upstream-модуле. Проект не
включает код EDL, vendor Firehose или проприетарные firmware-образы.

Лицензия проекта: [GPL-3.0-or-later](../LICENSE).
