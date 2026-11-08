// Self-made parsing fixture only; not deployable firmware.
void output(int id, uint16_t value) {
 switch (id) {
 case OUT_1:
  __HAL_TIM_SET_COMPARE(&htim3, TIM_CHANNEL_1, value);
  break;
 case OUT_2:
  __HAL_TIM_SET_COMPARE(&htim3, TIM_CHANNEL_2, value);
  break;
 }
}
