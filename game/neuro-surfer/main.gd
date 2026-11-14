extends Node2D

@export var obstacle_scene: PackedScene
@export var score_label: Label
@export var player: Area2D

# zmienne prędkości świata
@export var start_speed: float = 250.0
@export var max_speed: float = 450.0 
@export var acceleration: float = 20.0
@export var braking_power: float = 100.0

var current_speed: float = 0.0
var score: float = 0.0
var time_since_last_spawn: float = 0.0

# 4 sekundy wyprzedzenia przy maks. prędkości
var max_spawn_interval: float = 6.0
var min_spawn_interval: float = 3.5 
var current_spawn_interval: float = 2.0

func _ready():
	current_speed = start_speed
	if score_label:
		score_label.text = "Punkty: 0"

func _process(delta):
	# ciągłe przyspieszenie
	current_speed += acceleration * delta
	current_speed = clamp(current_speed, start_speed, max_speed)
	
	# nabijanie punktów
	score += delta * 100.0
	if score_label:
		score_label.text = "Punkty: %d\nPredkosc: %d" % [int(score), int(current_speed)]
		
	#  spawnowanie przeszkód na podstawie prędkości i czasu
	current_spawn_interval = lerp(max_spawn_interval, min_spawn_interval, (current_speed - start_speed) / (max_speed - start_speed))
	
	time_since_last_spawn += delta
	if time_since_last_spawn >= current_spawn_interval:
		_spawn_obstacle()
		time_since_last_spawn = 0.0

# zwolnienie jako  nagroda wywoływana przez Gracza, gdy skręca
func reward_player(delta):
	current_speed -= braking_power * delta
	# lock na świat
	if current_speed < start_speed:
		current_speed = start_speed

# crash gracza w przeszkode
func trigger_crash():
	score = 0.0
	current_speed = start_speed
	# czyszczenie skał po crashu gracza?
	get_tree().call_group("obstacle", "queue_free")

func _spawn_obstacle():
	if obstacle_scene == null:
		return
		
	var obs = obstacle_scene.instantiate()
	var screen_w = get_viewport_rect().size.x
	
	# Ustawienie wyżej nad ekranem (aby gracz miał te 4 sekundy na reakcję zjazdową)
	var spawn_y = - 450
	var spawn_x = randf_range(50, screen_w - 50)
	
	obs.position = Vector2(spawn_x, spawn_y)
	add_child(obs)
