idf_component_register(SRCS "main.c" "motor.c" "sensors.c"
    INCLUDE_DIRS "." REQUIRES driver json esp_psram)
