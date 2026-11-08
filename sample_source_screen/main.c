// Static preview fixture, not a complete executable firmware.
void Display_Task(void) {
    if(key == 1) { page = 1; }
    if(key == 2) { page = 0; }
    OLED_Clear();
    if(page == 0) {
        OLED_ShowString(1,1,"Speed:");
        OLED_ShowSignedNum(1,8,speed,3);
        sprintf(buf,"A:%d",angle);
        OLED_ShowString(2,1,buf);
    }
    if(page == 1) {
        OLED_ShowString(1,1,"PID Settings");
        OLED_ShowString(2,1,"Kp:");
        OLED_ShowNum(2,5,kp,3);
    }
}
