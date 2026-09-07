# Claude quota dashboard

The host reads `~/.claude/usage-now.json` and `usage-history.jsonl`, renders all
pixels with Pillow, converts changed rectangles to RGB565, and sends them to a
LilyGO T-Display-S3. The firmware is intentionally a dumb rectangle receiver.

Four pages: `QUOTA` (both quotas at a glance, when each clears, and a crab that
breathes), `5 HOUR` (countdown, bar, and the burn curve for the current window),
`CONTEXT` (context used against the window, with the 200K mark, plus model and
mode), and `CACHE` (hit rate, what a cold rebuild would cost, last miss, spend).
Button 1 goes back a page, Button 2 forward. Backlight is `quota bri 0-255`.

The crab in `crab.py` is drawn here, not borrowed. Its posture follows the
seven-day quota -- claws up while there is room, hanging as the week burns down,
flat on the sand near the end -- so the column beside the numbers says something
the numbers do not.

Small text is drawn without anti-aliasing -- at this pixel pitch the grey edge
pixels are most of a glyph -- while the two large sizes keep it.

Install from this directory:

    python3 -m pip install --user pyserial numpy Pillow
    mkdir -p ~/.config/systemd/user
    cp install/quota-dash.service ~/.config/systemd/user/
    systemctl --user daemon-reload
    systemctl --user enable --now quota-dash.service

Build the firmware with `pio run -d firmware`. Generate synthetic visual checks
with `python3 preview.py /tmp/quota_preview`.
