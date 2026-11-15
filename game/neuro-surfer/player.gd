extends Area2D

@export var max_speed: float = 400.0
@export var turn_speed: float = 8.0 # szybkośćteraz wydaję lerpowania do boku
@export var max_rotation_deg: float = 15.0 # kąt "snowboardowy"
@export var drag: float = 5.0 # długość powrotu do pozycji 0 bez klikania

var bci_direction: float = 0.0
var bci_timer: float = 0.0
var target_velocity_x: float = 0.0
var screen_size: Vector2

# sterowanie menadżerem
@onready var game_manager = get_node("/root/Main")

func _ready():
	screen_size = get_viewport_rect().size
	add_to_group("player")

func _process(delta):
	var direction = 0.0
	
	# odczyt z klawiatury 
	if Input.is_action_pressed("ui_left"):
		direction = -1.0
		if game_manager: game_manager.reward_player(delta)
	elif Input.is_action_pressed("ui_right"):
		direction = 1.0
		if game_manager: game_manager.reward_player(delta)
		
	# nadpisanie sygnałem BCI z Pythona
	if bci_timer > 0:
		direction = bci_direction
		bci_timer -= delta
		# Sygnał BCI też powinien dawać graczowi kontrolę nad prędkością
		if game_manager: game_manager.reward_player(delta)
		
	# fizyka i bezwładność
	if direction != 0:
		target_velocity_x = lerp(target_velocity_x, direction * max_speed, turn_speed * delta)
	else:
		target_velocity_x = lerp(target_velocity_x, 0.0, drag * delta)
		
	position.x += target_velocity_x * delta
	position.x = clamp(position.x, 350, 1570)
	
	# spinning sprite'a proporcjonalnie do prędkości
	rotation_degrees = (target_velocity_x / max_speed) * max_rotation_deg
func _on_area_entered(area):
	if area.is_in_group("obstacle"):
		print("Oh no! You hit:", area.name)
		if game_manager:
			game_manager.trigger_crash()
			
func apply_bci_command(action: String):
	if action == "left":
		bci_direction = -1.0
	elif action == "right":
		bci_direction = 1.0    
	bci_timer = 0.3
