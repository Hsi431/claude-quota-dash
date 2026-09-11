#include <Arduino.h>
#include <TFT_eSPI.h>

#include <esp_heap_caps.h>
#include <esp_system.h>
#include <stdlib.h>

#define PROTO_VERSION 1
#define SCREEN_WIDTH 320
#define SCREEN_HEIGHT 170
#define LCD_POWER_ON 15
#define LCD_BACKLIGHT 38
#define BUTTON_1 0
#define BUTTON_2 14
#define BACKLIGHT_CHANNEL 0
#define BACKLIGHT_FREQ 5000
#define BACKLIGHT_BITS 8
#define PAYLOAD_TIMEOUT_MS 2000
#define FAILSAFE_MS 30000

TFT_eSPI tft = TFT_eSPI();

static String line;
static uint8_t brightness = 255;
static bool failsafeDimmed = false;
static uint32_t lastRectAt = 0;
// Diagnostics (2026-09-11): the host sees only silence when a RECT is lost, so
// the board has to say for itself how long its last push took and how much
// memory it had left when it did.
static uint32_t lastRectMs = 0;
static uint32_t rectCount = 0;
static uint32_t rectFailures = 0;
static int lastButton1 = HIGH;
static int stableButton1 = HIGH;
static uint32_t button1ChangedAt = 0;
static int lastButton2 = HIGH;
static int stableButton2 = HIGH;
static uint32_t button2ChangedAt = 0;

static void applyBrightness() {
  ledcWrite(BACKLIGHT_CHANNEL, failsafeDimmed ? 26 : brightness);
}

static bool readPayload(uint8_t *dst, size_t want) {
  size_t got = 0;
  uint32_t deadline = millis() + PAYLOAD_TIMEOUT_MS;
  while (got < want) {
    int available = Serial.available();
    if (available > 0) {
      size_t ask = min((size_t)available, want - got);
      size_t n = Serial.readBytes(dst + got, ask);
      if (n > 0) {
        got += n;
        deadline = millis() + PAYLOAD_TIMEOUT_MS;
      }
    } else if ((int32_t)(millis() - deadline) >= 0) {
      // Whatever arrives late is pixels, not a command. Drop it here or the
      // reader below parses it as text and every reply after this is skewed.
      uint32_t drainUntil = millis() + 250;
      size_t dropped = 0;
      while ((int32_t)(millis() - drainUntil) < 0) {
        while (Serial.available()) {
          Serial.read();
          dropped++;
          drainUntil = millis() + 250;
        }
        yield();
      }
      Serial.printf("ERR timeout got %u of %u dropped %u\n",
                    (unsigned)got, (unsigned)want, (unsigned)dropped);
      return false;
    }
    yield();
  }
  return true;
}

static bool parseByte(const String &value, int &result) {
  if (!value.length()) return false;
  for (size_t i = 0; i < value.length(); i++) {
    if (value[i] < '0' || value[i] > '9') return false;
  }
  result = value.toInt();
  return result >= 0 && result <= 255;
}

static void handleRect(const String &command) {
  int x, y, w, h;
  char extra;
  if (sscanf(command.c_str(), "RECT %d %d %d %d %c", &x, &y, &w, &h, &extra) != 4 ||
      w <= 0 || h <= 0 || x < 0 || y < 0 || x + w > SCREEN_WIDTH || y + h > SCREEN_HEIGHT) {
    Serial.println("ERR bad-rect");
    return;
  }

  size_t pixelsCount = (size_t)w * h;
  size_t bytes = pixelsCount * 2;
  uint16_t *pixels = (uint16_t *)ps_malloc(bytes);
  if (!pixels) pixels = (uint16_t *)malloc(bytes);
  if (!pixels) {
    Serial.printf("ERR no-memory want %u psram %lu block %u heap %lu\n",
                  (unsigned)bytes, (unsigned long)ESP.getFreePsram(),
                  (unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_SPIRAM),
                  (unsigned long)ESP.getFreeHeap());
    rectFailures++;
    return;
  }
  uint32_t startedAt = millis();
  if (readPayload((uint8_t *)pixels, bytes)) {
    // The payload is already in the order the panel wants, byte for byte.
    // Converting it to native uint16 here only earns a second swap inside
    // pushImage, which lands every pixel half a pixel out and fringes edges.
    tft.pushImage(x, y, w, h, pixels);
    lastRectAt = millis();
    lastRectMs = lastRectAt - startedAt;
    rectCount++;
    if (failsafeDimmed) {
      failsafeDimmed = false;
      applyBrightness();
    }
    Serial.println("OK");
  } else {
    rectFailures++;
  }
  free(pixels);
}

static void handle(const String &command) {
  if (command == "PING") {
    Serial.printf("PONG %d tdisplay up=%lu rects=%lu fails=%lu lastrect=%lums "
                  "heap=%lu psram=%lu psramblock=%u\n",
                  PROTO_VERSION, (unsigned long)millis(), (unsigned long)rectCount,
                  (unsigned long)rectFailures, (unsigned long)lastRectMs,
                  (unsigned long)ESP.getFreeHeap(), (unsigned long)ESP.getFreePsram(),
                  (unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_SPIRAM));
  } else if (command.startsWith("RECT ")) {
    handleRect(command);
  } else if (command.startsWith("BRI ")) {
    int value;
    if (!parseByte(command.substring(4), value)) {
      Serial.println("ERR bad-bri");
    } else {
      brightness = (uint8_t)value;
      applyBrightness();
      Serial.println("OK");
    }
  } else if (command == "CLR") {
    tft.fillScreen(TFT_BLACK);
    Serial.println("OK");
  } else if (command.length()) {
    Serial.printf("ERR unknown %s\n", command.c_str());
  }
}

static void pollButton(uint8_t pin, int id, int &lastRaw, int &stable, uint32_t &changedAt) {
  int raw = digitalRead(pin);
  if (raw != lastRaw) {
    lastRaw = raw;
    changedAt = millis();
  }
  if (raw != stable && millis() - changedAt >= 30) {
    int previous = stable;
    stable = raw;
    if (previous == HIGH && stable == LOW) Serial.printf("BTN %d\n", id);
  }
}

void setup() {
  pinMode(LCD_POWER_ON, OUTPUT);
  digitalWrite(LCD_POWER_ON, HIGH);
  pinMode(BUTTON_1, INPUT_PULLUP);
  pinMode(BUTTON_2, INPUT_PULLUP);
  lastButton1 = stableButton1 = digitalRead(BUTTON_1);
  lastButton2 = stableButton2 = digitalRead(BUTTON_2);
  button1ChangedAt = button2ChangedAt = millis();

  ledcSetup(BACKLIGHT_CHANNEL, BACKLIGHT_FREQ, BACKLIGHT_BITS);
  ledcAttachPin(LCD_BACKLIGHT, BACKLIGHT_CHANNEL);
  applyBrightness();

  tft.init();
  tft.setRotation(1);
  tft.fillScreen(TFT_BLACK);

  Serial.setRxBufferSize(4096);
  Serial.begin(115200);
  Serial.setTimeout(PAYLOAD_TIMEOUT_MS);
  lastRectAt = millis();
  // A silent RECT and a board that rebooted mid-RECT look identical from the
  // host. This line is how the host tells them apart.
  delay(50);
  Serial.printf("BOOT %d tdisplay reset=%d heap=%lu psram=%lu\n",
                PROTO_VERSION, (int)esp_reset_reason(),
                (unsigned long)ESP.getFreeHeap(), (unsigned long)ESP.getFreePsram());
}

void loop() {
  pollButton(BUTTON_1, 1, lastButton1, stableButton1, button1ChangedAt);
  pollButton(BUTTON_2, 2, lastButton2, stableButton2, button2ChangedAt);
  if (!failsafeDimmed && millis() - lastRectAt > FAILSAFE_MS) {
    failsafeDimmed = true;
    applyBrightness();
  }
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') {
      line.trim();
      handle(line);
      // Tried against a reply that sometimes sits unsent until the host's next
      // write, which the host cannot tell apart from a board that died mid-RECT.
      // Measured over a night: this does not fix it and does not even make it
      // rarer - HWCDC::flush only waits for its own ring buffer, and what is
      // already in the USB-Serial-JTAG FIFO still waits for the host. Kept only
      // so the next person does not spend the night re-testing it; the fix that
      // works is on the host side.
      Serial.flush();
      line = "";
    } else if (c != '\r' && line.length() < 64) {
      line += c;
    }
  }
}
