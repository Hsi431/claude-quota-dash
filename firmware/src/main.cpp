#include <Arduino.h>
#include <TFT_eSPI.h>

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
      Serial.printf("ERR timeout got %u of %u\n", (unsigned)got, (unsigned)want);
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
    Serial.println("ERR no-memory");
    return;
  }
  if (readPayload((uint8_t *)pixels, bytes)) {
    // The payload is already in the order the panel wants, byte for byte.
    // Converting it to native uint16 here only earns a second swap inside
    // pushImage, which lands every pixel half a pixel out and fringes edges.
    tft.pushImage(x, y, w, h, pixels);
    lastRectAt = millis();
    if (failsafeDimmed) {
      failsafeDimmed = false;
      applyBrightness();
    }
    Serial.println("OK");
  }
  free(pixels);
}

static void handle(const String &command) {
  if (command == "PING") {
    Serial.printf("PONG %d tdisplay\n", PROTO_VERSION);
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
      line = "";
    } else if (c != '\r' && line.length() < 64) {
      line += c;
    }
  }
}
