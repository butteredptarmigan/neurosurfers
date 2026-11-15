import socket
import json

UDP_IP = "127.0.0.1"
UDP_PORT = 5005
godot_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

def send_godot_command(command_dict):
    try:
        message = json.dumps(command_dict, separators=(',', ':')).encode('utf-8')
        godot_socket.sendto(message, (UDP_IP, UDP_PORT))
    except Exception as e:
        print(f"Błąd komunikacji z grą: {e}")

# Przykład  głównej pętli klasyfikatora
while is_streaming:
    # 1. Odbierasz okno czasowe (epoch) z EEG
    # epoch_data = buffer.get_latest_data()
    
    # 2. Twój model klasyfikuje sygnał
    # prediction = model.predict(epoch_data)
    
    # 3. Zamieniasz wynik predykcji na akcję w Godocie
    if prediction == 'left_hand_imagery':
        send_godot_command({"type": "ERD", "action": "left"})
        
    elif prediction == 'right_hand_imagery':
        send_godot_command({"type": "ERD", "action": "right"})
        
    elif prediction == 'ssvep_target_10hz':
        send_godot_command({"type": "SSVEP", "map_id": 1})