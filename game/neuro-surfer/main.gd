extends Node2D

@export var obstacle_scene: PackedScene
@export var tree_scene: PackedScene
@export var score_label: Label
@export var player: Area2D

@export var start_speed: float = 250.0
@export var max_speed: float = 450.0 
@export var acceleration: float = 20.0
@export var braking_power: float = 100.0

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

func _process(delta):
	current_speed += acceleration * delta
	current_speed = clamp(current_speed, start_speed, max_speed)
	
	score += delta * 100.0
	if score_label:
		score_label.text = "Punkty: %d\nPredkosc: %d" % [int(score), int(current_speed)]
		
	current_spawn_interval = lerp(max_spawn_interval, min_spawn_interval, (current_speed - start_speed) / (max_speed - start_speed))
	
	# przeszkody na torze
	time_since_last_spawn += delta
	if time_since_last_spawn >= current_spawn_interval:
		_spawn_obstacle()
		time_since_last_spawn = 0.0

	# drzewa na poboczu
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
