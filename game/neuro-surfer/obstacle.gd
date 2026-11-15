extends Area2D 

var game_manager = null
var horizon_y: float = 100.0
var bottom_y: float = 1080.0

var lane: float = 0.0

func _ready():
	game_manager = get_node("/root/Main")
	scale = Vector2(0.05, 0.05)
	
func _process(delta):
	if game_manager == null: return
		
	position.y += game_manager.current_speed * delta
	
	var depth = (position.y - horizon_y) / (bottom_y - horizon_y)
	
	var current_scale = lerp(0.05, 2.0, depth)
	scale = Vector2(current_scale, current_scale)
	
	var current_half_width = lerp(200.0, 700.0, depth)
	
	position.x = 960.0 + (lane * current_half_width)
	
	if position.y > bottom_y + 200:
		queue_free()
