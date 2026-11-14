extends Area2D

var game_manager = null

func _ready():
	# pobranie referencję do Menedżera z informacją o prędkości świata
	game_manager = get_node("/root/Main")

func _process(delta):
	if game_manager == null:
		return
		
	position.y += game_manager.current_speed * delta
	
	# usuwanie obiektu
	if position.y > get_viewport_rect().size.y + 200:
		queue_free()
