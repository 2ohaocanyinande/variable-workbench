#include <math.h>
#include "motor.h"

// Simulation only: no GPIO, PWM, motor driver, or physical motor is operated.
motor_t drive_motor = {.duty_percent = 0.0f, .enabled = false};
static float speed = 0.0f;

esp_err_t motor_set_duty(motor_t *motor, float duty)
{
    (void)speed;
    if (!motor || !isfinite(duty) || duty < MOTOR_DUTY_MIN || duty > MOTOR_DUTY_MAX) {
        return ESP_ERR_INVALID_ARG;
    }
    motor->duty_percent = duty;
    return ESP_OK;
}

esp_err_t motor_set_enabled(motor_t *motor, bool enabled)
{
    if (!motor) return ESP_ERR_INVALID_ARG;
    motor->enabled = enabled;
    return ESP_OK;
}
