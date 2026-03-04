extends SceneTree


func _init() -> void:
	var config = ConfigFile.new()
	var err = config.load("res://export_presets.cfg")
	if err != OK:
		print("[]")
		return

	var preset_names = []

	for section in config.get_sections():
		if section.begins_with("preset."):  # 找到所有 preset.x
			var platform = config.get_value(section, "platform", "")
			var name = config.get_value(section, "name", "")
			# This tool exports to WeChat minigame (web runtime),
			# so only Web presets are valid.
			if name != "" and platform == "Web":
				preset_names.append(name)
	print(JSON.stringify(preset_names))
	quit()
