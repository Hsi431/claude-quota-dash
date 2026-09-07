# LilyGO T-Display-S3 — verified hardware facts

Source: `espressif/arduino-esp32` `variants/lilygo_t_display_s3/pins_arduino.h`
(fetched 2026-09-07). Board on this desk verified by esptool:
ESP32-S3 (QFN56) rev v0.2, embedded PSRAM 8MB, flash 16MB (ef:4018),
USB-Serial/JTAG, MAC `ec:da:3b:9d:77:38`, enumerates as `/dev/ttyACM1`
(`/dev/serial/by-id/usb-Espressif_USB_JTAG_serial_debug_unit_EC:DA:3B:9D:77:38-if00`).

## Display
ST7789 IPS TFT, **170 x 320** native (portrait), 8-bit **i80 parallel** bus.

| Signal | GPIO |
|---|---|
| LCD_D0..D7 | 39, 40, 41, 42, 45, 46, 47, 48 |
| LCD_WR | 8 |
| LCD_RD | 9 |
| LCD_DC | 7 |
| LCD_CS | 6 |
| LCD_RES | 5 |
| LCD_BL (backlight) | 38 |
| LCD_POWER_ON | 15 |

⚠️ **GPIO 15 must be driven HIGH before anything on the panel works.** It gates
the LDO that powers the display. Forget it and the board looks dead.

⚠️ **The panel is an inverted IPS part: `TFT_INVERSION_ON` is mandatory.**
Without it every colour comes out complemented -- a near-black page renders as a
white page with dark text, which reads as "washed out / blurry" rather than as an
obvious colour fault. Verified on this board 2026-09-07.

⚠️ **Do not convert the received pixels to native uint16 before `pushImage`.**
The wire format is plain big-endian RGB565 and the panel wants exactly those
bytes; `pushImage` writes a native uint16 low byte first, so a "helpful"
conversion in the firmware produces a second swap. Solid colours still look
plausible when this is wrong -- they just come out as a different colour -- so
the tell is **coloured fringing on anti-aliased text**, which is the only place
adjacent pixels differ. Diagnosed 2026-09-07.

⚠️ Omitting `TFT_RGB_ORDER` is not neutral: `ST7789_Defines.h` falls back to
**BGR** whenever `CGRAM_OFFSET` is defined, which is a different wrong answer.

⚠️ The ST7789 controller is a 240x320 part; the glass is 170 wide. A **column
offset of 35** ((240-170)/2) is required or everything is shifted. TFT_eSPI's
`Setup206_LilyGo_T_Display_S3` handles this — use it rather than hand-rolling.

## Other pins
| Signal | GPIO |
|---|---|
| BUTTON_1 (also BOOT) | 0 |
| BUTTON_2 | 14 |
| BAT_VOLT (ADC) | 4 |
| I2C SDA / SCL | 18 / 17 |
| TP_RESET / TP_INIT (touch variant only) | 21 / 16 |
| UART TX / RX | 43 / 44 |

## USB
VID 0x303a, PID 0x1001 — **identical to the ESP32-C3 puck** on this desk.
The only thing distinguishing the two by-id paths is the MAC. Never pick a
port with `sorted(glob(...))[0]`.
