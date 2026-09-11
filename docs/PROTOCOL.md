# Serial protocol

Newline-terminated ASCII commands at 115200 on the board's native USB CDC.
`RECT` is followed immediately by a fixed-size raw binary payload.

| Command | Payload | Reply |
|---|---|---|
| `PING` | — | `PONG 1 tdisplay up=<ms> rects=<n> fails=<n> lastrect=<ms> heap=<bytes> psram=<bytes> psramblock=<bytes>` |
| `RECT <x> <y> <w> <h>` | `w*h*2` bytes, big-endian RGB565 | `OK` |
| `BRI <0-255>` | — | `OK` |
| `CLR` | — | `OK` |

The `PONG` fields are the board's own account of itself: uptime, how many
rectangles it has pushed and how many it failed, how long the last push took,
and the memory it has left. They are there to be compared against the values
from a known-good moment, which is why a host should log one `PING` at startup.

Payload reads time out after 2000 ms. Whatever arrives after that is pixels
rather than a command, so the board drops it and says how much it threw away:
`ERR timeout got <n> of <want> dropped <n>`. Dropping it matters — parsed as
text, a late payload skews every reply after it. Payloads are sent by the host
in chunks of 4096 bytes or smaller. Rectangle coordinates are in the 320x170
landscape framebuffer. Invalid rectangles return `ERR bad-rect` without writing
pixels; an allocation failure returns
`ERR no-memory want <n> psram <n> block <n> heap <n>`.

The board may emit `BTN 1`, `BTN 2` or `BOOT ...` asynchronously. Hosts must
keep these separate from command replies. `BOOT 1 tdisplay reset=<reason>
heap=<bytes> psram=<bytes>` is printed at the end of `setup()`, where `reason`
is `esp_reset_reason()`. Opening the port resets the board, so a host always
sees one `BOOT` on connect; a second one mid-session means the board restarted
underneath it.

## Replies are not guaranteed

On the ESP32-S3's native USB-Serial-JTAG a reply can arrive long after the host
has given up on it, or never arrive at all, while the board itself is perfectly
healthy — it reports the push finished in ~74 ms with no failures, an uptime
that never restarted, and memory that has not moved. Measured here: roughly one
in every ten to twenty thousand rectangles. Flushing on the board does not help;
what is already in the USB FIFO still waits for the host to write something.

So a host must not treat a timeout as a dead board:

- Write something — a `PING` will do. That nudges a late reply out. A line that
  comes back that is not the `PONG` is the missing reply.
- If nothing comes back but a fresh `PING` is answered at once, the reply was
  lost rather than late. `RECT`, `BRI` and `CLR` are all idempotent, so send the
  command again.
- Only a board that answers neither is actually gone.

Swallow the `PONG` you provoked before running the next command, or it turns up
as the answer to that one.
