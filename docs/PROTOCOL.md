# Serial protocol

Newline-terminated ASCII commands at 115200 on the board's native USB CDC.
`RECT` is followed immediately by a fixed-size raw binary payload.

| Command | Payload | Reply |
|---|---|---|
| `PING` | — | `PONG 1 tdisplay` |
| `RECT <x> <y> <w> <h>` | `w*h*2` bytes, big-endian RGB565 | `OK` |
| `BRI <0-255>` | — | `OK` |
| `CLR` | — | `OK` |

Payload reads time out after 2000 ms and reply `ERR timeout got <n> of <want>`.
Payloads are sent by the host in chunks of 4096 bytes or smaller. Rectangle
coordinates are in the 320x170 landscape framebuffer. Invalid rectangles return
`ERR bad-rect` without writing pixels.

The board may emit `BTN 1` or `BTN 2` asynchronously. Hosts must keep button
events separate from command replies.
