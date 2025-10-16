from flask import Flask

app = Flask(__name__)

@app.route('/buzz_on')
def buzz_on():
    print("✅ --- ALARM RECEIVED: BUZZER ON --- ✅")
    return "Buzzer is now ON", 200

@app.route('/buzz_off')
def buzz_off():
    print("❌ --- ALARM RECEIVED: BUZZER OFF --- ❌")
    return "Buzzer is now OFF", 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000) # localhost:5000 pr routes check krega