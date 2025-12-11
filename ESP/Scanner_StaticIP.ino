#include <WiFi.h>

const char *ssid = "Peeyush's S24 Ultra";
const char *password = "peeyush26";

void setup(){
    Serial.begin(115200);
    WiFi.begin(ssid, password);

    while (WiFi.status() != WL_CONNECTED){
        delay(500);
        Serial.print(".");
    }

    Serial.print("Local IP (Assigned by Router): ");
    Serial.println(WiFi.localIP());

    Serial.print("Gateway: ");
    Serial.println(WiFi.gatewayIP());

    Serial.print("Subnet: ");
    Serial.println(WiFi.subnetMask());

    Serial.print("DNS: ");
    Serial.println(WiFi.dnsIP());

    Serial.print("MAC Address: ");
    Serial.println(WiFi.macAddress());
}

void loop() {}