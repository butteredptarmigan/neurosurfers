extends Node2D

@export var obstacle_scene: PackedScene
@export var tree_scene: PackedScene
@export var score_label: Label
@export var player: Area2D

@export var calibration_ui: Control
@export var menu_ui: Control

@export var start_speed: float = 250.0
@export var max_speed: float = 450.0 
@export var acceleration: float = 20.0
@export var braking_power: float = 100.0

# --- Zmienne Sieciowe (UDP) ---
var udp_peer := PacketPeerUDP.new()
var listen_port: int = 5005

# --- Zmienne Systemu Stanów ---
enum GameState { CALIBRATION, MENU, PLAYING }
var current_state = GameState.CALIBRATION

var current_speed: float = 0.0
var score: float = 0.0
var time_since_last_spawn: float = 0.0
var time_since_last_tree: float = 0.0

var max_spawn_interval: float = 6.0 
var min_spawn_interval: float = 3.5 
var current_spawn_interval: float = 5.0

func _ready():
	current_speed = start_speed
	
	if score_label: score_label.hide()
	if calibration_ui: calibration_ui.show()
	if menu_ui: menu_ui.hide()
	
	var err = udp_peer.bind(listen_port)
	if err == OK:
		print("Godot nasłuchuje BCI na porcie: ", listen_port)
	else:
		print("Błąd bindowania portu UDP!")

func _process(delta):
	_poll_udp()
	
	# --- AWARYJNE OBEJŚCIE (KLAWIATURA) ---
	if current_state == GameState.CALIBRATION:
		if Input.is_action_just_pressed("ui_accept"):
			print("Awaryjne pominięcie kalibracji (Klawiatura)")
			current_state = GameState.MENU
			if calibration_ui: calibration_ui.hide()
			if menu_ui: menu_ui.show()
			
	elif current_state == GameState.MENU:
		if Input.is_action_just_pressed("ui_accept"):
			print("Awaryjny start gry (Klawiatura)")
			current_state = GameState.PLAYING
			if menu_ui: menu_ui.hide()
			if score_label: score_label.show()
			
	elif current_state == GameState.PLAYING:
		_process_playing(delta)

func _process_playing(delta):
	current_speed += acceleration * delta
	current_speed = clamp(current_speed, start_speed, max_speed)
	score += delta * 100.0
	
	if score_label:
		score_label.text = "Punkty: %d\nPredkosc: %d" % [int(score), int(current_speed)]
		
	current_spawn_interval = lerp(max_spawn_interval, min_spawn_interval, (current_speed - start_speed) / (max_speed - start_speed))
	
	time_since_last_spawn += delta
	if time_since_last_spawn >= current_spawn_interval:
		_spawn_obstacle()
		time_since_last_spawn = 0.0

	time_since_last_tree += delta
	if time_since_last_tree >= (current_spawn_interval * 0.4):
		_spawn_tree()
		time_since_last_tree = 0.0

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
	obs.position.y = 160.0 
	obs.lane = randf_range(-0.8, 0.8) 
	add_child(obs)

func _spawn_tree():
	if tree_scene == null: return
	var tree_obj = tree_scene.instantiate()
	tree_obj.position.y = 160.0 
	
	if randf() > 0.5:
		tree_obj.lane = randf_range(1.2, 2.2) # Prawe pobocze
	else:
		tree_obj.lane = randf_range(-2.2, -1.2) # Lewe pobocze
		
	add_child(tree_obj)

func _poll_udp():
	while udp_peer.get_available_packet_count() > 0:
		var packet = udp_peer.get_packet()
		var message = packet.get_string_from_utf8().strip_edges()
		
		var json = JSON.new()
		var error = json.parse(message)
		
		if error == OK:
			var data = json.data
			_handle_bci_command(data)
		else:
			print("Błąd parsowania JSON! Otrzymana wiadomość: ", message)

func _handle_bci_command(data: Dictionary):
	if not data.has("type"): return
		
	match data["type"]:
		"CALIBRATION_DONE":
			if current_state == GameState.CALIBRATION:
				print("Kalibracja zakończona! Przejście do Menu.")
				current_state = GameState.MENU
				if calibration_ui: calibration_ui.hide()
				if menu_ui: menu_ui.show()
				
		"SSVEP":
			if current_state == GameState.MENU and data.get("action") == "start":
				print("SSVEP wykryty! Startujemy grę.")
				current_state = GameState.PLAYING
				if menu_ui: menu_ui.hide()
				if score_label: score_label.show()
				
		"ERD":
			if current_state == GameState.PLAYING:
				if player != null and player.has_method("apply_bci_command"):
					player.apply_bci_command(data["action"])
