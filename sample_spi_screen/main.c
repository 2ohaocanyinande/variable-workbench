// Static preview fixture; not compilable firmware.
float angle=12.5;
void draw(void){
 LCD_ShowString(12,8,(uint8_t*)"SPI SCREEN",WHITE,BLACK,24,0);
 sprintf(buf,"Angle: %.1f",angle);
 LCD_ShowString(12,40,(uint8_t*)buf,0x07E0,BLACK,24,0);
 LCD_ShowString(12,80,(uint8_t*)"SOURCE PREVIEW",WHITE,BLACK,16,0);
}
