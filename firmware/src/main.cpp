#include <Arduino.h>
#include <TFT_eSPI.h>

#include <Preferences.h>
#include <WiFi.h>
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
#define DEFAULT_NET_PORT 8782
#define WIFI_WAIT_TIMEOUT_MS 15000
#define HELLO_TIMEOUT_MS 2000
#define NET_CONNECT_TIMEOUT_MS 3000
#define COMMAND_MAX 256

TFT_eSPI tft = TFT_eSPI();
Preferences preferences;
WiFiClient netClient;

static String serialLine;
static String netLine;
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

enum NetState {
  STATE_OFF,
  STATE_WIFI_WAIT,
  STATE_TCP_CONNECT,
  STATE_HELLO_WAIT,
  STATE_UP,
  STATE_BACKOFF,
};

static NetState netState = STATE_OFF;
static String netSsid;
static String netPass;
static String netHost;
static String netToken;
static uint16_t netPort = DEFAULT_NET_PORT;
static bool netEnabled = false;
static uint32_t netStateSince = 0;
static uint32_t helloDeadline = 0;
static uint32_t upSince = 0;
static unsigned int backoffSeconds = 1;
static uint32_t backoffUntil = 0;

static const char *netStateName() {
  switch (netState) {
    case STATE_OFF: return "OFF";
    case STATE_WIFI_WAIT: return "WIFI_WAIT";
    case STATE_TCP_CONNECT: return "TCP_CONNECT";
    case STATE_HELLO_WAIT: return "HELLO_WAIT";
    case STATE_UP: return "UP";
    case STATE_BACKOFF: return "BACKOFF";
  }
  return "OFF";
}

static bool deadlinePassed(uint32_t deadline) {
  return (int32_t)(millis() - deadline) >= 0;
}

static String netIp() {
  if (WiFi.status() == WL_CONNECTED) {
    return WiFi.localIP().toString();
  }
  return "-";
}

static Stream *activeIo() {
  if (netState == STATE_UP) {
    return &netClient;
  }
  return &Serial;
}

static void setNetState(NetState state) {
  netState = state;
  netStateSince = millis();
}

static bool readPayload(Stream *io, uint8_t *dst, size_t want) {
  size_t got = 0;
  uint32_t deadline = millis() + PAYLOAD_TIMEOUT_MS;
  while (got < want) {
    int available = io->available();
    if (available > 0) {
      size_t ask = min((size_t)available, want - got);
      size_t n = io->readBytes((char *)(dst + got), ask);
      if (n > 0) {
        got += n;
        deadline = millis() + PAYLOAD_TIMEOUT_MS;
      }
    } else if (deadlinePassed(deadline)) {
      // Whatever arrives late is pixels, not a command. Drop it here or the
      // reader below parses it as text and every reply after this is skewed.
      uint32_t drainUntil = millis() + 250;
      size_t dropped = 0;
      while (!deadlinePassed(drainUntil)) {
        while (io->available()) {
          io->read();
          dropped++;
          drainUntil = millis() + 250;
        }
        yield();
      }
      io->print("ERR timeout got ");
      io->print((unsigned)got);
      io->print(" of ");
      io->print((unsigned)want);
      io->print(" dropped ");
      io->println((unsigned)dropped);
      return false;
    }
    yield();
  }
  return true;
}

static void applyBrightness() {
  ledcWrite(BACKLIGHT_CHANNEL, failsafeDimmed ? 26 : brightness);
}

static bool parseByte(const String &value, int &result) {
  if (!value.length()) return false;
  for (size_t i = 0; i < value.length(); i++) {
    if (value[i] < '0' || value[i] > '9') return false;
  }
  result = value.toInt();
  return result >= 0 && result <= 255;
}

static void loadNetConfig() {
  netSsid = preferences.getString("ssid", "");
  netPass = preferences.getString("pass", "");
  netHost = preferences.getString("host", "");
  netPort = preferences.getUShort("port", DEFAULT_NET_PORT);
  netToken = preferences.getString("token", "");
  netEnabled = preferences.getBool("on", false);
}

static void closeNet(const char *reason) {
  bool hadLink = netState == STATE_TCP_CONNECT ||
                 netState == STATE_HELLO_WAIT || netState == STATE_UP;
  netClient.stop();
  netLine = "";
  if (hadLink && reason) {
    Serial.print("NET link down ");
    Serial.println(reason);
  }
}

static void enterWifiWait() {
  WiFi.mode(WIFI_STA);
  setNetState(STATE_WIFI_WAIT);
  WiFi.begin(netSsid.c_str(), netPass.c_str());
  WiFi.setSleep(false);
}

static void enterBackoff(const char *reason) {
  netClient.stop();
  netLine = "";
  Serial.print("NET link down ");
  Serial.println(reason);
  setNetState(STATE_BACKOFF);
  backoffUntil = millis() + backoffSeconds * 1000UL;
  Serial.print("NET backoff ");
  Serial.print(backoffSeconds);
  Serial.println("s");
  if (backoffSeconds < 16) {
    backoffSeconds *= 2;
  } else {
    backoffSeconds = 30;
  }
}

static bool parsePort(const String &value, uint16_t *port) {
  if (!value.length()) {
    return false;
  }
  unsigned long parsed = 0;
  for (unsigned int i = 0; i < value.length(); i++) {
    if (value[i] < '0' || value[i] > '9') {
      return false;
    }
    parsed = parsed * 10 + (value[i] - '0');
    if (parsed > 65535) {
      return false;
    }
  }
  if (!parsed) {
    return false;
  }
  *port = (uint16_t)parsed;
  return true;
}

static bool setNetValue(const String &key, const String &value) {
  if (key == "ssid") {
    netSsid = value;
    preferences.putString("ssid", netSsid);
  } else if (key == "pass") {
    netPass = value;
    preferences.putString("pass", netPass);
  } else if (key == "host") {
    netHost = value;
    preferences.putString("host", netHost);
  } else if (key == "token") {
    netToken = value;
    preferences.putString("token", netToken);
  } else if (key == "port") {
    uint16_t parsed;
    if (!parsePort(value, &parsed)) {
      return false;
    }
    netPort = parsed;
    preferences.putUShort("port", netPort);
  } else {
    return false;
  }
  return true;
}

static void handleNet(Stream *io, const String &cmd) {
  if (cmd == "NET SHOW") {
    io->print("NET on=");
    io->print(netEnabled ? 1 : 0);
    io->print(" ssid=");
    io->print(netSsid);
    io->print(" host=");
    io->print(netHost);
    io->print(" port=");
    io->print(netPort);
    io->print(" pass=");
    io->print(netPass.length() ? "set" : "unset");
    io->print(" token=");
    io->print(netToken.length() ? "set" : "unset");
    io->print(" state=");
    io->print(netStateName());
    io->print(" ip=");
    io->println(netIp());
    return;
  }

  if (cmd.startsWith("NET SET ")) {
    String assignment = cmd.substring(8);
    int separator = assignment.indexOf(' ');
    if (separator <= 0) {
      io->println("ERR net-usage");
      return;
    }
    String key = assignment.substring(0, separator);
    String value = assignment.substring(separator + 1);
    value.trim();
    if (!value.length() || !setNetValue(key, value)) {
      io->println("ERR net-usage");
      return;
    }
    bool restart = netEnabled;
    if (restart) {
      closeNet("config changed");
      setNetState(STATE_OFF);
      backoffSeconds = 1;
    }
    io->println("OK");
    if (restart) {
      enterWifiWait();
    }
    return;
  }

  if (cmd == "NET ON") {
    netEnabled = true;
    preferences.putBool("on", true);
    if (netState == STATE_OFF) {
      backoffSeconds = 1;
      enterWifiWait();
    }
    io->println("OK");
    return;
  }

  if (cmd == "NET OFF") {
    netEnabled = false;
    preferences.putBool("on", false);
    closeNet("disabled");
    WiFi.disconnect(false);
    setNetState(STATE_OFF);
    io->println("OK");
    return;
  }

  if (cmd == "NET CLEAR") {
    closeNet("cleared");
    preferences.clear();
    netSsid = "";
    netPass = "";
    netHost = "";
    netPort = DEFAULT_NET_PORT;
    netToken = "";
    netEnabled = false;
    WiFi.disconnect(false);
    setNetState(STATE_OFF);
    io->println("OK");
    return;
  }

  io->println("ERR net-usage");
}

static void handleRect(Stream *io, const String &command) {
  int x, y, w, h;
  char extra;
  if (sscanf(command.c_str(), "RECT %d %d %d %d %c", &x, &y, &w, &h, &extra) != 4 ||
      w <= 0 || h <= 0 || x < 0 || y < 0 || x + w > SCREEN_WIDTH || y + h > SCREEN_HEIGHT) {
    io->println("ERR bad-rect");
    return;
  }

  size_t pixelsCount = (size_t)w * h;
  size_t bytes = pixelsCount * 2;
  uint16_t *pixels = (uint16_t *)ps_malloc(bytes);
  if (!pixels) pixels = (uint16_t *)malloc(bytes);
  if (!pixels) {
    io->printf("ERR no-memory want %u psram %lu block %u heap %lu\n",
               (unsigned)bytes, (unsigned long)ESP.getFreePsram(),
               (unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_SPIRAM),
               (unsigned long)ESP.getFreeHeap());
    rectFailures++;
    return;
  }
  uint32_t startedAt = millis();
  if (readPayload(io, (uint8_t *)pixels, bytes)) {
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
    io->println("OK");
  } else {
    rectFailures++;
  }
  free(pixels);
}

static void handle(Stream *io, const String &command, bool fromNet) {
  if (command.startsWith("NET")) {
    if (fromNet) {
      io->println("ERR net-usage");
    } else {
      handleNet(io, command);
    }
    return;
  }
  if (command == "PING") {
    io->printf("PONG %d tdisplay up=%lu rects=%lu fails=%lu lastrect=%lums "
               "heap=%lu psram=%lu psramblock=%u\n",
               PROTO_VERSION, (unsigned long)millis(), (unsigned long)rectCount,
               (unsigned long)rectFailures, (unsigned long)lastRectMs,
               (unsigned long)ESP.getFreeHeap(), (unsigned long)ESP.getFreePsram(),
               (unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_SPIRAM));
  } else if (command.startsWith("RECT ")) {
    handleRect(io, command);
  } else if (command.startsWith("BRI ")) {
    int value;
    if (!parseByte(command.substring(4), value)) {
      io->println("ERR bad-bri");
    } else {
      brightness = (uint8_t)value;
      applyBrightness();
      io->println("OK");
    }
  } else if (command == "CLR") {
    tft.fillScreen(TFT_BLACK);
    io->println("OK");
  } else if (command.length()) {
    io->printf("ERR unknown %s\n", command.c_str());
  }
}

static void pollCommands(Stream *io, String *line, bool fromNet) {
  while (io->available()) {
    int value = io->read();
    if (value < 0) {
      return;
    }
    char c = (char)value;
    if (c == '\n') {
      line->trim();
      handle(io, *line, fromNet);
      *line = "";
    } else if (c != '\r' && line->length() < COMMAND_MAX) {
      *line += c;
    }
  }
}

static bool sendGreeting() {
  String greeting = "HELLO 1 tdisplay ";
  greeting += netToken;
  greeting += "\n";
  return netClient.print(greeting) == greeting.length();
}

static void pollHello() {
  while (netClient.available()) {
    int value = netClient.read();
    if (value < 0) {
      return;
    }
    char c = (char)value;
    if (c == '\n') {
      if (netLine == "OK") {
        setNetState(STATE_UP);
        upSince = millis();
        Serial.print("NET link up ");
        Serial.print(netHost);
        Serial.print(":");
        Serial.println(netPort);
      } else {
        enterBackoff("auth");
      }
      netLine = "";
      return;
    }
    if (c != '\r') {
      if (netLine.length() >= COMMAND_MAX) {
        enterBackoff("hello too long");
        return;
      }
      netLine += c;
    }
  }
}

static void stepNet() {
  if (!netEnabled) {
    return;
  }

  switch (netState) {
    case STATE_OFF:
      enterWifiWait();
      break;
    case STATE_WIFI_WAIT:
      if (WiFi.status() == WL_CONNECTED) {
        Serial.print("NET wifi up ip=");
        Serial.println(netIp());
        setNetState(STATE_TCP_CONNECT);
      } else if (millis() - netStateSince >= WIFI_WAIT_TIMEOUT_MS) {
        enterBackoff("wifi timeout");
      }
      break;
    case STATE_TCP_CONNECT:
      if (WiFi.status() != WL_CONNECTED) {
        enterBackoff("wifi lost");
        break;
      }
      if (netClient.connect(netHost.c_str(), netPort, NET_CONNECT_TIMEOUT_MS)) {
        netClient.setNoDelay(true);
        netClient.setTimeout(PAYLOAD_TIMEOUT_MS);
        netLine = "";
        setNetState(STATE_HELLO_WAIT);
        if (!sendGreeting()) {
          enterBackoff("write");
        } else {
          helloDeadline = millis() + HELLO_TIMEOUT_MS;
        }
      } else {
        enterBackoff("connect");
      }
      break;
    case STATE_HELLO_WAIT:
      if (WiFi.status() != WL_CONNECTED) {
        enterBackoff("wifi lost");
      } else if (!netClient.connected()) {
        enterBackoff("closed");
      } else if (deadlinePassed(helloDeadline)) {
        enterBackoff("hello timeout");
      } else {
        pollHello();
      }
      break;
    case STATE_UP:
      if (WiFi.status() != WL_CONNECTED) {
        enterBackoff("wifi lost");
      } else {
        pollCommands(&netClient, &netLine, true);
        if (!netClient.connected()) {
          enterBackoff("closed");
        } else if (millis() - upSince >= 60000UL) {
          backoffSeconds = 1;
        }
      }
      break;
    case STATE_BACKOFF:
      if (deadlinePassed(backoffUntil)) {
        enterWifiWait();
      }
      break;
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
    if (previous == HIGH && stable == LOW) {
      Stream *io = activeIo();
      io->print("BTN ");
      io->println(id);
    }
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
  preferences.begin("net", false);
  lastRectAt = millis();
  // A silent RECT and a board that rebooted mid-RECT look identical from the
  // host. This line is how the host tells them apart.
  delay(50);
  Stream *bootIo = activeIo();
  bootIo->printf("BOOT %d tdisplay reset=%d heap=%lu psram=%lu\n",
                 PROTO_VERSION, (int)esp_reset_reason(),
                 (unsigned long)ESP.getFreeHeap(), (unsigned long)ESP.getFreePsram());

  loadNetConfig();
  if (netEnabled) {
    enterWifiWait();
  }
}

void loop() {
  pollButton(BUTTON_1, 1, lastButton1, stableButton1, button1ChangedAt);
  pollButton(BUTTON_2, 2, lastButton2, stableButton2, button2ChangedAt);
  if (!failsafeDimmed && millis() - lastRectAt > FAILSAFE_MS) {
    failsafeDimmed = true;
    applyBrightness();
  }
  pollCommands(&Serial, &serialLine, false);
  stepNet();
}
