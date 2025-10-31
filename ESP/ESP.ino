const int buzzerPin = 2;

String serialCommand;

void setup() {
  // Start serial communication at 115200 bits per second (baud rate).
  Serial.begin(115200);
  Serial.println("\n--- ESP32 Serial Buzzer Control ---");
  Serial.println("Type 'buzz_on' or 'buzz_off' and press Enter.");

  // Set the buzzer pin as an output.
  pinMode(buzzerPin, OUTPUT);

  // Ensure the buzzer is off at the start.
  digitalWrite(buzzerPin, LOW);
}

void loop() {
  while (Serial.available()) {
    // Read one character at a time.
    char c = Serial.read();
    // If the character is a newline, it means the command is complete.
    if (c == '\n') {
      serialCommand.trim(); // Remove any leading/trailing whitespace.

      // Check if the command matches "buzz_on".
      if (serialCommand.equals("buzz_on")) {
        digitalWrite(buzzerPin, HIGH); // Turn the buzzer ON.
        Serial.println("Command received: buzz_on. Buzzer is now ON.");

      // Check if the command matches "buzz_off".
      } else if (serialCommand.equals("buzz_off")) {
        digitalWrite(buzzerPin, LOW); // Turn the buzzer OFF.
        Serial.println("Command received: buzz_off. Buzzer is now OFF.");
      
      } else {
        Serial.println("Unknown command: '" + serialCommand + "'");
      }

      serialCommand = ""; // Clear the string to be ready for the next command.

    } else {
      // If it's not a newline, add the character to our command string.
      serialCommand += c;
    }
  }
}