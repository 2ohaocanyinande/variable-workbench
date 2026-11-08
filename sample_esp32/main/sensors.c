#include "driver/temperature_sensor.h"
#include "sensors.h"

static temperature_sensor_handle_t chip_temperature;
static float speed = 0.0f;

esp_err_t sensor_init(void)
{
    (void)speed;
    temperature_sensor_config_t config = TEMPERATURE_SENSOR_CONFIG_DEFAULT(10, 50);
    esp_err_t err = temperature_sensor_install(&config, &chip_temperature);
    if (err == ESP_OK) err = temperature_sensor_enable(chip_temperature);
    return err;
}

esp_err_t sensor_read_temperature(float *value)
{
    if (!chip_temperature) return ESP_ERR_INVALID_STATE;
    return temperature_sensor_get_celsius(chip_temperature, value);
}
