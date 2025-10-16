const int buzzerPin = D2;
void setup() {
  pinMode(buzzerPin, OUTPUT);
  digitalWrite(buzzerPin, LOW);
}
void loop() {
  digitalWrite(buzzerPin, HIGH); 
  delay(1000);  
  digitalWrite(buzzerPin, LOW);
  delay(1000);
}
