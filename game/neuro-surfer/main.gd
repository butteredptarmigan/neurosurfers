extends Node2D

@export var obstacle_scene: PackedScene
@export var tree_scene: PackedScene
@export var score_label: Label
@export var player: Area2D

@export var start_speed: float = 250.0
@export var max_speed: float = 450.0 
@export var acceleration: float = 20.0
@export var braking_power: float = 100.0

# --- Zmienne Sieciowe (UDP) ---
var udp_peer := PacketPeerUDP.new()
var listen_port: int = 5005

# --- Zmienne Systemu SSVEP ---
enum GameState { PLAYING, SSVEP_CHOICE }
var current_state = GameState.PLAYING
var ssvep_timer: float = 0.0
var ssvep_duration: float = 5.0 
var next_milestone: float = 1000.0 

var current_speed: float = 0.0
var score: float = 0.0
var time_since_last_spawn: float = 0.0
var time_since_last_tree: float = 0.0

var max_spawn_interval: float = 6.0 
var min_spawn_interval: float = 3.5 
var current_spawn_interval: float = 5.0

func _ready():
	current_speed = start_speed
	if score_label: score_label.text = "Punkty: 0"
	
	# nasłuchiwanie UDP
	var err = udp_peer.bind(listen_port)
	if err == OK:
		print("Godot nasłuchuje BCI na porcie: ", listen_port)
	else:
		print("Błąd bindowania portu UDP!")

func _process(delta):
	_poll_udp()
	
	if current_state == GameState.PLAYING:
		_process_playing(delta)
	elif current_state == GameState.SSVEP_CHOICE:
		_process_ssvep(delta)
		
func _process_playing(delta):
	current_speed += acceleration * delta
	current_speed = clamp(current_speed, start_speed, max_speed)
	score += delta * 100.0
	
	if score_label:
		score_label.text = "Punkty: %d\nPredkosc: %d" % [int(score), int(current_speed)]
	
	# SSVEP check
	if score >= next_milestone:
		_start_ssvep_phase()
		
	current_spawn_interval = lerp(max_spawn_interval, min_spawn_interval, (current_speed - start_speed) / (max_speed - start_speed))
	
	time_since_last_spawn += delta
	if time_since_last_spawn >= current_spawn_interval:
		_spawn_obstacle()
		time_since_last_spawn = 0.0

	time_since_last_tree += delta
	if time_since_last_tree >= (current_spawn_interval * 0.4):
		_spawn_tree()
		time_since_last_tree = 0.0
		
func _start_ssvep_phase():
	current_state = GameState.SSVEP_CHOICE
	ssvep_timer = ssvep_duration
	next_milestone += 1500.0
	print("START SSVEP! Brak nowych przeszkód. Czekam na wybór...")
	# miejsce do wywołania rzeczy jak np. show_ssvep_panels()
		
func reward_player(delta):
	current_speed -= braking_power * delta
	if current_speed < start_speed:
		current_speed = start_speed

func trigger_crash():
	score = 0.0
	current_speed = start_speed
	get_tree().call_group("obstacle", "queue_free")

func _spawn_obstacle():
	if obstacle_scene == null: return
	var obs = obstacle_scene.instantiate()
	obs.position.y = 100.0 
	
	obs.lane = randf_range(-0.8, 0.8) 
	
	add_child(obs)

func _spawn_tree():
	if tree_scene == null: return
	var tree_obj = tree_scene.instantiate()
	tree_obj.position.y = 100.0 
	
	if randf() > 0.5:
		tree_obj.lane = randf_range(1.2, 2.2) # Prawe pobocze
	else:
		tree_obj.lane = randf_range(-2.2, -1.2) # Lewe pobocze
		
	add_child(tree_obj)

func _poll_udp():
	while udp_peer.get_available_packet_count() > 0:
		var packet = udp_peer.get_packet()
		#  (CRITICAL FIX)
		var message = packet.get_string_from_utf8().strip_edges()
		
		var json = JSON.new()
		var error = json.parse(message)
		
		if error == OK:
			var data = json.data
			_handle_bci_command(data)
		else:
			print("Błąd parsowania JSON! Linia: ", json.get_error_line(), " Błąd: ", json.get_error_message())
			print("Otrzymana surowa wiadomość: ", message)

func _handle_bci_command(data: Dictionary):
	if data.has("type"):
		if data["type"] == "ERD":
			print("Wykryto ERD (Ruch): ", data["action"])
			if player != null and player.has_method("apply_bci_command"):
				player.apply_bci_command(data["action"])
			
		elif data["type"] == "SSVEP" and current_state == GameState.SSVEP_CHOICE:
			var chosen_map = data["map_id"]
			print("Wykryto SSVEP! Zmieniam mapę na: ", chosen_map)
			
			#podmianka tekstur
			
			# Skoro wybór został dokonany, wracamy do jazdy
			_end_ssvep_phase()
			
func _process_ssvep(delta):
	score += delta * 100.0
	ssvep_timer -= delta
	
	if ssvep_timer <= 0:
		print("SSVEP Timeout! Wracamy do jazdy na starej mapie.")
		_end_ssvep_phase()

func _end_ssvep_phase():
	current_state = GameState.PLAYING
	
