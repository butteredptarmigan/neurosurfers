import socket
import json

# Przed uruchomieniem tego skryptu upewnij się, że masz uruchomiony odbiornik UDP na porcie 5005.

UDP_IP = "127.0.0.1"
UDP_PORT = 5005
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

def send_command(command_dict):
    # separators usuwa białe znaki ze stringa JSON
    message = json.dumps(command_dict, separators=(',', ':')).encode('utf-8')
    sock.sendto(message, (UDP_IP, UDP_PORT))
    print(f"[WYSŁANO] -> {message.decode('utf-8')}")

print("--- SYMULATOR BCI (UDP) ---")
print("L - Skręt w lewo (ERD)")
print("R - Skręt w prawo (ERD)")
print("1 - Wybór mapy 1 (SSVEP - 10Hz)")
print("2 - Wybór mapy 2 (SSVEP - 12Hz)")
print("3 - Wybór mapy 3 (SSVEP - 15Hz)")
print("Q - Wyjście")

while True:
    choice = input("\nPodaj komendę: ").strip().upper()
    
    if choice == 'L':
        send_command({"type": "ERD", "action": "left"})
    elif choice == 'R':
        send_command({"type": "ERD", "action": "right"})
    elif choice == '1':
        send_command({"type": "SSVEP", "map_id": 1})
    elif choice == '2':
        send_command({"type": "SSVEP", "map_id": 2})
    elif choice == '3':
        send_command({"type": "SSVEP", "map_id": 3})
    elif choice == 'Q':
        print("Zamykanie...")
        sock.close()
        break
    else:
        print("Nieznana komenda.")