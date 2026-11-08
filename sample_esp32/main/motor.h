#pragma once
#include <stdbool.h>
#include "esp_err.h"
#define MOTOR_DUTY_MIN 0.0f
#define MOTOR_DUTY_MAX 100.0f
typedef struct {
    float duty_percent;
    bool enabled;
} motor_t;
extern motor_t drive_motor;
esp_err_t motor_set_duty(motor_t *motor, float duty);
esp_err_t motor_set_enabled(motor_t *motor, bool enabled);
