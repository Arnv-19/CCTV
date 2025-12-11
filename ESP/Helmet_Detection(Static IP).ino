/*
  - GET /buzz_on  -> Turns the buzzer ON.
  - GET /buzz_off -> Turns the buzzer OFF.
  - GET /         -> Shows the current status.
*/

#include <WiFi.h>
#include <WebServer.h>

// Network Credentials
const char* ssid = "Peeyush's S24 Ultra";
const char* password = "peeyush26";

// Static IP Configuration
IPAddress local_IP(10, 235, 72, 82);
IPAddress gateway(10, 235, 72, 34);
IPAddress subnet(255, 255, 255, 0);
IPAddress primaryDNS(8, 8, 8, 8);
IPAddress secondaryDNS(8, 8, 4, 4);

// --- Hardware Pins ---
const int buzzerPin = D1;
const int ledPin = D4;

// Create a web server object that listens on port 80
WebServer server(80);

// String to store incoming serial data
String serialCommand;

// --- Handler Functions for Web Routes ---

// Function to handle the "/buzz_on" request
void handleBuzzOn() {
    digitalWrite(buzzerPin, HIGH);
    digitalWrite(ledPin, HIGH);
    server.send(200, "text/plain", "Buzzer is now ON");
    Serial.println("Request received: /buzz_on. Buzzer turned ON.");
}

// Function to handle the "/buzz_off" request
void handleBuzzOff() {
    digitalWrite(buzzerPin, LOW);
    digitalWrite(ledPin, LOW);
    server.send(200, "text/plain", "Buzzer is now OFF");
    Serial.println("Request received: /buzz_off. Buzzer turned OFF.");
}

// Function to handle the root URL "/"
void handleRoot() {
    String status = digitalRead(buzzerPin) ? "ON" : "OFF";
    String html = "<h1>ESP Buzzer Controller</h1>";
    html += "<p>Buzzer Status: <strong>" + status + "</strong></p>";
    server.send(200, "text/html", html);
    Serial.println("Request received: /. Status page sent.");
}

// Function to handle requests to non-existent pages
void handleNotFound() {
    server.send(404, "text/plain", "404: Not Found");
}

// --- Main Setup ---
void setup() {
    // Start serial communication
    Serial.begin(115200);
    delay(10);
    Serial.println("\n--- ESP Buzzer Controller ---");

    pinMode(buzzerPin, OUTPUT);
    pinMode(ledPin, OUTPUT);
    digitalWrite(buzzerPin, LOW);
    digitalWrite(ledPin, LOW);

    // Configure the Static IP
    if (!WiFi.config(local_IP, gateway, subnet, primaryDNS, secondaryDNS)) {
        Serial.println("Static IP Failed to configure");
    }
    // Connect to the WiFi network
    Serial.print("Connecting to WiFi...");
    Serial.println(ssid);
    WiFi.begin(ssid, password);

    // Wait for the connection to be established
    int retries = 0;
    while (WiFi.status() != WL_CONNECTED && retries < 20) {
        delay(500);
        Serial.print(".");
        retries++;
    }

    // Check if connection was successful
    if (WiFi.status() == WL_CONNECTED) {
        Serial.println("\nWiFi connected!");
        Serial.print("IP address: ");
        Serial.println(WiFi.localIP());

        // Define the server's routes
        server.on("/", HTTP_GET, handleRoot);
        server.on("/buzz_on", HTTP_GET, handleBuzzOn);
        server.on("/buzz_off", HTTP_GET, handleBuzzOff);
        
        // Set up a handler for pages that are not found
        server.onNotFound(handleNotFound);

        // Start the web server
        server.begin();
        Serial.println("HTTP server started. Waiting for requests...");
    } else {
        Serial.println("\nFailed to connect to WiFi. Please check credentials.");
    }
}

// --- Main Loop ---
void loop() {
    // Handle any incoming client requests
    server.handleClient();

    // Handle any incoming Serial port commands
    while (Serial.available()) {
        char c = Serial.read();
        if (c == '\n') {
            serialCommand.trim();
            if (serialCommand.equals("buzz_on")) {
                digitalWrite(buzzerPin, HIGH);
                digitalWrite(ledPin, HIGH);
                Serial.println("Serial command received: buzz_on. Buzzer ON.");
            } else if (serialCommand.equals("buzz_off")) {
                digitalWrite(buzzerPin, LOW);
                digitalWrite(ledPin, LOW);
                Serial.println("Serial command received: buzz_off. Buzzer OFF.");
            }
            serialCommand = ""; // Clear for the next command
        } else {
            serialCommand += c;
        }
    }
}