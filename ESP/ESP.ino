#include <WiFi.h>
#include <WebServer.h>

#define BUZZER_PIN 19  // GPIO pin for the buzzer

// WiFi credentials
const char* ssid = "realme 8s 5G";
const char* password = "987654321";

WebServer server(80);

// Track buzzer state and timing
bool buzzerState = false;
unsigned long buzzerOnTime = 0;
const unsigned long BUZZER_DURATION = 2000;  // 2 seconds in milliseconds

void setup() {
  Serial.begin(115200);
  Serial.setTimeout(10);
  pinMode(BUZZER_PIN, OUTPUT);
  digitalWrite(BUZZER_PIN, LOW);

  // Connect to WiFi
  WiFi.begin(ssid, password);
  Serial.print("Connecting to WiFi");
  unsigned long startAttemptTime = millis();
  const unsigned long wifiTimeout = 10000;  // 10 seconds

  while (WiFi.status() != WL_CONNECTED && millis() - startAttemptTime < wifiTimeout) {
    delay(500);
    Serial.print(".");
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\n✅ WiFi connected. IP address:");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println("\n❌ WiFi connection failed. Continuing without WiFi.");
  }

  // Define HTTP endpoints
  server.on("/buzz_on", HTTP_GET, []() {
    buzzerState = true;
    buzzerOnTime = millis();  // Start the 2-second timer
    server.send(200, "text/plain", "Buzzer ON for 2 seconds");
  });

  // Optional manual off (if you want to use it too)
  server.on("/buzz_off", HTTP_GET, []() {
    buzzerState = false;
    server.send(200, "text/plain", "Buzzer OFF manually");
  });

  server.begin();
  Serial.println("HTTP server started");
}

void loop() {
  server.handleClient();

  // Handle USB serial input
  if (Serial.available()) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();

    if (cmd == "buzz_on") {
      buzzerState = true;
      buzzerOnTime = millis();
      Serial.println("Buzzer ON via USB");
    } else if (cmd == "buzz_off") {
      buzzerState = false;
      Serial.println("Buzzer OFF via USB");
    } else {
      Serial.println("Unknown command: " + cmd);
    }
  }

  // Auto turn off buzzer after 2 seconds
  if (buzzerState && (millis() - buzzerOnTime > BUZZER_DURATION)) {
    buzzerState = false;
    Serial.println("Buzzer auto-OFF after 2 seconds");
  }

  // Apply buzzer state to pin
  digitalWrite(BUZZER_PIN, buzzerState ? HIGH : LOW);
}
