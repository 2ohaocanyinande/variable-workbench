#pragma once
#include "esp_err.h"
esp_err_t sensor_init(void);
esp_err_t sensor_read_temperature(float *value);
