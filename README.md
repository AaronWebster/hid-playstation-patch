# hid-playstation patch: DualSense Edge back paddle + Fn buttons

## What this does

Patches the kernel `hid-playstation` driver to expose the 4 extra buttons on the
DualSense Edge controller (back paddles + front Fn buttons) as evdev events:

- `BTN_TRIGGER_HAPPY1` — Fn1 (left front button below left stick)
- `BTN_TRIGGER_HAPPY2` — Fn2 (right front button below right stick)
- `BTN_TRIGGER_HAPPY3` — Left rear paddle
- `BTN_TRIGGER_HAPPY4` — Right rear paddle

## Why needed

The upstream kernel `hid-playstation` driver (as of 6.12) parses only the 13
standard DualSense buttons and ignores the Edge's extra bytes. The extra buttons
are in `buttons[2]` (struct offset 9), bits 4-7. Note: the probe script
reports this as raw BT byte 11 because BT reports have a 2-byte header
before the struct data.

## Rebuild after kernel update

```bash
cd ~/hid-playstation-patch
make clean
make
sudo mkdir -p /lib/modules/$(uname -r)/updates/
sudo cp hid-playstation.ko /lib/modules/$(uname -r)/updates/
sudo depmod -a
sudo rmmod hid_playstation && sudo modprobe hid_playstation
```

## Files changed vs upstream hid-playstation.c

1. Added `DS_EDGE_BUTTONS_*` bit defines for buttons[2] bits 4-7
2. Added `bool is_edge` to `struct dualsense`
3. Set `ds->is_edge = true` in `dualsense_create()` for product 0x0df2
4. Register `BTN_TRIGGER_HAPPY1-4` capabilities when `is_edge`
5. Parse those buttons in `dualsense_parse_report()` when `is_edge`
