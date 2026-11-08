// Self-authored parsing fixture for the desktop demo, not deployable firmware.
typedef struct { float Kp; float Ki; float Kd; } controller_t;
controller_t angle_loop;
float last_error, sum;
float controller_step(float target,float feedback,controller_t *controller) {
    float error=target-feedback;
    sum+=error;
    float result=controller->Kp*error+controller->Ki*sum+controller->Kd*(error-last_error);
    last_error=error;
    return result;
}
void configure(void) {
    angle_loop.Kp=15.0f;
    angle_loop.Ki=0.0f;
    angle_loop.Kd=0.75f;
    HAL_TIM_PWM_Start(&htim3,TIM_CHANNEL_1);
    HAL_TIM_PWM_Start(&htim3,TIM_CHANNEL_2);
    HAL_TIM_Encoder_Start(&htim2,TIM_CHANNEL_ALL);
}
void observe(void) {
    unsigned count=__HAL_TIM_GET_COUNTER(&htim2);
    unsigned sample=HAL_ADC_GetValue(&hadc1);
    float output=controller_step(0,angle,&angle_loop);
    __HAL_TIM_SET_COMPARE(&htim3,TIM_CHANNEL_1,output);
}
