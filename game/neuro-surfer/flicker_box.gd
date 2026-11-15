extends ColorRect

# Częstotliwość migania (w Hz). 10 Hz to domyślny, bezpieczny wybór.
@export var frequency: float = 10.0 

var time_passed: float = 0.0
var toggle_interval: float = 0.0

func _ready():
	if frequency > 0:
		toggle_interval = 1.0 / (frequency * 2.0)

func _process(delta):
	if not is_visible_in_tree():
		return
		
	time_passed += delta
	
	if time_passed >= toggle_interval:
		if modulate.a == 1.0:
			modulate.a = 0.0
		else:
			modulate.a = 1.0
			
		time_passed -= toggle_interval
