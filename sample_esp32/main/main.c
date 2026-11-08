#include <math.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/uart.h"
#include "cJSON.h"
#include "motor.h"
#include "sensors.h"

typedef struct {
    const char *id;
    bool writable;
    bool boolean;
    double minimum;
    double maximum;
    esp_err_t (*get)(double *value);
    esp_err_t (*set)(double value);
} bridge_field_t;

// Generated from user-selected, source-verified fields by the local workbench.
#include "generated_bridge.inc"

static void add_value(cJSON *object, const bridge_field_t *field)
{
    double value;
    esp_err_t err = field->get(&value);
    if (err != ESP_OK || !isfinite(value)) {
        cJSON *error = cJSON_AddObjectToObject(object, field->id);
        cJSON_AddStringToObject(error, "error", esp_err_to_name(err));
    } else if (field->boolean) {
        cJSON_AddBoolToObject(object, field->id, value != 0);
    } else {
        cJSON_AddNumberToObject(object, field->id, value);
    }
}

static void process(const char *line)
{
    cJSON *request = cJSON_Parse(line);
    cJSON *reply = cJSON_CreateObject();
    const cJSON *id = cJSON_GetObjectItemCaseSensitive(request, "id");
    const cJSON *op = cJSON_GetObjectItemCaseSensitive(request, "op");
    cJSON_AddNumberToObject(reply, "id", cJSON_IsNumber(id) ? id->valuedouble : -1);
    cJSON_AddStringToObject(reply, "schema_id", BRIDGE_SCHEMA_ID);
    const char *error = NULL;
    if (!cJSON_IsNumber(id) || !cJSON_IsString(op)) {
        error = "invalid_request";
    } else if (strcmp(op->valuestring, "hello") == 0) {
        cJSON_AddStringToObject(reply, "device", "ESP32-S3 / variable workbench demo");
        cJSON_AddStringToObject(reply, "protocol", "workbench/1");
        cJSON_AddNumberToObject(reply, "field_count", sizeof(bridge_fields) / sizeof(bridge_fields[0]));
    } else if (strcmp(op->valuestring, "get_all") == 0) {
        cJSON *values = cJSON_AddObjectToObject(reply, "values");
        for (size_t i = 0; i < sizeof(bridge_fields) / sizeof(bridge_fields[0]); i++) {
            add_value(values, &bridge_fields[i]);
        }
    } else if (strcmp(op->valuestring, "set") == 0) {
        const cJSON *schema = cJSON_GetObjectItemCaseSensitive(request, "schema_id");
        const cJSON *field_id = cJSON_GetObjectItemCaseSensitive(request, "field");
        const cJSON *value = cJSON_GetObjectItemCaseSensitive(request, "value");
        const bridge_field_t *field = NULL;
        if (cJSON_IsString(field_id)) {
            for (size_t i = 0; i < sizeof(bridge_fields) / sizeof(bridge_fields[0]); i++) {
                if (strcmp(bridge_fields[i].id, field_id->valuestring) == 0) field = &bridge_fields[i];
            }
        }
        if (!cJSON_IsString(schema) || strcmp(schema->valuestring, BRIDGE_SCHEMA_ID) != 0) error = "schema_mismatch";
        else if (!field) error = "unknown_field";
        else if (!field->writable) error = "read_only";
        else if (field->boolean ? !cJSON_IsBool(value) : !cJSON_IsNumber(value)) error = "type_mismatch";
        else {
            double number = field->boolean ? cJSON_IsTrue(value) : value->valuedouble;
            if (!isfinite(number) || number < field->minimum || number > field->maximum) error = "out_of_range";
            else {
                esp_err_t err = field->set(number);
                if (err != ESP_OK) error = esp_err_to_name(err);
                else {
                    cJSON *values = cJSON_AddObjectToObject(reply, "values");
                    add_value(values, field);
                }
            }
        }
    } else error = "unknown_operation";
    cJSON_AddBoolToObject(reply, "ok", error == NULL);
    if (error) cJSON_AddStringToObject(reply, "error", error);
    char *text = cJSON_PrintUnformatted(reply);
    if (text) { printf("%s\n", text); free(text); }
    cJSON_Delete(reply);
    cJSON_Delete(request);
}

void app_main(void)
{
    setvbuf(stdout, NULL, _IONBF, 0);
    ESP_ERROR_CHECK(uart_driver_install(UART_NUM_0, 4096, 0, 0, NULL, 0));
    esp_err_t err = sensor_init();
    printf("WORKBENCH_READY sensor=%s motor=SIMULATION\n", esp_err_to_name(err));
    char line[1024];
    size_t used = 0;
    bool overflow = false;
    while (true) {
        uint8_t byte;
        if (uart_read_bytes(UART_NUM_0, &byte, 1, portMAX_DELAY) != 1) continue;
        if (byte == '\r') continue;
        if (byte == '\n') {
            if (!overflow && used) { line[used] = 0; process(line); }
            used = 0;
            overflow = false;
        } else if (used + 1 < sizeof(line)) line[used++] = byte;
        else overflow = true;
    }
}
