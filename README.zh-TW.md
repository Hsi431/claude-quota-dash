# Claude 額度儀表板

[English](README.md)

桌上一塊 LilyGO T-Display-S3,顯示 Claude Code 的額度還剩多少。

![額度頁](docs/images/page1-quota.png)

所有工作都在電腦這端:讀 `~/.claude/usage-now.json` 與 `usage-history.jsonl`,
用 Pillow 把每一個像素畫出來,只把有變動的矩形轉成 RGB565 從 USB 序列埠推過去。
韌體刻意做得很笨,只負責收矩形貼上去,所以**改版面是存檔,不是重燒板子**。

## 四個頁面

左鍵上一頁,右鍵下一頁。

| | |
|---|---|
| `QUOTA` — 兩個額度一眼看完,以及各自何時重置 | `5 HOUR` — 倒數、長條,與這個視窗的燒盡曲線 |
| ![](docs/images/page1-quota.png) | ![](docs/images/page2-five-hour.png) |
| `CONTEXT` — context 用掉多少,含 200K 標記 | `CACHE` — 命中率、冷掉要重建多少、花費 |
| ![](docs/images/page3-context.png) | ![](docs/images/page4-cache.png) |

全台一套顏色:60% 以下白、61–90% 橘、91% 以上暗紅。這裡**沒有**「你現在應該用到哪」
的等速參考線 —— 5 小時視窗本來就會自己補滿,而 7 天那條只要你認真工作就會整週恆橘,
等於沒有資訊。

小字一律關抗鋸齒,因為在這種像素密度下,灰色的邊緣像素會佔掉大半個字;
只有兩種大字保留抗鋸齒。

## 資料是哪來的(最容易漏掉的一步)

Claude Code 自己不會寫那兩個檔。狀態列 hook 是唯一觸發夠頻繁的地方,所以
`install/statusline-sampler.sh` 會在每次刷新時記下完整 payload,並且**最多每 30 秒**
往歷史檔追加一行。**少了這一步,儀表板會永遠停在 NO DATA**,而且症狀不明顯、很難查。

在 `~/.claude/settings.json` 裡:

```json
"statusLine": {"type": "command", "command": "~/claude-quota-dash/install/statusline-sampler.sh"}
```

已經有自己的狀態列?那就留著,把那支腳本裡 `RECORD` 兩個標記中間那段貼到你自己的最前面。
它需要 `jq`、靠歷史檔本身的 mtime 節流、而且每一步都容許靜默失敗 ——
因為這段跑在你每一次操作的狀態列上,絕對不能拖慢你。

曲線能畫多長,取決於歷史檔累積了多少行,所以第一天會很稀疏。

## 安裝

硬體:一塊 LilyGO T-Display-S3(320x170,不帶觸控的那款),以及一條**能傳資料**的 USB-C 線。

```bash
sudo apt install fonts-jetbrains-mono jq          # 版面是照這個字型量出來的
python3 -m pip install --user pyserial numpy Pillow
pio run -d firmware -t upload                     # PlatformIO,燒一次就好
mkdir -p ~/.config/systemd/user
cp install/quota-dash.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now quota-dash.service
```

然後照上面設好狀態列,等一分鐘讓它收到第一筆資料。

**插了不只一塊 ESP32?** 所有走原生 USB-JTAG 的板子 VID:PID 都是 `303a:1001`,
分不出來,只有 `/dev/serial/by-id` 路徑裡的 MAC 不一樣。只插一塊時程式會自動找到;
插兩塊時它不會亂猜,會把找到的都列出來,由你指定是哪一塊:

```ini
# ~/.config/systemd/user/quota-dash.service.d/port.conf
[Service]
Environment=QUOTA_DASH_PORT=/dev/serial/by-id/usb-Espressif_USB_JTAG_serial_debug_unit_AA:BB:...-if00
```

## 操作

    quota page 1-4      跳到某一頁
    quota next / prev   跟實體按鍵一樣
    quota bri 0-255     背光
    quota crab on/off   螃蟹,見下面
    quota lang en/zh    介面語言,見下面
    quota status        目前的頁面、背光、螃蟹狀態、語言

主機掛掉時,韌體會在 30 秒沒收到畫面後把背光降到 10%。**這是刻意的**:
留在螢幕上的是過期數字,而亮著的過期數字會騙人。看到螢幕變暗,先查
`systemctl --user status quota-dash`。

## 中文介面

![中文版的五小時頁](docs/images/page2-five-hour-zh.png)

`quota lang zh` 把標籤換成中文,`quota lang en` 換回英文,設定重開機還在
(就是 `~/.config/quota-dash/lang` 這個檔)。數字、時間、單位和模型名維持原樣 ——
那些兩種語言讀起來一樣,而同一行混兩套字型付出的比拿到的多。

同樣的字級,中文要的像素比英文多:11px 的標籤在 1.9 吋螢幕上就是一團墨。
所以標籤放大到 16px,並且保留抗鋸齒(英文小字反而要關掉),
而多出來的高度總得有地方來,原本三處「標籤在上、值在下」的堆疊就改成同一行。
這需要 Noto Sans CJK 字型(Debian/Ubuntu:`apt install fonts-noto-cjk`)。

## 螃蟹

![開了螃蟹的額度頁](docs/images/page1-quota-crab.png)

`quota crab on` 會把數字旁邊那根長條換成一隻螃蟹,牠的姿態跟著 7 天額度走:
還有餘裕時舉著螯站直,一週燒下去就慢慢垮,快用完時整隻趴在沙上。牠會呼吸、眨眼、東張西望。
這個設定會留著,重開機也還在(就是 `~/.config/quota-dash/crab` 這個檔)。

**預設是關的。** 因為牠是對 Clawd 的致敬 —— Clawd 是 Anthropic(做 Claude 的公司)的螃蟹吉祥物。
這裡的像素是我為這塊螢幕自己畫的,但角色是他們的。本專案與 Anthropic 無關,也未獲其背書。

## 想再深入

`docs/PROTOCOL.md` 是主機跟板子之間的通訊格式。
`reference/tdisplay-s3-facts.md` 是腳位表與面板的各種坑,全部對著實機驗過 ——
要移植到別的面板的話從這裡開始看,特別是 `TFT_INVERSION_ON` 跟位元組序那幾段。

`python3 test_data.py` 蓋解析那一層;`python3 preview.py 輸出目錄` 會用合成資料把每一頁畫出來,
桌上沒有板子也能檢查版面改動。

## 授權

MIT,見 `LICENSE`。
